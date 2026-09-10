# [Pro #268 깊이 읽기] WiscKey와 RocksDB BlobDB: 차세대 SSD 친화적 키-값 분리 아키텍처와 가비지 컬렉션의 수학적 원리

## 1. LSM-Tree의 쓰기 증폭(Write Amplification)과 근본적 한계

로그 구조화 병합 트리(Log-Structured Merge-Tree, LSM-Tree)는 구글 Bigtable, Apache Cassandra, LevelDB, RocksDB 등 현대 분산 데이터 저장소의 핵심 기반 구조로 널리 채택되어 왔습니다. 디스크의 랜덤 쓰기를 메모리 버퍼(MemTable)와 추가 전용 순차 로그(Write-Ahead Log, WAL)를 통해 고속 순차 쓰기로 전환함으로써 HDD 시대의 기계적 탐색 오버헤드를 극복했습니다.

그러나 LSM-Tree에는 필연적인 비용이 따릅니다. 상위 레벨($L_i$)의 SST 파일들이 차오르면 다음 하위 레벨($L_{i+1}$)의 겹치는 키 범위를 갖는 파일들과 병합 정렬(Compaction)을 수행해야 합니다. 레벨 간 크기 비율을 $T$(통상 $T=10$)라 하고 전체 레벨 수를 $L$이라 할 때, 하나의 키-값 쌍이 최하위 레벨에 도달하기까지 평균적으로 발생하는 디스크 쓰기 횟수는 다음과 같이 정의됩니다:

$$WA_{\text{LSM}} \approx O(T \cdot L)$$

일반적인 워크로드에서 $WA_{\text{LSM}}$은 10에서 심할 경우 50 이상에 달합니다. 1GB의 데이터를 데이터베이스에 입력했을 때, 실제 물리 드라이브에는 10GB~50GB의 I/O가 가해지는 것입니다.

특히 키(수십 바이트)에 비해 값(Value)의 크기가 수 KB~수 MB 이상인 대형 객체 워크로드(사진 메타데이터, LLM 임베딩 벡터, 압축된 JSON 문서, 프로토콜 버퍼 등)에서는 재앙적인 성능 저하가 발생합니다. **컴팩션 과정에서 정렬 순서를 결정하는 데 필요한 것은 오직 '키(Key)'뿐임에도 불구하고, 전혀 내용이 바뀌지 않은 거대한 '값(Value)' 페이로드 전체를 수십 번씩 디스크에서 읽고 정렬하여 다시 쓰는 극심한 대역폭 낭비**가 발생하기 때문입니다. 이는 플래시 메모리(SSD)의 쓰기 수명(P/E Cycle)을 급격히 고갈시키고 SSD 컨트롤러 내부의 자체 GC 오버헤드까지 촉발합니다.

---

## 2. WiscKey 패러다임: 키-값 분리(Key-Value Separation)

2016년 USENIX FAST 학회에서 위스콘신-매디슨 대학교 연구진이 발표한 **"WiscKey: Separating Keys from Values in SSD-conscious Storage"** 논문은 최신 고속 SSD의 하드웨어적 특성(우수한 병렬 랜덤 읽기 대역폭)에 착안하여 LSM-Tree의 구조를 완전히 재정의했습니다.

```
       [Client Write Request (Key, Value)]
                        │
         ┌──────────────┴──────────────┐
         ▼ (Size < Threshold)          ▼ (Size >= Threshold)
    [ INLINE Path ]               [ BlobDB Path ]
         │                             │
         │ (Key, Value)                │ 1. Sequential Append Value
         │                             ▼
         │                      [ Immutable Blob File (vLog) ]
         │                             │
         │                             │ 2. Return (File#, Offset, Size, CRC)
         │                             ▼
         └────────────────────► [ LSM-Tree Index ]
                                (Key -> Blob Index / Inline Val)
                                       │
                                       ▼ (Compaction)
                           [ Low Write Amplification! ]
                           (Only keys & pointers move)
```

WiscKey의 핵심 분리 원칙은 다음과 같습니다:
1. **분리 저장**:
   - 키(Key)와 블롭의 물리적 위치 포인터(`BlobIndex = {file_number, offset, size, crc32}`)는 정렬 상태를 유지하는 LSM-Tree(SST 파일)에 저장됩니다.
   - 대형 값(Value) 원본은 LSM-Tree 외부에 별도로 존재하는 추가 전용 블롭 파일(Value Log, vLog)에 기록됩니다.
2. **쓰기 증폭 극소화**:
   - 대형 값 원본은 vLog에 단 한 번 순차적으로 기록된 후 더 이상 컴팩션 과정에서 이동하지 않습니다.
   - LSM-Tree 컴팩션 시에는 오직 크기가 수십 바이트에 불과한 키와 `BlobIndex`만 레벨 간에 이동하므로, 값 데이터에 대한 쓰기 증폭은 이상적으로 $WA \approx 1.0$에 수렴합니다.
3. **읽기 경로(Read Path)**:
   - 클라이언트가 `GET(key)`을 요청하면 먼저 LSM-Tree 인덱스를 탐색합니다.
   - 인덱스에 저장된 항목이 `INLINE`이면 즉시 값을 반환합니다.
   - 인덱스에 저장된 항목이 `BLOB_INDEX`이면 지정된 `file_number`의 파일에서 `offset` 위치로부터 `size` 바이트를 직접 읽어들여 CRC32를 검증한 후 반환합니다.

---

## 3. 블롭 라이프사이클과 가비지 컬렉션(GC)의 수학적 모델

