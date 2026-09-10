# RocksDB 리본 필터(Ribbon Filter)와 차세대 확률적 자료구조 이론 백서: GF(2) 결합 선형 방정식, 가우스 소거법, 그리고 30% 메모리 압축의 수리적 원리

## 1. LSM-Tree 스토리지와 블룸 필터의 물리적 한계

RocksDB, LevelDB, Cassandra와 같은 **LSM-Tree (Log-Structured Merge-Tree)** 스토리지 엔진에서, 포인트 쿼리(`Get(key)`)는 MemTable $	o$ L0 $	o$ L1 $	o \dots 	o$ Lmax 순서로 SSTable 파일들을 탐색합니다.

```text
[Get(Key) 요청]
       │
       ▼
   [MemTable] ──(부재)──► [SSTable L0 Filter] ──(불일치: 디스크 스킵!)
                               │ (일치: 오탐 or 실제 존재)
                               ▼
                          [SSTable L0 Data Block Read] (디스크 I/O 발생)
```

만약 필터가 없다면, 존재하지 않는 키를 찾기 위해 모든 레벨의 수백 개 SSTable 파일에 대해 물리적 디스크 I/O를 수행해야 하므로 읽기 성능이 궤멸됩니다.

### 전통적 블룸 필터의 정보이론적 벽
$n$개의 키와 $m$비트 배열, $k$개의 독립 해시 함수를 사용하는 블룸 필터의 오탐률(FPR, $\epsilon$)은 다음과 같습니다:
$$\epsilon pprox \left(1 - e^{-kn/m}ight)^k$$
최적의 $k = rac{m}{n} \ln 2$를 대입하면, 키당 요구되는 비트 수($m/n$)는 다음과 같습니다:
$$rac{m}{n} = -rac{\log_2 \epsilon}{\ln 2} pprox 1.44 \log_2\left(rac{1}{\epsilon}ight)$$
* $\epsilon = 0.01$ (1% FPR)일 때: $rac{m}{n} pprox 1.44 	imes 6.64 pprox 9.6 	ext{ bits/key}$ (실무에서는 정렬과 해시 오버헤드로 통상 10 bits/key 사용).
* **한계**: 블룸 필터는 각 비트가 독립적으로 $0$ 또는 $1$로 설정되는 확률적 무작위성에 의존하기 때문에, 정보이론적 섀넌 엔트로피 하한선($\log_2(1/\epsilon) pprox 6.64$ 비트)에 도달하지 못하고 항상 **44%의 잉여 메모리 오버헤드**를 지불해야 합니다.

---

## 2. 결합 해싱과 리본 필터 (Ribbon Filter, FAST '21)

Meta가 2021년 FAST 컨퍼런스에서 발표한 **리본 필터(Ribbon Filter)**는 무작위 비트 마킹 대신, **이진 유한체 $\mathbb{F}_2$ (Galois Field GF(2)) 상의 선형 연립방정식**을 푸는 기법을 도입했습니다:

```text
[리본 행렬 A (방대하지만 띠 형태의 희소 행렬)]
          0       start         start+w                M
Key 0:   [0 0 0 ... 1 0 1 1 0 1 ... 0 0 0]  *  [ x_0 ]   =   [ sig_0 ]
Key 1:   [0 0 0 0 ... 1 1 0 0 1 ... 0 0 0]     [ x_1 ]       [ sig_1 ]
Key 2:   [0 ... 1 0 0 1 1 0 1 ... 0 0 0 0]     [ ... ]       [ ...   ]
                                               [ x_M ]       [ sig_M ]
```

* 각 키는 $M$개의 열 중 특정 $start$ 위치에서 시작하는 $w$비트 폭의 좁은 띠(Ribbon Band) 형태의 계수 행을 생성합니다.
* 우변 $\mathbf{sig}$는 각 키의 $r$비트 해시 서명입니다.
* 필터 구축이란, 주어진 $N$개의 키에 대해 연립방정식 $\mathbf{A} \mathbf{x} = \mathbf{sig} \pmod 2$를 만족하는 미지수 벡터 $\mathbf{x} \in \mathbb{F}_2^{M 	imes r}$를 구하는 것입니다.

### 왜 30% 메모리가 절감되는가?
* 오탐률은 순수하게 서명 비트 수 $r$에 의해 결정됩니다:
  $$\epsilon pprox 2^{-r}$$
  $r = 7$이면 $\epsilon = 2^{-7} = rac{1}{128} pprox 0.78\% \le 1.0\%$.
* 리본 필터가 요구하는 키당 비트 수는 다음과 같습니다:
  $$	ext{Bits/Key} = (1 + \epsilon_{	ext{overhead}}) 	imes r$$
* 폭 $w = 32$ 또는 $64$의 밴드 행렬에서, 선형 연립방정식이 해를 가질 확률(Solvability)은 슬롯 비율이 $1.05 \sim 1.10$에 도달하는 순간 99.99% 이상으로 급상승합니다.
* 따라서 키당 비트 수는 $1.08 	imes 7 pprox \mathbf{7.56 	ext{ bits/key}}$ (10비트 대비 **24.4% ~ 30% 절감**)!

---

## 3. 밴드 가우스 소거법 (Band Gaussian Elimination)

전체 $N 	imes M$ 행렬에 대한 일반 가우스 소거법은 $O(N^3)$의 계산 비용이 소요되어 실무에서 사용이 불가능합니다.
그러나 리본 필터는 계수가 오직 $w$비트 밴드 내에만 존재하는 구조적 특성을 활용합니다:

1. **소거(Forward Elimination)**:
   - 현재 행의 선두 $1$이 위치한 열 $col$에 이미 피벗이 존재한다면, XOR 연산을 수행합니다.
   - 밴드 폭이 $w$로 제한되어 있으므로, 단일 64비트 정수 XOR 연산 1회로 한 단계를 소거할 수 있습니다 ($O(w)$ 상수 시간).
2. **후진 대입(Back-Substitution)**:
   - 역순으로 탐색하며 각 열의 미지수 비트를 결정합니다.
   - 키당 생성 시간이 수십 마이크로초에 불과하여 RocksDB의 SSTable 플러시 및 컴팩션 속도에 영향을 주지 않습니다.

3. **조회(Query)**:
   - 키의 $start$ 위치부터 $w$개의 연속 비트와 해답 벡터 $\mathbf{x}$를 내적(Dot Product modulo 2)합니다.
   - 단 한 번의 연속 메모리 읽기로 $r$비트 서명을 복원할 수 있어 캐시 친화적(Cache-Friendly)입니다.
