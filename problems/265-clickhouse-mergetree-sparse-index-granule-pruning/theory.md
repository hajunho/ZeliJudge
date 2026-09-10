# [이론 및 배경] ClickHouse MergeTree 스토리지 엔진과 희소 기본 인덱스(Sparse Primary Index)의 내부 아키텍처

## 1. Dense Index (B-Tree) vs Sparse Index (MergeTree)

전통적인 트랜잭션 DB(OLTP)인 MySQL InnoDB나 PostgreSQL은 **밀집 인덱스(Dense Index)** 구조의 B+Tree를 채택합니다.
- 테이블에 10억 개의 행(Row)이 존재하면 B+Tree 인덱스는 10억 개의 노드 엔트리를 유지해야 합니다.
- 행 하나당 인덱스 오버헤드가 수십 바이트에 달하므로 인덱스 크기만 30~50GB에 달하게 되며, RAM 용량을 초과하면 디스크 Random I/O 병목으로 인해 쓰기 및 대규모 집계 성능이 급격히 저하됩니다.

반면 **ClickHouse MergeTree**는 **희소 기본 인덱스(Sparse Primary Index)**를 채택합니다:
- 데이터를 `ORDER BY (PK1, PK2, ...)` 튜플 기준으로 완전히 정렬하여 파트(Part) 파일로 불변(Immutable) 기록합니다.
- 정렬된 행을 일정 크기의 **그래뉼(Granule, 기본 8,192개 행)** 단위로 쪼개고, **각 그래뉼의 첫 번째 행의 기본 키 값만을 인덱스 파일(`primary.idx`)에 단 1개씩 기록**합니다.
- 10억 행의 테이블이라도 그래뉼 수는 약 $10^9 / 8192 \approx 122,000$개에 불과하며, 인덱스 전체 크기는 불과 수 MB(Megabytes) 수준으로 압축되어 RAM에 100% 상주합니다.

---

## 2. 마크 파일(`.mrk2`)과 압축 블록(`.bin`)의 이중 포인터 구조

컬럼 지향(Columnar) 데이터 파일인 `col.bin`과 마크 파일 `col.mrk2`는 긴밀하게 연동됩니다:

$$\text{Data Part} = \{\text{primary.idx}\} \cup \{\text{column.bin}, \text{column.mrk2}\}_{\text{each column}}$$

### 압축 블록과 그래뉼의 관계
- ClickHouse는 컬럼 데이터를 LZ4 또는 ZSTD로 압축할 때, 1개 그래뉼마다 압축하는 것이 아니라 여러 개의 그래뉼(기본 약 64KB uncompressed)을 모아 하나의 **압축 블록(Compressed Block)**으로 묶습니다.
- 마크 파일(`.mrk2`)의 각 엔트리는 특정 그래뉼 $g$가 위치한 지점을 가리키는 **2단계 오프셋(Dual Offset)**을 보관합니다:
  1. `compressed_offset`: `.bin` 파일 내에서 해당 압축 블록이 시작하는 디스크 바이트 오프셋.
  2. `uncompressed_offset`: 해당 압축 블록을 메모리에 해제했을 때, 그래뉼 $g$의 첫 번째 행이 시작하는 오프셋.
- 따라서 어떤 그래뉼들이 스킵(Skip)되면, ClickHouse는 해당 그래뉼이 포함된 압축 블록 번호 전체가 필요 없는 경우 **디스크 블록 읽기(read) 및 압축 해제(decompress)를 1바이트도 수행하지 않고 원천 차단**합니다.

---

## 3. 다차원 사전 순서(Lexicographical Order)와 그래뉼 범위 프루닝

기본 키가 복합 컬럼 `(A, B)`로 구성되어 있을 때, 그래뉼 $g$ 내의 모든 데이터는 사전식 순서(Lexicographical Total Order)를 따릅니다:

$$(a_1, b_1) \le (a_2, b_2) \iff a_1 < a_2 \lor (a_1 == a_2 \land b_1 \le b_2)$$

각 그래뉼 $g$의 키 범위를 $[S_g, E_g]$라고 할 때, 쿼리의 `WHERE` 절이 요구하는 최소·최대 키 튜플 $Q = [Q_{\min}, Q_{\max}]$와의 교집합 여부는 다음 공리로 완전히 결정됩니다:

$$\text{CanContainMatchingRows}(g) \iff S_g \le Q_{\max} \land Q_{\min} \le E_g$$

### 선두 컬럼 규칙 (Leading Column Rule)
- 쿼리 조건이 인덱스의 첫 번째 컬럼(`A`)을 포함하지 않고 두 번째 컬럼(`B`)에만 조건을 거는 경우, 첫 번째 컬럼의 범위가 $[-\infty, +\infty]$가 되므로 대부분의 그래뉼이 $Q$와 겹치게 되어 프루닝 효율이 급감합니다.
- 이것이 ClickHouse 스키마 설계 시 카디널리티가 낮거나 쿼리에서 가장 자주 필터링되는 컬럼을 `ORDER BY`의 첫 번째 위치에 배치해야 하는 핵심 이유입니다.

---

## 4. 보조 데이터 스킵 인덱스 (Data Skipping Index)

기본 키에 포함되지 않은 일반 컬럼(예: 응답시간 `latency_ms`, HTTP 상태코드 `http_status`)의 검색 속도를 높이기 위해 보조 스킵 인덱스를 생성합니다:
1. **MinMax 인덱스**:
   - $K$개의 연속된 그래뉼 블록에 대해 대상 컬럼의 $[\min, \max]$ 값을 기록합니다.
   - `WHERE latency_ms >= 500` 쿼리가 들어왔을 때, 블록의 $\max < 500$이면 해당 $K$개의 그래뉼을 통째로 스킵합니다.
2. **Set 인덱스**:
   - $K$개의 그래뉼 블록 내에 등장한 고유 값들의 집합(Set)을 유지합니다.
   - `WHERE http_status = 500` 쿼리 시, 해당 블록의 Set에 500이 존재하지 않으면 즉시 스킵합니다.

이와 같은 2단계 계층형 프루닝(Primary Key Sparse Pruning $\to$ Secondary Skipping Pruning)을 통해, 수백억 건의 데이터 중 실제로 디스크에서 읽어오는 데이터의 양을 99.9% 이상 절감하여 실시간 분석의 기적을 가능하게 합니다.
