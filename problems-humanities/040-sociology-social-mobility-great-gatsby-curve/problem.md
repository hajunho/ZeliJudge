# 문제 #040: 개천에서 더 이상 용이 나지 않는 이유: 사회학(Sociology) & 계층론: 소로킨의 사회이동, 세대 간 마르코프 전이 행렬(Markov Transition Matrix), 프라이스-비비 이동성 지수(Prais-Bibby Index) 및 위대한 개츠비 곡선(Great Gatsby Curve) 시뮬레이터

## 실무 및 정책 배경: 수저계급론의 계량화와 부의 대물림 방지 사회정책 분석
대통령 직속 국민통합위원회 및 사회정책연구원은 청년 세대 사이에 팽배한 "금수저·흙수저" 계급론과 교육을 통한 계층 이동 사다리의 붕괴 현상을 과학적으로 진단하기 위해 실증적 사회이동성 계량 분석 엔진을 구축하고 있습니다.

2012년 백악관 경제자문위원회 의장이었던 고(故) 앨런 크루거(Alan Krueger) 교수는 마일스 코락(Miles Corak)의 연구를 인용하여 전설적인 경제·사회학적 명제인 **위대한 개츠비 곡선(The Great Gatsby Curve)**을 제시했습니다:
* *"소득 불평등(지니계수)이 심한 사회일수록, 세대 간 계층 이동성(Intergenerational Mobility)은 왜 더 처참하게 얼어붙는가?"*
* *"부모 세대의 소득 5분위 계층이 자녀 세대로 대물림되는 확률은 마르코프 연쇄(Markov Chain)로 어떻게 모델링되는가?"*
* *"최하층이 영원히 바닥에 갇히는 '끈적한 바닥(Sticky Floor)'과 최상층에 진입하지 못하는 '유리천장(Glass Ceiling)' 효과는 사회 전체의 정상 상태 계층 분포(Stationary Distribution)를 어떻게 왜곡하는가?"*

1927년 피티림 소로킨(Pitirim Sorokin)의 고전적 『사회이동론(*Social Mobility*)』 이래, 현대 계층사회학과 노동경제학은 마르코프 전이 확률 행렬($\mathbf{P}$)과 **프라이스-비비 이동성 지수(Prais-Bibby Mobility Index)**를 결합하여 사회의 유동성(Social Fluidity)과 세대 간 탄력성(IGE)을 정밀하게 측정합니다.

사회학 연구원이자 공공 데이터 과학자로서, 5분위 계층 전이 확률 행렬을 바탕으로 계층 상승·하강률, 끈적한 바닥 및 유리천장 지수를 계산하고, 다국가 지니계수와 세대 간 탄력성 간의 개츠비 선형 회귀 모형을 도출하는 사회이동성 시뮬레이터를 구현하십시오.

---

## 사회이동성 및 위대한 개츠비 곡선 알고리즘 사양

### 1. 계층 전이 행렬 사양
5분위 소득 계층:
* `Class 0`: 빈곤층/하층 (Lower 20%)
* `Class 1`: 차상위/노동계층 (Working 20%)
* `Class 2`: 중간계층 (Middle 20%)
* `Class 3`: 중상류층 (Upper-Middle 20%)
* `Class 4`: 최상류층 (Upper 20%)

전이 행렬 $\mathbf{P} \in \mathbb{R}^{5 	imes 5}$:
* $P_{ij} = P(	ext{자녀 계층} = j \mid 	ext{부모 계층} = i)$ (각 행의 합은 $1.0$).

---

### 2. 세부 계산 지표 (`ANALYZE_MOBILITY`)

1. **프라이스-비비 이동성 지수 (Prais-Bibby Mobility Index, $M$)**:
   행렬의 대각합(Trace, 세습·잔류 확률의 합)을 바탕으로 전체 사회의 유동성을 정규화:
   $$M(\mathbf{P}) = rac{k - 	ext{tr}(\mathbf{P})}{k - 1}$$
   ($k = 5$. 완전 세습 항등행렬 시 $M = 0.0$, 완전 균등 기회 사회 시 $M = 1.0$).
