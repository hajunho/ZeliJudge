# 문제 225 이론: 컬럼형 스토리지(Columnar Storage) 엔진 아키텍처와 압축 인코딩, 존 맵(Zone Map) 데이터 스키핑 심층 분석

## 1. 개요: NSM (Row Store) 대 DSM / PAX (Column Store)

관계형 데이터베이스(RDBMS)의 전통적인 스토리지 아키텍처는 **NSM (N-ary Storage Model)** 또는 행 지향(Row-Oriented) 스토리지입니다. 반면 최신 데이터 웨어하우스 및 분석 엔진(ClickHouse, DuckDB, Apache Parquet, Apache ORC, Snowflake)은 **DSM (Decomposition Storage Model)** 또는 **PAX (Partition Attributes Across)** 구조의 컬럼 지향(Columnar) 스토리지를 채택하고 있습니다.

```
[NSM: Row-Oriented Layout (e.g. Postgres Page)]
+-------------------------------------------------------------------+
| Row 1: (ID, Date, Region, Status, Amount, UnusedPayload256B)     |
| Row 2: (ID, Date, Region, Status, Amount, UnusedPayload256B)     |
| Row 3: (ID, Date, Region, Status, Amount, UnusedPayload256B)     |
+-------------------------------------------------------------------+
-> In an analytical query like "SELECT SUM(amount) WHERE date >= 2026":
   Every disk block must be read, transferring 100% of bytes even if only 5% of columns are needed!

[PAX / Columnar Layout (e.g. Parquet / ClickHouse Row Group)]
+-------------------------------------------------------------------+
| Row Group 0 (64,000 Rows):                                        |
|   Column 'ID'     : [id_0, id_1, id_2, ..., id_63999]             |
|   Column 'Date'   : [d_0, d_1, d_2, ..., d_63999] (Zone Map min/max)|
|   Column 'Region' : [r_0, r_1, r_2, ..., r_63999] (Dict Encoded) |
|   Column 'Amount' : [a_0, a_1, a_2, ..., a_63999] (Bit-Packed)   |
|   Column 'Payload': [p_0, p_1, p_2, ..., p_63999] (NOT ACCESSED) |
+-------------------------------------------------------------------+
```

---

## 2. 컬럼형 스토리지의 핵심 최적화 기법

### 2.1 프로젝션 푸시다운 (Projection Pushdown / Pruning)
분석 쿼리(OLAP)는 통상 수십~수백 개의 컬럼 중 2~5개 미만의 컬럼만을 집계합니다. 행 지향 스토리지에서는 단 하나의 컬럼만 필요해도 행 전체를 I/O해야 하므로 디스크 버스 대역폭이 낭비됩니다.
컬럼형 스토리지는 쿼리가 요구하는 컬럼 스트림 파일/페이지 페이지만 파일 오프셋 단위로 선택적 `seek()` 및 `read()`를 수행하여 80~95% 이상의 불필요한 디스크 I/O를 즉시 제거합니다.

### 2.2 존 맵(Zone Map) 및 로우 그룹 메타데이터 스키핑
대규모 컬럼 파일(Parquet, ORC)은 수만~수십만 행 단위의 **로우 그룹(Row Group / Stripe / Data Part)**으로 물리 분할됩니다.
각 로우 그룹의 메타데이터 헤더/푸터에는 각 컬럼의 통계 정보(Statistics: `min_value`, `max_value`, `null_count`, `num_values`)가 사전 계산되어 저장됩니다.

만약 데이터가 정렬 키(Sorting Key / Primary Key, e.g. `timestamp`, `id`) 기준으로 정렬되어 있다면:
- 로우 그룹 0의 `date` 범위: `[20260101, 20260123]`
- 쿼리 조건: `WHERE date >= 20261001`
- `rg_max (20260123) < 20261001` 이 성립하므로, 쿼리 엔진은 **로우 그룹 0의 디스크 블록 전체를 전혀 읽지 않고 스킵**합니다.
- 이를 통해 I/O 비용과 CPU 압축 해제 비용을 극적으로 낮출 수 있습니다.

