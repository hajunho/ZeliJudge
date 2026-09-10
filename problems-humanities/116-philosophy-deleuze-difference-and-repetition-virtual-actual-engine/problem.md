# 질 들뢰즈: 차이와 반복(Différence et Répétition), 잠재성과 실재화(Virtual to Actual) 및 시간의 3중 종합 시뮬레이션 엔진

## 문제 설명

20세기 프랑스 후기 구조주의 철학의 거장 **질 들뢰즈(Gilles Deleuze, 1925~1995)**는 대표 주저인 『차이와 반복(Différence et Répétition, 1968)』을 통해 서양 철학 2,500년 동안 동일성(Identity)에 종속되어 온 '차이'를 독립적인 존재론적 제1원리로 해방시켰습니다.

전통적인 재현(Representation) 사유는 차이를 오직 "A는 B와 다르다(동일성의 결여)"라는 부정적 파생물로만 보았지만, 들뢰즈는 차이야말로 모든 존재와 생성을 추동하는 일차적 역능인 **"차이 자체(Difference-in-itself / Différence en soi)"**임을 천명합니다.

```
       [내재성의 평면 (Plane of Immanence)]
         - 강도적 기울기 (Intensity Gradients : Spatium)
         - 잠재적 다양체 (Virtual Multiplicities) & 미분적 관계 (dx/dy)
         - 특이점들 (Singularities : 안장점, 노드, 끌개)
                       ↓ (극화 / Dramatization & 실재화 / Actualization)
       [시간의 3중 종합 (Three Syntheses of Time)]
         1) 제1종합: 습관 (Habit) -> 순간들의 수축과 '살아있는 현재'
         2) 제2종합: 기억 (Memory / Mnemosyne) -> 공존하는 '순수 과거'
         3) 제3종합: 영원회귀 (Eternal Return) -> 오직 차이만을 선택하는 미래의 바퀴
                       ↓ (재현의 4대 족쇄 극복: 동일성, 유비, 대립, 유사성)
       [차이 자체의 해방 (Difference-in-itself Unleashed)]
```

### 핵심 존재론 구조
1. **잠재성과 실재화 (The Virtual and Actualization)**:
   - 들뢰즈에게 **잠재적인 것(Virtual)**은 허구(Fictional)나 가능성(Possible)이 아닙니다. *"잠재적인 것은 실재하지만 현실적이지 않다(Real without being actual)"*.
   - 잠재적 다양체(Multiplicities)는 강도적 공간(Spatium)의 잠재력 차이(Intensity Gradient)가 임계치(`intensity_threshold`)를 넘어설 때 비로소 외연적 공간과 물질로 실재화(Actualization / Dramatization)됩니다.
2. **시간의 3중 종합과 반복 (Three Syntheses of Time)**:
   - **기계적 반복(Bare Repetition)**: 동일자가 아무런 변주 없이 반복되는 것으로, 사유를 재현의 도그마에 가둡니다.
   - **영원회귀(Eternal Return)**: 오직 차이와 변주(Delta Variation)만을 긍정하고, 고정된 동일자를 소멸시키는 선택의 바퀴입니다.
3. **재현의 4대 족쇄 (Four Shackles of Representation)**:
   - 개념에서의 동일성 (Identity in the concept)
   - 판단에서의 유비 (Analogy in judgment)
   - 술어에서의 대립 (Opposition in the predicate)
   - 지각에서의 유사성 (Resemblance in perception)

본 문제에서는 내재성의 평면(Plane of Immanence) 상의 강도적 기울기, 잠재적 다양체와 특이점, 시간의 3중 종합(습관/기억/영원회귀) 사이클, 그리고 재현의 4대 족쇄 비판을 수리적으로 모델링하여 들뢰즈의 차이 존재론적 상태 머신을 구현해야 합니다.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다.

```json
{
  "plane_of_immanence": {
    "dimensions": 3,
    "intensity_gradients": [
      {"dimension": "temperature", "potential_delta": 4.0},
      {"dimension": "pressure", "potential_delta": 3.0}
    ]
  },
  "multiplicities": [
    {
      "id": "morphogenesis_embryo",
      "singularities": [
        {"coords": [1.0, 2.0, 0.5], "nature": "SADDLE_NODE"},
        {"coords": [3.0, 1.5, 2.0], "nature": "ATTRACTOR"}
      ],
      "differential_relation": "dy_over_dx",
      "intensity_threshold": 4.5
    }
  ],
  "repetition_cycles": [
    {
      "cycle_id": 1,
      "repetition_type": "HABIT_LIVING_PRESENT",
      "delta_variation": 0.2
    },
    {
      "cycle_id": 2,
      "repetition_type": "ETERNAL_RETURN_SELECTIVE",
      "delta_variation": 2.5
    }
  ],
  "representation_critique_enabled": true
}
```

### 파라미터 규격
- `plane_of_immanence` (객체): 내재성 평면의 차원 수(`dimensions`)와 각 차원별 강도 기울기(`intensity_gradients`: `dimension`, `potential_delta`).
- `multiplicities` (배열): 잠재적 다양체 목록.
  - `id` (문자열): 다양체 식별자.
  - `singularities` (배열): 특이점 좌표 및 성격.
  - `differential_relation` (문자열): 미분 관계식 명칭.
  - `intensity_threshold` (실수): 실재화를 촉발하기 위한 최소 강도 임계치.