2. **계층 이동률 (부모 세대 분포 $\mathbf{w}$ 가중)**:
   - 계층 상승률: $R_{	ext{up}} = \sum_{i < j} w_i P_{ij} 	imes 100\%$
   - 계층 하강률: $R_{	ext{down}} = \sum_{i > j} w_i P_{ij} 	imes 100\%$
   - 세습/잔류율: $R_{	ext{stay}} = \sum_{i} w_i P_{ii} 	imes 100\%$
3. **끈적한 바닥 및 유리천장 지수**:
   - 끈적한 바닥 (Sticky Floor): $P_{0, 0}$ (하층 부모의 자녀가 여전히 하층에 잔류할 확률).
   - 유리천장 비율 (Glass Ceiling Ratio): $rac{P_{0, 4}}{\max(P_{4, 4}, 10^{-6})}$ (하층 출신이 최상층에 도달할 확률 대비 최상층 출신의 최상층 세습 확률의 비).
4. **다음 세대 분포 ($\mathbf{w}_{	ext{next}}$)**:
   $$\mathbf{w}_{	ext{next}} = \mathbf{w} \cdot \mathbf{P}$$
5. **에르고딕 극한 계층 정상분포 ($oldsymbol{\pi}$)**:
   세대 교체가 무한히 거듭될 때 수렴하는 정상 상태 확률 벡터 ($oldsymbol{\pi} = oldsymbol{\pi}\mathbf{P}$, 100회 거듭제곱 반복).
6. **세대 간 소득 탄력성 대용치 (Estimated IGE)**:
   $$IGE pprox 1.0 - M(\mathbf{P})$$

---

### 3. 다세대 마르코프 투영 (`MULTI_GEN_PROJECTION`)
초기 계층 분포 $\mathbf{w}_0$로부터 $G$세대 후까지의 계층 분포 변화 궤적을 순차 계산하여 반환합니다.

---

### 4. 위대한 개츠비 곡선 선형 회귀 (`GATSBY_REGRESSION`)
각 국가의 지니계수($x_i = 	ext{Gini}_i$)와 관측된 세대 간 탄력성($y_i = 1.0 - M_i$) 데이터셋에 대해 최소자승법(OLS) 1차 회귀선 $y = a + b \cdot x$을 적합하고, 목표 국가의 예상 IGE를 예측합니다:
$$b = rac{\sum (x_i - ar{x})(y_i - ar{y})}{\sum (x_i - ar{x})^2}, \quad a = ar{y} - bar{x}$$

---

## 입력 형식
표준 입력(stdin)으로 JSON 객체가 주어집니다:
```json
{
  "operation": "ANALYZE_MOBILITY",
  "transition_matrix": [
    [0.30, 0.30, 0.20, 0.12, 0.08],
    [0.18, 0.32, 0.28, 0.14, 0.08],
    [0.12, 0.20, 0.36, 0.20, 0.12],
    [0.08, 0.14, 0.28, 0.32, 0.18],
    [0.06, 0.10, 0.20, 0.30, 0.34]
  ],
  "initial_distribution": [0.20, 0.25, 0.30, 0.15, 0.10]
}
```

## 출력 형식
표준 출력(stdout)으로 JSON 단일 라인으로 평가 결과를 출력합니다:
```json
{
  "operation": "ANALYZE_MOBILITY",
  "result": {
    "prais_mobility_index": 0.84,
    "mobility_rates": {
      "upward": 34.0,
      "downward": 33.2,
      "immobility": 32.8
    },
    "sticky_floor_prob": 0.3,
    "glass_ceiling_ratio": 0.2353,
    "next_gen_distribution": [0.148, 0.212, 0.264, 0.216, 0.16],
    "steady_state_distribution": [0.14, 0.211, 0.2789, 0.2175, 0.1526],
    "estimated_ige": 0.16
  }
}
```