### 2.3 컬럼 데이터 특화 압축 인코딩 (Compression Encodings)

컬럼 스토리지에서는 동일한 데이터 타입의 값들이 연속적으로 배열되므로 엔트로피가 매우 낮아 강력한 도메인 특화 인코딩을 적용할 수 있습니다:

1. **RLE (Run-Length Encoding)**:
   - 연속해서 동일한 값이 나타나는 경우 `(값, 반복횟수)` 형태로 저장.
   - 예: `[A, A, A, A, A, B, B, B]` $\rightarrow$ `(A, 5), (B, 3)`
   - 정렬된 저카디널리티 컬럼(예: 날짜, 상태 코드)에서 20~50배 압축률 달성.
2. **딕셔너리 인코딩 (Dictionary Encoding)**:
   - 중복 문자열이나 고정 크기 데이터 대신 고유값 목록(Dictionary)을 만들고, 본문 데이터는 1~2바이트 정수 인덱스로 치환.
   - 카디널리티 $C \le 256$인 경우 1바이트 ID 사용.
   - **딕셔너리 폭발 위험(Dictionary Explosion)**:
     만약 사용자 고유 UUID나 타임스탬프처럼 거의 모든 행이 유니크한 고카디널리티 컬럼에 딕셔너리 인코딩을 적용하면, 딕셔너리 크기 + 인덱스 크기가 원시 데이터보다 더 커지는 역효과(Negative Compression)와 인메모리 해시 테이블 OOM이 발생합니다. Parquet 및 ClickHouse는 카디널리티가 임계치(예: 로우 그룹 크기의 70~80%)를 초과하면 즉시 PLAIN 인코딩으로 폴백합니다.
3. **비트 패킹 (Bit-Packing) & 프레임 오브 레퍼런스 (FoR)**:
   - 32비트나 64비트 정수 컬럼이라도 실제 값의 범위가 $0 \sim 7$에 불과하다면, 각 값을 단 3비트만 사용하여 연속된 바이트 스트림에 패킹.
   - FoR(Frame of Reference)과 결합하여 기준값과의 차이($\Delta$)를 비트 패킹함으로써 고효율 압축 실현.
4. **SIMD 벡터화 실행 (Vectorized Execution)**:
   - 컬럼 단위로 연속된 메모리 배열(Dense Array)을 가지므로 Intel AVX-512, ARM NEON 등의 SIMD 명령어를 활용하여 루프당 8~16개 정수를 단일 CPU 클록 사이클에 필터링 및 집계할 수 있습니다.

---

## 3. 실무 엔지니어링 체크리스트 및 튜닝 가이드

| 스토리지 파라미터 | 권장 값 / 전략 | 주의점 및 부작용 |
| :--- | :--- | :--- |
| **Row Group 크기** | 64,000 ~ 1,000,000 행 (128MB ~ 512MB) | 너무 작으면 메타데이터 오버헤드 증가, 너무 크면 존 맵 스키핑 단위가 뭉개짐 |
| **정렬 키 (Sorting Key)** | 쿼리 필터 빈도가 가장 높은 컬럼 (날짜/시간, 테넌트 ID) | 정렬 키가 아닌 컬럼은 존 맵 min/max 범위가 전역으로 퍼져 스키핑 불가 |
| **딕셔너리 임계치** | 고유값 비율 70% 초과 시 PLAIN 폴백 | 고카디널리티 컬럼 딕셔너리 강제 시 메모리 폭발 및 역압축 |
| **Late Materialization** | 필터 조건을 먼저 평가한 후 통과된 행의 프로젝션 컬럼만 읽기 | 결합도가 높거나 다중 조인 시 오프셋 관리 오버헤드 주의 |
