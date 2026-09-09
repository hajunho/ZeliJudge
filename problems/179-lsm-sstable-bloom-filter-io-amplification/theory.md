# LSM-Tree SSTable 블룸 필터(Bloom Filter)와 포인트 룩업(Point Lookup) 읽기 증폭(Read Amplification) 최적화

## 1. 개요: LSM-Tree 스토리지 엔진의 딜레마

현대 대규모 분산 데이터베이스(RocksDB, Apache Cassandra, Google Bigtable, ScyllaDB, LevelDB 등)는 초당 수백만 건의 고속 쓰기를 달성하기 위해 **LSM-Tree (Log-Structured Merge-tree)** 아키텍처를 채택하고 있습니다.

LSM-Tree는 디스크의 임의 쓰기(Random Write)를 순차 쓰기(Sequential Append-Only Write)로 전환하여 최고의 쓰기 성능을 제공하지만, 반대급부로 **읽기 증폭(Read Amplification, $R_A$)**이라는 숙명적인 딜레마를 안고 있습니다:
- 데이터 갱신과 삭제가 제자리(In-Place) 덮어쓰기가 아니라 새 버전의 레코드나 묘비(Tombstone)를 덧붙이는 방식으로 이루어집니다.
- 메모리(`MemTable`)가 가득 차면 디스크의 불변 파일인 `SSTable` (Sorted String Table)로 플러시되며, 여러 레벨(Level 0, Level 1, ..., Level $L$)에 걸쳐 수십~수백 개의 SSTable 파일이 분산 저장됩니다.

---

## 2. 참사의 근원: 포인트 룩업(Point Lookup)과 부존재 키의 읽기 증폭 재앙

### 2.1 존재하지 않는 키(Non-Existent Key)를 조회할 때 일어나는 일

클라이언트가 `GET user:99999999` 단건 포인트 조회를 요청했다고 가정해 봅시다:

```
[클라이언트 GET user:99999999]
          │
          ▼
[1. MemTable 검색] ──> 미발견 (Miss)
          │
          ▼
[2. L0 SSTable 1 검색] ──> 디스크 I/O 발생 (200µs) ──> 미발견 (Miss)
          │
          ▼
[3. L0 SSTable 2 검색] ──> 디스크 I/O 발생 (200µs) ──> 미발견 (Miss)
          │
          ▼
[4. L1 SSTable 3 검색] ──> 디스크 I/O 발생 (200µs) ──> 미발견 (Miss)
          │
          ▼
         ... (수십 개의 SSTable을 차례로 디스크에서 읽음) ...
          │
          ▼
[N. Ln SSTable N 검색] ──> 디스크 I/O 발생 (200µs) ──> 최종 결과: NOT FOUND (404)
```

### 2.2 결과: 읽기 증폭과 I/O 병목으로 인한 시스템 마비

1. 데이터가 실제로 존재하는 키라면 최신 SSTable에서 발견되는 즉시 탐색을 멈출 수 있습니다.
2. 하지만 **"데이터베이스에 존재하지 않는 유령 키"**나 아주 오래전에 저장된 키를 조회할 경우:
   - 스토리지 엔진은 해당 키가 없는지 확신할 수 없으므로, 시스템 내 **모든 SSTable을 최신순부터 가장 오래된 것까지 전수 디스크 I/O로 탐색**해야 합니다!
3. 디스크 읽기 지연시간이 SSTable당 $200\,\mu\text{s}$이고 SSTable이 50개라면:
   $$\text{단 1건의 부존재 키 조회 지연시간} = 50 \times 200\,\mu\text{s} = 10,000\,\mu\text{s} = 10\,\text{ms}$$
4. 해커의 무작위 키 스캔 공격(Cache Penetration)이나 일상적인 부존재 키 질의가 초당 수천 건 유입되면, NVMe SSD의 IOPS가 100% 포화되고 스토리지 엔진이 질식사합니다 (`CATASTROPHIC_READ_AMPLIFICATION_NO_FILTER`).

---

## 3. 구원: SSTable 레벨 블룸 필터(Bloom Filter)

1970년 Burton Howard Bloom이 제안한 **블룸 필터(Bloom Filter)**는 어떤 원소가 집합에 속하는지 여부를 검사하는 공간 효율적인 확률적 자료구조입니다.

LSM-Tree 엔진은 각 SSTable을 디스크에 기록(`Flush` 또는 `Compaction`)할 때, 해당 SSTable에 포함된 모든 키들을 인덱싱하는 블룸 필터를 함께 생성하여 메모리(또는 SSTable 헤더/메타 블록)에 적재합니다.

### 3.1 블룸 필터의 2대 절대 원칙

