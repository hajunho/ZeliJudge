# 문제 #039: 대한민국은 소멸할 것인가?!: 인구통계학(Demography) & 인구지리학: 토머스 맬서스에서 인구 변천 이론(DTM), 레슬리 행렬(Leslie Matrix) 연령별 인구 추계, 부양비 및 인구 절벽(Demographic Cliff) 시뮬레이터

## 실무 및 정책 배경: 합계출산율 0.7명 시대, 국민연금 고갈과 인구 절벽의 엄습
통계청 및 기획재정부 중장기전략위원회는 대한민국 인구 피라미드의 극단적 역삼각형 붕괴와 2040~2060년 국민연금 고갈, 생산가능인구 절벽(Demographic Cliff)에 대응하기 위한 국가 인구 모델링 엔진을 재설계하고 있습니다.

2024년 대한민국 합계출산율은 0.72명으로 전 세계 압도적 최하위를 기록했습니다:
* *"현재 태어나는 유소년 인구가 줄어들면, 20년 뒤 경제활동 인구와 부양비(Dependency Ratio)는 몇 배로 치솟는가?"*
* *"노인 인구가 아이들 수를 추월하는 '노령화지수(Aging Index) 100' 골든크로스는 언제 도래했는가?"*
* *"정년 연장이나 외국인 숙련인력 이민 정책(Net Migration)을 도입하면 인구 절벽의 충격을 몇 년이나 유예할 수 있는가?"*

인구학은 단순한 통계 집계가 아닙니다. 1798년 토머스 맬서스(Thomas Malthus)의 『인구론』 이래, 워런 톰슨의 **인구 변천 이론(Demographic Transition Model, DTM)**과 1945년 패트릭 레슬리(Patrick H. Leslie)가 확립한 **레슬리 행렬(Leslie Matrix)**은 선형대수학의 고유값(Eigenvalue)과 마르코프 연쇄를 결합하여 국가의 흥망성쇠를 수치로 예측하는 가장 정밀한 수학적 사회과학 도구입니다.

인구정책 수석 데이터 과학자로서, 5대 연령 코호트(유소년, 청년, 중년, 장년, 고령층) 간의 출산율(Fecundity)과 생존율(Survival), 순이민(Migration)을 전이시키는 **레슬리 행렬 엔진**을 구현하고, 고령화 단계 전이와 인구 절벽 개시 시점을 정확히 분석하십시오.

---

## 레슬리 행렬 및 인구통계 지표 사양

### 1. 연령 코호트 정의 (5개 집단)
인구 벡터 $\mathbf{n}(t) = [n_0(t), n_1(t), n_2(t), n_3(t), n_4(t)]^T$:
* $n_0$: 유소년 인구 (0~14세, Youth)
* $n_1$: 청년 생산가능인구 (15~29세, Young Working)
* $n_2$: 핵심 생산가능인구 (30~49세, Prime Working)
* $n_3$: 장년 생산가능인구 (50~64세, Mature Working)
* $n_4$: 고령층 인구 (65세 이상, Elderly)
* 총인구: $P_{	ext{total}} = \sum_{i=0}^4 n_i$
* 총 생산가능인구 (15~64세): $P_{	ext{work}} = n_1 + n_2 + n_3$

---

### 2. 레슬리 행렬 이산 전이 공식
각 주기 $t 	o t+1$ (통상 15년 단위 세대 주기):
1. **신규 출생아 ($n_0(t+1)$)**:
   각 코호트의 출산 기여율(Fecundity) $F_i$의 선형 결합:
   $$n_0(t+1) = \sum_{i=0}^4 F_i \cdot n_i(t) + M_0$$
2. **청년·중년·장년 코호트 생존 전이 ($n_i(t+1)$, $i = 1, 2, 3$)**:
   직전 코호트의 생존율 $S_{i-1}$을 곱하여 진급:
   $$n_i(t+1) = S_{i-1} \cdot n_{i-1}(t) + M_i$$
3. **고령층 코호트 ($n_4(t+1)$)**:
   장년층의 신규 고령 진입($S_3 \cdot n_3$)에 더해, 기존 65세 이상 고령자의 생존 유지율($S_4 \cdot n_4$)이 누적 합산(Absorbing Cohort):
   $$n_4(t+1) = S_3 \cdot n_3(t) + S_4 \cdot n_4(t) + M_4$$
* $M_i$는 주기별 순이민자(Net Migration) 수 (음수가 되지 않도록 $\max(0.0, \dots)$ 보정).

---

### 3. 인구통계학적 지표 및 상태 판정 기준
* **고령 인구 비율**: $R_{	ext{elderly}} = rac{n_4}{P_{	ext{total}}} 	imes 100\%$
  - $R_{	ext{elderly}} < 7.0\% \implies$ **청년사회 (`"YOUNG"`)**
  - $7.0\% \le R_{	ext{elderly}} < 14.0\% \implies$ **고령화사회 (`"AGING"`)**
  - $14.0\% \le R_{	ext{elderly}} < 20.0\% \implies$ **고령사회 (`"AGED"`)**
  - $R_{	ext{elderly}} \ge 20.0\% \implies$ **초고령사회 (`"SUPER_AGED"`)**
* **3대 부양비 (Dependency Ratios)**:
  - 유소년 부양비: $D_{	ext{youth}} = rac{n_0}{P_{	ext{work}}} 	imes 100$
  - 노년 부양비: $D_{	ext{old}} = rac{n_4}{P_{	ext{work}}} 	imes 100$
  - 총부양비: $D_{	ext{total}} = D_{	ext{youth}} + D_{	ext{old}}$
* **노령화지수 (Aging Index)**:
  $$I_{	ext{aging}} = rac{n_4}{n_0} 	imes 100$$
  - $I_{	ext{aging}} \ge 100.0$에 최초로 도달하는 주기(Cycle)를 크로스오버 시점(`aging_crossover`)으로 기록.
* **인구 절벽 (Demographic Cliff)**:
  - 생산가능인구 $P_{	ext{work}}$가 최고 정점(Peak)에 도달한 후, 다음 주기에서 최초로 감소세로 돌아선 시점(`demographic_cliff_cycle`)을 탐지.

---

## 입력 형식
표준 입력(stdin)으로 JSON 객체가 주어집니다:
```json
{
  "config": {
    "fecundity": [0.0, 0.4, 0.6, 0.05, 0.0],
    "survival": [0.99, 0.98, 0.95, 0.80, 0.50]
  },
  "initial_population": [10.0, 10.0, 10.0, 8.0, 4.0],
  "cycles": 4,
  "migration_per_cycle": [0.0, 0.0, 0.0, 0.0, 0.0]
}
```

## 출력 형식
표준 출력(stdout)으로 JSON 단일 라인으로 시뮬레이션 결과를 출력합니다:
```json
{
  "cycles_simulated": 4,
  "working_age_peak": {
    "cycle": 1,
    "peak_population": 29.7
  },
  "demographic_cliff": {
    "detected": true,
    "cliff_onset_cycle": 2
  },
  "aging_crossover": {
    "crossover_cycle": 2
  },
  "history": [
    {
      "cycle": 0,
      "population_vector": [10.0, 10.0, 10.0, 8.0, 4.0],
      "analysis": {
        "total_population": 42.0,
        "youth_pop": 10.0,
        "working_pop": 28.0,
        "elderly_pop": 4.0,
        "elderly_ratio_pct": 9.52,
        "society_stage": "AGING",
        "dependency_ratios": {"youth": 35.71, "old_age": 14.29, "total": 50.0},
        "aging_index": 40.0
      }
    }
  ]
}
```