키-값 분리 아키텍처의 가장 중대한 엔지니어링 도전 과제는 **공간 증폭(Space Amplification)의 제어**와 **가비지 컬렉션(Garbage Collection)**입니다.

블롭 파일은 고속 순차 쓰기를 위해 항상 불변(Immutable) 상태로 닫히며 덮어쓰기(In-place update)를 허용하지 않습니다. 따라서 클라이언트가 기존 키를 수정(`PUT`)하거나 삭제(`DELETE`)하면, 기존에 블롭 파일에 쓰여 있던 데이터는 물리적으로 즉시 삭제되지 않고 **쓰레기(Garbage / Dead bytes)**로 남게 됩니다.

### 3.1 가비지 비율(Garbage Ratio)과 트리거 조건
각 블롭 파일 $F$에 대해 다음과 같은 바이트 통계를 추적합니다:
- $S_{\text{total}}(F)$: 파일에 기록된 총 바이트 수
- $S_{\text{live}}(F)$: 현재 유효한 블롭들의 바이트 합
- $S_{\text{garbage}}(F) = S_{\text{total}}(F) - S_{\text{live}}(F)$

파일 $F$의 가비지 비율 $R_{\text{garbage}}(F)$는 다음과 같이 정의됩니다:

$$R_{\text{garbage}}(F) = \frac{S_{\text{garbage}}(F)}{S_{\text{total}}(F)}$$

닫힌 파일(`IMMUTABLE`) 중 $R_{\text{garbage}}(F) \ge \theta_{\text{threshold}}$ (예: 0.30)인 파일만이 GC 대상 후보군(Candidates)으로 선정됩니다.

### 3.2 생존자 재배치(Live Blob Relocation)와 포인터 갱신
수거 대상 파일 $F$에 존재하는 모든 레코드 $r = (k, v, \text{offset})$에 대해, 엔진은 현재 최신 LSM-Tree 인덱스를 조회하여 해당 블롭이 여전히 유효한지 검증합니다:

$$\text{is\_live}(r) = \begin{cases} 
\text{True}, & \text{if } \text{LSM}[k].\text{type} = \text{BLOB\_INDEX} \land \text{LSM}[k].\text{file\_number} = F.\text{num} \land \text{LSM}[k].\text{offset} = r.\text{offset} \\ 
\text{False}, & \text{otherwise (overwritten or deleted)} 
\end{cases}$$

- $\text{is\_live}(r) == \text{True}$인 생존 블롭들은 현재 열려 있는 활성 블롭 파일(`active_fn`)의 끝에 순차적으로 복사(Relocate)됩니다.
- 복사가 완료되면 LSM-Tree의 인덱스 포인터는 새로운 활성 파일 번호와 새로운 오프셋으로 원자적으로 갱신됩니다.
- 모든 생존 블롭의 이동이 끝나면 구 파일 $F$는 완전히 폐기(`PURGED`)되어 디스크 공간이 100% 회수됩니다.

---

## 4. 트레이드오프: 쓰기 증폭(WAF) vs 공간 증폭(SAF)

가비지 컬렉션 임계값 $\theta$는 스토리지 엔진 설계에서 가장 중요한 트레이드오프 조절 손잡이입니다:

1. **$\theta$가 너무 높은 경우 (예: $\theta = 0.8$)**:
   - 가비지가 80% 이상 찰 때까지 GC를 미루므로 생존자 복사량이 적어 GC로 인한 추가 쓰기 증폭은 최소화됩니다.
   - 하지만 쓸모없는 죽은 데이터가 디스크를 오랫동안 차지하므로 **공간 증폭(Space Amplification Factor, SAF)**이 극심해집니다.
2. **$\theta$가 너무 낮은 경우 (예: $\theta = 0.1$)**:
   - 가비지가 조금만 생겨도 즉시 파일을 정리하므로 디스크 공간은 매우 깔끔하게 유지됩니다 ($SAF \approx 1.0$).
   - 그러나 90%에 달하는 유효 데이터를 계속해서 새 파일로 복사해야 하므로 **GC 쓰기 증폭($WA_{\text{GC}}$)**이 다시 급증하여 WiscKey 본래의 쓰기 절감 이점이 희석됩니다.

실제 RocksDB BlobDB 및 TiKV Titan에서는 워크로드 특성에 따라 동적으로 GC 임계값을 조정하거나, 연령 기반 계층(Age-based tiering) 방식을 채택하여 최적의 파레토 프론티어(Pareto Frontier)를 유지합니다.

---

## 5. 프로덕션 구현: RocksDB Integrated BlobDB 및 TiKV Titan

- **RocksDB Integrated BlobDB (v6.18+)**: 초기 BlobDB는 RocksDB 위의 별도 래퍼 계층으로 구현되어 복중 트랜잭션 오버헤드가 컸으나, RocksDB 6.18부터 코어 SST 및 컴팩션 필터 엔진 내부로 완벽히 통합되었습니다. 컴팩션 스레드가 SST를 순회하면서 직접 블롭 파일의 쓰레기 비율을 집계하고 백그라운드 GC를 스케줄링합니다.
- **TiKV Titan**: PingCAP 사가 분산 SQL 데이터베이스 TiKV의 대용량 트랜잭션 페이로드를 처리하기 위해 RocksDB 플러그인 형태로 개발한 대표적인 WiscKey 구현체입니다. 블롭 파일 크기와 가비지 회수율을 세밀하게 제어하여 분산 환경에서 초당 수십만 건의 대형 쓰기를 안정적으로 수용합니다.