1. **위음성 절대 불가 (No False Negatives)**:
   - 블룸 필터가 "해당 키는 이 SSTable에 없다(False)"고 응답했다면, 그 키는 **100% 확률로 진짜 없습니다 (True Negative)**.
   - 스토리지 엔진은 해당 SSTable의 디스크 I/O를 완벽하게 건너뛸 수 있습니다 ($0\,\mu\text{s}$ 디스크 읽기).
2. **위양성 가능성 존재 (False Positives Allowed)**:
   - 블룸 필터가 "해당 키가 이 SSTable에 있을 수 있다(True)"고 응답했을 때, 실제로는 키가 없을 수도 있습니다 (**위양성, False Positive**).
   - 이때는 헛걸음 디스크 I/O가 1회 발생하지만, 필터의 수학적 확률에 의해 위양성률(FPR)을 $1\%$ 이하로 통제할 수 있습니다.

---

## 4. 수학적 최적화: 비트 할당과 Kirsch-Mitzenmacher 더블 해싱

### 4.1 키당 비트 수(Bits-per-key, $m/n$)와 위양성률(FPR)

SSTable의 총 키 수를 $n$, 비트 배열의 크기를 $m$이라 할 때, 키당 할당 비트 수 $c = m/n$입니다.
최적 해시 함수 개수 $k$는 다음과 같습니다:

$$k = \text{round}\left(\frac{m}{n} \times \ln 2\right) \approx \text{round}(0.693 \times c)$$

최적 $k$를 사용할 때의 이론적 위양성률($p$)은 다음과 같습니다:

$$p = \left(1 - e^{-k n / m}\right)^k \approx (0.6185)^{m/n}$$

| $m/n$ (Bits/Key) | 최적 해시 함수 수 $k$ | 이론적 위양성률 (FPR) | 1,000건 부존재 쿼리 시 낭비 디스크 I/O |
| :---: | :---: | :---: | :---: |
| **0 (미사용)** | 0 | **$100\%$** | **1,000회 디스크 I/O (재앙)** |
| **2.0** | 1 | $\approx 38.2\%$ | ~382회 디스크 I/O (캐시 오염) |
| **5.0** | 3 | $\approx 9.2\%$ | ~92회 디스크 I/O |
| **10.0 (표준)** | **7** | **$\approx 0.82\% \approx 1\%$** | **단 8회 디스크 I/O (99.2% 차단!)** |
| **14.0 (고정밀)** | **10** | **$\approx 0.12\%$** | **단 1회 디스크 I/O (99.9% 차단!)** |

RocksDB와 Cassandra는 기본값으로 **$10.0 \text{ bits/key}$**를 사용하여, 메모리는 키당 1.25바이트만 소모하면서 부존재 키 디스크 I/O의 **$99\%$를 메모리에서 사전 차단**합니다!

### 4.2 Kirsch-Mitzenmacher 더블 해싱 최적화

블룸 필터에서 $k$개의 서로 다른 독립 암호학적 해시 함수($H_1, H_2, \dots, H_k$)를 계산하는 것은 CPU 비용이 매우 큽니다.
Adam Kirsch와 Michael Mitzenmacher의 연구(2006)에 따르면, **단 2개의 기본 64비트 해시($h_1, h_2$)만으로 $k$개의 해시를 수학적으로 동등하게 시뮬레이션**할 수 있습니다:

$$g_i(x) = (h_1(x) + i \cdot h_2(x)) \pmod m \quad (i = 0, 1, \dots, k-1)$$

이 최적화를 통해 CPU 해시 연산 부하를 $O(k)$에서 $O(1)$로 격감시키고, L1 캐시 친화적인 초고속 비트 조회를 달성합니다.

---

## 5. 실무 포인트 룩업의 3단계 파이프라인

스토리지 엔진은 각 SSTable을 순회할 때 다음 3단계를 거칩니다:

1. **키 범위 검사 (Key Range Check)**:
   - SSTable 메타데이터의 `[min_key, max_key]` 범위에 찾는 키가 속하는지 검사.
   - 범위 밖이면 블룸 필터도 보지 않고 즉시 스킵 ($0.0\,\mu\text{s}$).
2. **블룸 필터 검사 (Bloom Filter Check)**:
   - 범위 내에 속할 경우 메모리 블룸 필터 조회 ($0.5\,\mu\text{s}$).
   - `contains(key) == False`이면 **True Negative**로 즉시 스킵 (디스크 I/O 0회!).
3. **블록 캐시 및 디스크 읽기 (Block Cache / Disk I/O)**:
   - 블룸 필터가 `True`를 반환한 경우에만 블록 캐시(LRU)를 확인 ($5\,\mu\text{s}$)하거나 실제 디스크 블록을 읽음 ($200\,\mu\text{s}$).