- `repetition_cycles` (배열): 반복 사이클 목록.
  - `cycle_id` (정수): 사이클 식별 번호.
  - `repetition_type` (문자열): `"HABIT..."`, `"MEMORY..."`, `"ETERNAL_RETURN..."` 중 하나.
  - `delta_variation` (실수, $\ge 0.0$): 반복 시 산출되는 차이 변주량.
- `representation_critique_enabled` (불리언): 재현의 4대 족쇄 비판 모듈 활성화 여부.

---

## 계산 명세

1. **강도적 공간 총합 (Total Intensity Spatium)**:
   - $\text{total\_intensity\_spatium} = \text{round}\left(\sqrt{\sum (\text{potential\_delta}_i)^2}, 4\right)$.

2. **다양체의 실재화 판정 (Actualization Events)**:
   - 각 다양체에 대해:
     - `total_intensity_spatium` $\ge$ `intensity_threshold` 이면 상태는 `"ACTUALIZED_INTO_EXTENSITY"`, 아니면 `"VIRTUAL_LATENCY"`.
     - $\text{intensity\_surplus} = \text{round}(\max(0.0, \text{total\_intensity\_spatium} - \text{intensity\_threshold}), 4)$.

3. **시간의 3중 종합과 반복 누적 (Time Syntheses & Repetition)**:
   - 각 사이클 분류 카운트: `habit_syntheses`, `memory_syntheses`, `eternal_return_syntheses`.
   - 차이 및 페널티 누적:
     - `"ETERNAL_RETURN"`: `delta_variation > 0`이면 $\text{diff} += \text{delta} \times 1.5$, `delta == 0`이면 $\text{penalty} += 1.0$.
     - `"MEMORY"`: $\text{diff} += \text{delta} \times 1.0$.
     - `"HABIT"`: `delta == 0`이면 $\text{penalty} += 0.5$, `delta > 0`이면 $\text{diff} += \text{delta} \times 0.5$.
   - $\text{accumulated\_difference} = \text{round}(\text{diff}, 4)$, $\text{bare\_repetition\_penalty} = \text{round}(\text{penalty}, 4)$.

4. **재현의 4대 족쇄 판별 (Critique of Representation)**:
   - `representation_critique_enabled`가 참인 경우:
     - `bare_repetition_penalty > 0.5` $\rightarrow$ `identity_subordinated = true`, `resemblance_in_perception = true`.
     - 전체 특이점 수 $< 2$ $\rightarrow$ `analogy_in_judgment = true`.
     - `habit_syntheses > memory_syntheses` 이고 `habit_syntheses > eternal_return_syntheses` $\rightarrow$ `opposition_in_predicate = true`.
   - `shackles_count` = 참으로 판정된 족쇄의 총 개수 (0~4).

5. **차이 자체 긍정 지표 및 최종 존재론 판정 (Ontological Verdict)**:
   - $\text{base\_metric} = (\text{total\_intensity} \times 0.3) + (\text{accumulated\_diff} \times 0.4) - (\text{penalty} \times 0.2) - (\text{shackles\_count} \times 0.1)$.
   - $\text{difference\_affirmation\_metric} = \text{round}\left(\max\left(0.05, \min\left(1.0, \frac{\text{base\_metric}}{5.0}\right)\right), 4\right)$.
   - 존재론적 상태 (`ontological_status`):
     - `metric >= 0.70` 이고 `eternal_return_syntheses > 0` $\rightarrow$ `"DIFFERENCE_IN_ITSELF_UNLEASHED"`
     - `shackles_count >= 3` $\rightarrow$ `"REPRESENTATIONAL_DOGMATISM"`
     - 모든 다양체가 `"VIRTUAL_LATENCY"` $\rightarrow$ `"UNACTUALIZED_VIRTUAL_CHAOS"`
     - 그 외 $\rightarrow$ `"DRAMATIZATION_IN_PROGRESS"`

---

## 출력 형식

표준 출력(stdout)으로 다음 스키마의 단일 JSON 문자열(공백 없는 compact 형태)을 출력합니다:

```json
{
  "plane_of_immanence": {
    "dimensions": 3,
    "total_intensity_spatium": 5.0
  },
  "actualization_events": [
    {
      "multiplicity_id": "morphogenesis_embryo",
      "singularities_count": 2,
      "intensity_threshold": 4.5,
      "status": "ACTUALIZED_INTO_EXTENSITY",
      "intensity_surplus": 0.5
    }
  ],
  "time_syntheses_breakdown": {
    "habit_syntheses": 1,
    "memory_syntheses": 0,
    "eternal_return_syntheses": 1,
    "accumulated_difference": 3.85,
    "bare_repetition_penalty": 0.0
  },
  "representation_critique": {
    "shackles_count": 0,
    "shackles": {
      "identity_subordinated": false,
      "analogy_in_judgment": false,
      "opposition_in_predicate": false,
      "resemblance_in_perception": false
    }
  },
  "ontological_verdict": {
    "difference_affirmation_metric": 0.608,
    "ontological_status": "DRAMATIZATION_IN_PROGRESS"
  }
}
```

---

## 제약 조건

- $1 \le \text{dimensions} \le 10$
- $1 \le \text{len(intensity\_gradients)} \le 20$
- $1 \le \text{len(multiplicities)} \le 50$
- $1 \le \text{len(repetition\_cycles)} \le 100$
- 모든 부동소수점 값은 명시된 반올림 규칙(`round(x, 4)`)을 준수합니다.
- 실행 시간 제한: 2.0초 이내
- 메모리 사용 제한: 256MB 이내
