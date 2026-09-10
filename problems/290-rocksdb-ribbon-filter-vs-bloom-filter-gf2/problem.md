# 문제 #290: RocksDB 리본 필터(Ribbon Filter) vs 블룸 필터: GF(2) 결합 선형 방정식(XOR Band Solver), 동일 오탐률(FPR) 대비 30% 메모리 절감 및 SSTable 포인트 쿼리 가속기

## 실무 배경: 페타바이트급 LSM-Tree 스토리지의 블룸 필터 메모리(DRAM) 고갈과 캐시 압박 참사
대규모 NoSQL 및 분산 트랜잭션 DB(CockroachDB, TiKV, Meta RocksDB)를 운영하는 글로벌 클라우드 플랫폼에서, 데이터셋이 수 페타바이트로 증식함에 따라 모든 SSTable 블록의 인덱스와 **블룸 필터(Bloom Filter)**가 DRAM을 15% 이상 집어삼키는 심각한 메모리 압박이 발생했습니다.

SSTable에서 존재하지 않는 키를 읽을 때 디스크 I/O를 방지하기 위해 사용되는 블룸 필터는, 1% 오탐률(False Positive Rate, FPR)을 유지하기 위해 키당 약 **10비트(Bits per key)**의 메모리를 소비합니다:
* 10억(1B) 개의 키가 인덱싱된 RocksDB 인스턴스 $\implies$ 블룸 필터 메타데이터만 **1.2GB**의 DRAM을 점유.
* 노드당 50개 인스턴스 구동 시 $\implies$ 필터 메모리만 **60GB**에 육박하여, 정작 핫 데이터 블록을 캐싱해야 할 블록 캐시(Block Cache)를 밀어내고 극심한 디스크 읽기 I/O 쓰레싱을 유발.

이 문제를 해결하기 위해 Meta(Facebook)는 2021년 USENIX FAST에서 RocksDB의 차세대 확률적 필터인 **리본 필터(Ribbon Filter: Rapid Invertible Boolean Band)**를 발표했습니다:
* **정보이론적 한계 돌파**: 전통적 블룸 필터는 정보이론적 하한선($pprox 1.44 \log_2(1/	ext{FPR})$)에 의해 키당 최소 9.6~10비트가 필수적입니다.
* **GF(2) 결합 선형 시스템**: 리본 필터는 각 키를 이진 유한체 $\mathbb{F}_2$(GF(2)) 상의 좁은 밴드(Ribbon) 행렬 방정식($\mathbf{A}\mathbf{x} = \mathbf{b}$)으로 모델링하고, 가우스 소거법(Gaussian Elimination)으로 해결합니다.
* **30% 메모리 절감**: 동일한 1% 오탐률을 달성하면서도 키당 비트를 **7.0비트** 수준으로 30% 감축하여 수백 테라바이트의 DRAM을 절약합니다.

스토리지 엔진 코어 엔지니어로서, 블룸 필터와 RocksDB 리본 필터의 GF(2) 밴드 소거법 생성 및 조회 알고리즘을 구현하고, 메모리 절감률과 오탐률 무결성을 입증하는 벤치마크 엔진을 구축하십시오.

---

## 블룸 필터 및 리본 필터 사양

### 1. 고전적 블룸 필터 (Bloom Filter)
* 비트 배열 크기: $m = \max(64, N 	imes 	ext{bits\_per\_key})$ (기본 `bits_per_key = 10`).
* 독립 해시 함수 개수: $k = 	ext{num\_hashes}$ (기본 7개).
* 삽입: 키당 $k$개의 해시 인덱스를 비트 배열에 $1$로 설정.
* 조회: $k$개의 비트가 모두 $1$이면 `True`(존재 가능), 하나라도 $0$이면 `False`(확정적 부재).

---

### 2. RocksDB 리본 필터 (Ribbon Filter over $\mathbb{F}_2$)
각 키 $x$에 대해 3개의 독립 해시값을 생성합니다:
1. **시작 열 인덱스**: $start = h_1(x) \pmod{M - w + 1}$ ($M$은 전체 슬롯 수, $w$는 리본 너비 `ribbon_width`, 기본 32).
2. **리본 밴드 마스크**: $w$비트 크기의 이진 마스크 $mask = h_2(x) \pmod{2^w}$ (0이 아니도록 보정).
3. **목표 서명(Signature)**: $r$비트 크기의 타깃 벡터 $\mathbf{sig} = [b_0, \dots, b_{r-1}]$ ($r = 	ext{target\_bits}$, 기본 7비트 $\implies 	ext{FPR} pprox 2^{-r} pprox 0.78\%$).

#### 구축 알고리즘 (Gaussian Elimination over GF(2))
* 총 슬롯 수: $M = \max(w + 10, \lfloor N 	imes 	ext{slot\_ratio} floor + w)$ (기본 `slot_ratio = 1.10`).
* 각 키를 순회하며 밴드 행렬에 삽입:
  - 선두 $1$의 열 위치(`pivot_col`)를 계산.
  - 해당 열에 이미 피벗 행이 존재하면, 기존 피벗과 XOR 소거(GF(2) 덧셈)를 수행하여 선두 $1$을 제거.
  - 빈 피벗 열을 발견하면 새 피벗으로 등록.
* **후진 대입 (Back-Substitution)**:
  - 가장 큰 피벗 열부터 역순으로 탐색하며 필터 해답 벡터 $\mathbf{sol} \in \mathbb{F}_2^{M 	imes r}$의 비트를 확정:
    $$\mathbf{sol}[col][b] = sig[b] \oplus igoplus_{j=1}^{w-1} \left(mask_j \cdot \mathbf{sol}[col + j][b]ight)$$

#### 조회 알고리즘 (Query over GF(2))
* 키의 $start, mask, sig$를 재계산.
* 각 서명 비트 $b \in [0, r-1]$에 대해 밴드 내적 계산:
  $$val_b = igoplus_{j=0}^{w-1} \left(mask_j \cdot \mathbf{sol}[start + j][b]ight)$$
* 모든 $b$에 대해 $val_b == sig_b$이면 `True`(존재 가능), 하나라도 불일치 시 `False`(확정적 부재).

---

## 입력 형식
표준 입력(stdin)으로 JSON 객체가 주어집니다:
```json
{
  "config": {
    "bloom_bits_per_key": 10,
    "bloom_num_hashes": 7,
    "ribbon_width": 32,
    "ribbon_target_bits": 7,
    "ribbon_slot_ratio": 1.10
  },
  "inserted_keys": ["user_0", "user_1", "user_2"],
  "query_keys": ["user_0", "nonexistent_key"]
}
```

## 출력 형식
표준 출력(stdout)으로 JSON 단일 라인으로 메모리 및 쿼리 통계를 출력합니다:
```json
{
  "keys_count": 3,
  "queries_count": 2,
  "memory_comparison": {
    "bloom_bits": 64,
    "ribbon_bits": 315,
    "bits_per_key_bloom": 21.33,
    "bits_per_key_ribbon": 105.0,
    "memory_savings_pct": -392.19
  },
  "query_performance": {
    "actual_positives": 1,
    "actual_negatives": 1,
    "bloom_false_positives": 0,
    "ribbon_false_positives": 0,
    "bloom_fpr_pct": 0.0,
    "ribbon_fpr_pct": 0.0
  }
}
```
