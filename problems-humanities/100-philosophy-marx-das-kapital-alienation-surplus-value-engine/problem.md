# 칼 마르크스의 자본론과 경제학-철학 수고: 4대 노동 소외(Entfremdung), 잉여가치 착취율 및 이윤율의 경향적 저하(TRPF) 엔진

> **인문학·비즈니스 트랙 100문제 대기록 달성 기념작 (Grand Centennial Milestone #100)**  
> *"인간이 자신의 노동 생산물, 자신의 생명 활동, 자신의 유적 존재(Gattungswesen)로부터 소외될 때, 인간은 다른 인간으로부터도 소외된다."*  
> — 카를 마르크스(Karl Marx), 『1844년 경제학-철학 수고(Ökonomisch-philosophische Manuskripte aus dem Jahre 1844)』

---

## 1. 개요 및 역사철학적 배경

19세기 산업혁명과 자본주의의 폭발적 성장은 인류에게 유례없는 물질적 풍요를 안겨주었으나, 동시에 인간 노동의 본질을 송두리째 뒤흔들었습니다. 청년 마르크스는 1844년 파리 망명 시절 집필한 『경제학-철학 수고』에서 근대 노동자가 직면한 비극을 **'소외(Entfremdung)'**라는 철학적 개념으로 해명하였고, 이후 불후의 명저 『자본론(Das Kapital, 제1권 1867년, 제3권 1894년)』을 통해 자본주의의 작동 원리와 내적 모순을 정밀한 경제학적·수학적 모델로 정식화했습니다.

마르크스 경제철학의 핵심 기둥은 다음과 같습니다:

1. **4대 노동 소외 (Die vierfache Entfremdung der Arbeit)**:
   - **생산물로부터의 소외 (Entfremdung vom Gegenstand)**: 노동자가 땀 흘려 생산한 물건이 노동자의 것이 아니라 자본가의 소유가 되며, 나아가 상품과 화폐라는 거대한 힘으로 노동자를 압제하는 '물신성(Fetishism)'을 띱니다.
   - **생산 행위(노동 과정)로부터의 소외 (Entfremdung im Zeugungsakt)**: 노동이 자아실현이나 창의적 환희가 아니라, 육체를 파괴하고 정신을 황폐화하는 고통스러운 강제 노역이자 생계유지의 비참한 수단으로 전락합니다.
   - **유적 존재(Gattungswesen)로부터의 소외**: 자유롭고 의식적인 창조 활동이라는 인간의 고유한 본질(유적 본질)이 박탈되어, 인간이 단순한 동물적 생존(먹고 자고 번식하는 것)만을 위해 살아가는 기계 부품으로 격하됩니다.
   - **인간으로부터의 소외 (Entfremdung des Menschen vom Menschen)**: 노동자와 노동자, 노동자와 자본가가 공동체적 연대와 협력의 관계가 아니라, 고용 시장과 경쟁 속에서 서로를 물건이나 적대적 착취 대상으로 대면합니다.

2. **잉여가치론과 착취율 (Mehrwerttheorie & Ausbeutungsgrad)**:
   - 하루 노동일($T_{work}$)은 노동자가 자신의 노동력 재생산에 필요한 가치를 생산하는 **필요노동시간($t_{nec}$)**과 자본가에게 무상으로 제공되는 **잉여노동시간($t_{sur}$)**으로 분할됩니다.
   - **잉여가치율(착취율, $s'$)**은 가변자본(임금, $v$)에 대한 잉여가치($s$)의 비율, 즉 $rac{t_{sur}}{t_{nec}} \times 100\%$로 결정됩니다.
   - 자본가는 노동일을 연장하는 **절대적 잉여가치(Absolute Surplus Value)** 추출이나 생산성 향상을 통해 필요노동시간을 줄이는 **상대적 잉여가치(Relative Surplus Value)** 추출을 시도합니다.

3. **자본의 유기적 구성과 이윤율의 경향적 저하 법칙 (TRPF)**:
   - 자본가는 경쟁에서 살아남기 위해 공장에 새로운 기계와 자동화 설비(**불변자본 $c$**)를 지속적으로 투입합니다.
   - 이에 따라 총자본 대비 불변자본의 비중을 나타내는 **자본의 유기적 구성(Organic Composition of Capital, $OCC = \frac{c}{c + v}$)**이 끊임없이 상승합니다.
   - 그러나 가치와 잉여가치를 창출하는 유일한 원천은 오직 살아있는 인간 노동(**가변자본 $v$**)뿐입니다.
   - 기계화가 진전될수록 전체 자본 투입량($c + v$)에 비해 잉여가치를 낳는 노동력($v$)의 상대적 비중이 줄어들므로, 사회 전체의 평균 **이윤율($p' = \frac{s}{c + v}$)**은 필연적으로 하락하는 경향을 띱니다.
   - 이는 필연적으로 자본의 과잉 축적과 과잉 생산, 유효수요 부족에 따른 공황(Crisis of Overaccumulation)을 낳습니다.

본 과제에서는 마르크스의 『경제학-철학 수고』와 『자본론』에 입각하여, 생산 매개변수와 소외 계수, 기술 혁신 라운드를 입력받아 잉여가치 착취율, 복합 소외 지수, 자본 유기적 구성 및 이윤율의 장기 동학(TRPF)을 완벽하게 추적하는 **마르크스 자본론 소외 및 잉여가치 시뮬레이션 엔진**을 구축합니다.

---

## 2. 시스템 아키텍처 및 경제학적 메커니즘

```
+-------------------------------------------------------------------------+
|                  생산 설정 (Production Configuration)                    |
|   노동일: working_day_hours (T)  |  필요노동: necessary_labor_hours (t_nec) |
|   불변자본: constant_capital_c   |  가변자본: variable_capital_v (v)       |
+-------------------------------------------------------------------------+
                                   |
                                   v
+-------------------------------------------------------------------------+
| [1단계] 잉여가치 및 착취율 계산 (Surplus Value & Rate of Exploitation)    |
|   · 잉여노동시간: surplus_hours = max(0.0, round(T - t_nec, 4))          |
|   · 착취율(%): rate_of_exploitation_pct = round((t_sur / t_nec)*100, 2) |
|   · 잉여가치액: surplus_s = round(v * (s' / 100), 2)                     |
+-------------------------------------------------------------------------+
                                   |
                                   v
+-------------------------------------------------------------------------+
| [2단계] 4대 노동 소외 지수 산출 (4-Fold Alienation Profile)              |
|   · a_product: 생산물 전유율     |  a_act: 노동 과정의 기계화/단조성        |
|   · a_species: 유적 본질 억압도   |  a_social: 인간 간 경쟁 및 시장 물화도  |
|   · 복합 소외 지수: composite = round(sum(a_i) / 4.0, 4)                 |
|   · 판정: >= 0.8: RADICAL_FETISHISTIC_ALIENATION                        |
|           >= 0.5: STRUCTURAL_WAGE_LABOR_ALIENATION                      |
|           < 0.5: MILD_COMMODITY_ALIENATION                              |
+-------------------------------------------------------------------------+
                                   |
                                   v
+-------------------------------------------------------------------------+
| [3단계] 초기 거시 지표 (Initial Macro Metrics)                            |
|   · 자본의 유기적 구성: organic_composition = round(c / (c + v), 4)      |
|   · 초기 이윤율(%): initial_rate_of_profit_pct = round(s / (c + v)*100, 2)|
+-------------------------------------------------------------------------+
                                   |
                                   v
+-------------------------------------------------------------------------+
| [4단계] 기술 혁신 라운드별 축적 궤적 (TRPF Simulation Rounds)            |
|   · 매 라운드: c += added_machinery_c, v = max(0.0, v + delta_variable_v)|
|   · 라운드 잉여가치: r_s = round(v * (s' / 100), 2)                      |
|   · 라운드 유기적 구성: r_occ = round(c / (c + v), 4)                    |
|   · 라운드 이윤율(%): r_p' = round(r_s / (c + v) * 100, 2)               |
|   · 위기 상태 판정:                                                      |
|       - r_p' < 10.0% AND r_occ > 0.85: CRISIS_OF_OVERACCUMULATION_TRPF   |
|       - r_p' < 15.0%: FALLING_PROFITABILITY_WARNING                      |
|       - 기타: NORMAL_ACCUMULATION                                        |
+-------------------------------------------------------------------------+
                                   |
                                   v
+-------------------------------------------------------------------------+
| [5단계] 역사철학적 최종 판정 (Systemic Historical Verdict)              |
|   · 최종 이윤율 < 10.0% AND 최종 OCC > 0.85:                             |
|       SYSTEMIC_CRISIS_TRPF_REALIZED                                     |
|   · 최종 이윤율 < 초기 이윤율:                                           |
|       TENDENTIAL_FALL_DEMONSTRATED                                      |
|   · 기타: STABLE_EXPLOITATION_EQUILIBRIUM                               |
+-------------------------------------------------------------------------+
```

---

## 3. 세부 계산 알고리즘 및 규칙 명세

### 3.1 잉여가치 및 착취율 분석 (`surplus_value_analysis`)
- **입력**: `working_day_hours` ($T$), `necessary_labor_hours` ($t_{nec}$), `constant_capital_c` ($c$), `variable_capital_v` ($v$).
- **잉여노동시간**:
  $$t_{sur} = \max\left(0.0, \ 	ext{round}(T - t_{nec}, 4)ight)$$
- **잉여가치율 (착취율 %)**:
  $$s' = 	ext{round}\left(rac{t_{sur}}{\max(0.01, t_{nec})} 	imes 100.0, \ 2ight)$$
- **초기 잉여가치 총액**:
  $$s = 	ext{round}\left(v 	imes rac{s'}{100.0}, \ 2ight)$$

### 3.2 4대 노동 소외 지수 (`alienation_profile`)
- **4대 소외 요소** (각 $[0.0, 1.0]$ 범위 실수):
  - $a_{product}$: `product_appropriation_ratio` (생산물 전유율)
  - $a_{act}$: `work_automation_monotony` (생산 행위 소외 / 기계화 부품화)
  - $a_{species}$: `species_being_suppression` (유적 본질 억압도)
  - $a_{social}$: `interpersonal_competition` (인간 간 상품화 및 경쟁도)
- **복합 소외 지수 (Composite Alienation Index)**:
  $$ar{A} = 	ext{round}\left(rac{a_{product} + a_{act} + a_{species} + a_{social}}{4.0}, \ 4ight)$$
- **소외 판정 (`verdict`)**:
  - $ar{A} \ge 0.8$: `"RADICAL_FETISHISTIC_ALIENATION"` (물신성에 굴복한 극단적 소외)
  - $ar{A} \ge 0.5$: `"STRUCTURAL_WAGE_LABOR_ALIENATION"` (근대 임금 노동의 구조적 소외)
  - $ar{A} < 0.5$: `"MILD_COMMODITY_ALIENATION"` (경미한 상품화 소외)

### 3.3 초기 거시경제 지표 (`initial_macro_metrics`)
- **자본의 유기적 구성 (OCC)**:
  $$OCC_{init} = 	ext{round}\left(rac{c}{\max(0.01, c + v)}, \ 4ight)$$
- **초기 이윤율 (%)**:
  $$p'_{init} = 	ext{round}\left(rac{s}{\max(0.01, c + v)} 	imes 100.0, \ 2ight)$$

### 3.4 기술 혁신 라운드 및 이윤율 저하 궤적 (`accumulation_trajectory`)
`innovation_rounds` 리스트의 각 라운드를 순차적으로 시뮬레이션합니다:
- 각 라운드는 `added_machinery_c` (추가 불변자본)와 `delta_variable_v` (가변자본 변동치)를 가집니다.
- 누적 자본 갱신:
  - $c_{curr} = 	ext{round}(c_{curr} + 	ext{added\_machinery\_c}, \ 2)$
  - $v_{curr} = \max(0.0, \ 	ext{round}(v_{curr} + 	ext{delta\_variable\_v}, \ 2))$
- 라운드 파생 수치:
  - 총자본: $C_{curr} = 	ext{round}(c_{curr} + v_{curr}, \ 2)$
  - 라운드 잉여가치: $s_{curr} = 	ext{round}\left(v_{curr} 	imes rac{s'}{100.0}, \ 2ight)$
  - 라운드 유기적 구성: $OCC_{curr} = 	ext{round}\left(rac{c_{curr}}{\max(0.01, C_{curr})}, \ 4ight)$
  - 라운드 이윤율 (%): $p'_{curr} = 	ext{round}\left(rac{s_{curr}}{\max(0.01, C_{curr})} 	imes 100.0, \ 2ight)$
- **라운드 상태 판정 (`state`)**:
  - $p'_{curr} < 10.0$ 이고 $OCC_{curr} > 0.85$: `"CRISIS_OF_OVERACCUMULATION_TRPF"`
  - 그렇지 않고 $p'_{curr} < 15.0$: `"FALLING_PROFITABILITY_WARNING"`
  - 그 외: `"NORMAL_ACCUMULATION"`

### 3.5 최종 거시 시스템 판정 (`systemic_historical_verdict`)
- 혁신 라운드가 비어있는 경우 최종 이윤율과 OCC는 초기값($p'_{init}, OCC_{init}$)을 사용합니다.
- 혁신 라운드가 존재하는 경우 최종 라운드의 이윤율($p'_{final}$)과 OCC($OCC_{final}$)를 사용합니다.
- 판정 규칙:
  1. $p'_{final} < 10.0$ 이고 $OCC_{final} > 0.85$: `"SYSTEMIC_CRISIS_TRPF_REALIZED"`
  2. $p'_{final} < p'_{init}$: `"TENDENTIAL_FALL_DEMONSTRATED"`
  3. 그 외: `"STABLE_EXPLOITATION_EQUILIBRIUM"`

---

## 4. 입출력 형식 및 제약 조건

### 입력 형식 (JSON)
표준 입력(stdin)으로 단일 JSON 객체가 주어집니다.
```json
{
  "production_config": {
    "working_day_hours": 10.0,
    "necessary_labor_hours": 4.0,
    "constant_capital_c": 2000.0,
    "variable_capital_v": 1000.0
  },
  "alienation_factors": {
    "product_appropriation_ratio": 0.95,
    "work_automation_monotony": 0.85,
    "species_being_suppression": 0.90,
    "interpersonal_competition": 0.80
  },
  "innovation_rounds": [
    { "round": 1, "added_machinery_c": 2000.0, "delta_variable_v": -200.0 },
    { "round": 2, "added_machinery_c": 3000.0, "delta_variable_v": -300.0 },
    { "round": 3, "added_machinery_c": 4000.0, "delta_variable_v": -200.0 }
  ]
}
```

### 출력 형식 (JSON)
표준 출력(stdout)으로 JSON 직렬화 결과를 공백 없는 단일 라인(`separators=(',', ':')`, `ensure_ascii=False`)으로 출력합니다.
```json
{
  "surplus_value_analysis": {
    "working_day_hours": 10.0,
    "necessary_labor_hours": 4.0,
    "surplus_labor_hours": 6.0,
    "rate_of_exploitation_pct": 150.0,
    "initial_surplus_value_s": 1500.0
  },
  "alienation_profile": {
    "product_alienation": 0.95,
    "act_of_production_alienation": 0.85,
    "species_being_alienation": 0.9,
    "social_relations_alienation": 0.8,
    "composite_alienation_index": 0.875,
    "verdict": "RADICAL_FETISHISTIC_ALIENATION"
  },
  "initial_macro_metrics": {
    "organic_composition_of_capital": 0.6667,
    "initial_rate_of_profit_pct": 50.0
  },
  "accumulation_trajectory": [
    {
      "round": 1,
      "constant_capital_c": 4000.0,
      "variable_capital_v": 800.0,
      "total_capital": 4800.0,
      "organic_composition": 0.8333,
      "surplus_value_s": 1200.0,
      "rate_of_profit_pct": 25.0,
      "state": "NORMAL_ACCUMULATION"
    },
    {
      "round": 2,
      "constant_capital_c": 7000.0,
      "variable_capital_v": 500.0,
      "total_capital": 7500.0,
      "organic_composition": 0.9333,
      "surplus_value_s": 750.0,
      "rate_of_profit_pct": 10.0,
      "state": "FALLING_PROFITABILITY_WARNING"
    },
    {
      "round": 3,
      "constant_capital_c": 11000.0,
      "variable_capital_v": 300.0,
      "total_capital": 11300.0,
      "organic_composition": 0.9735,
      "surplus_value_s": 450.0,
      "rate_of_profit_pct": 3.98,
      "state": "CRISIS_OF_OVERACCUMULATION_TRPF"
    }
  ],
  "systemic_historical_verdict": "SYSTEMIC_CRISIS_TRPF_REALIZED"
}
```

### 제약 조건
- $1.0 \le \text{working\_day\_hours} \le 24.0$
- $0.1 \le \text{necessary\_labor\_hours} \le \text{working\_day\_hours}$
- $10.0 \le c, v \le 10^8$
- $0.0 \le a_{product}, a_{act}, a_{species}, a_{social} \le 1.0$
- $0 \le \text{len(innovation\_rounds)} \le 100$
- 모든 부동소수점 연산은 지정된 유효 자릿수로 정밀하게 반올림(`round`)되어야 합니다.
