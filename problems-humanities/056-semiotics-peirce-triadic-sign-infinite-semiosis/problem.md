# 문제 056: 샤를 샌더스 퍼스의 3분법 기호학: 도상·지표·상징 분류 및 무한 기호작용(Infinite Semiosis) 추론 엔진 (Peirce's Triadic Semiotics & Infinite Semiosis Engine)

## 문제 배경
언어와 기호가 인간의 사고 속에서 어떻게 의미를 획득하는가를 탐구하는 기호학(Semiotics)에는 역사적으로 두 개의 거대한 산맥이 존재합니다:
1. **페르디낭 드 소쉬르(Ferdinand de Saussure)**의 유럽 구조주의:
   - 기호를 음성적 형태인 '기표(Signifiant)'와 심상적 개념인 '기의(Signifié)'의 2항 관계로 설명하며, 언어 체계 내부의 상호 차이와 자의성에 주목했습니다.
2. **샤를 샌더스 퍼스(Charles Sanders Peirce)**의 미국 실용주의(Pragmatism):
   - 기호를 결코 2항 대립으로 닫아두지 않고, **표상체(Representamen, 기호 그 자체)**, **대상체(Object, 기호가 지시하는 실체나 관념)**, 그리고 이 둘 사이의 관계로부터 지각자(인지 주체)의 마음에 생성되는 제3의 기호인 **해석체(Interpretant)**의 **3자 관계(Triadic Relation)**로 정의했습니다.

퍼스의 천재성은 기호를 고정된 명사로 보지 않고, 하나의 기호가 낳은 해석체가 다시 다음 단계의 기호가 되어 또 다른 해석체를 낳는 연쇄적 인식 과정, 즉 **무한 기호작용(Infinite Semiosis)**으로 파악한 데 있습니다:
$$S_1 \xrightarrow{\text{Object}} I_1 (= S_2) \xrightarrow{\text{Object}} I_2 (= S_3) \xrightarrow{\text{Object}} \dots$$

이 과정은 자칫 끝없는 순환 논증이나 발산에 빠질 수 있으나, 탐구가 지속되면 결국 인지 주체가 세계와 상호작용하는 안정된 행동 규칙이자 믿음인 **궁극적 해석체(Final Interpretant / Habit)**에 도달하여 수렴합니다.

본 문제에서는 퍼스의 기호 삼분법(도상 Icon, 지표 Index, 상징 Symbol)과 맥락적 접지(Grounding) 검증, 그리고 단계별 해석체 도출 및 무한 기호작용 탐구 루프를 정밀하게 시뮬레이션하는 **퍼스 3분법 기호학 추론 엔진**을 구현해야 합니다.

---

## 시스템 동작 규칙 및 엔진 명세

### 1. 퍼스의 3대 기호 분류 체계 (Sign Classification)
기호와 대상체(Object)의 결합 방식에 따라 세 가지 유형으로 분류됩니다:
1. **도상 (Icon)**:
   - 기호와 대상체가 지닌 **물리적·형태적 유사성(Resemblance / Similarity)**에 기반합니다 (예: 초상화, 지도, 픽토그램).
   - 유효 접지(Grounding) 조건: 기호의 유사도 점수(`similarity_score`)가 시스템의 임계치(`grounding_threshold`) 이상이어야 유효합니다.
2. **지표 (Index)**:
   - 기호와 대상체 간의 **실제적·물리적·인과적 연결(Causal / Spatiotemporal Contiguity)**에 기반합니다 (예: 연기와 불, 온도계 수은주와 기온, 풍향계와 바람).
   - 유효 접지 조건: `physical_proximity`가 참인 경우, 기호의 원인 요소(`causal_factor`) 또는 대상체(`target_object`)가 관측 맥락의 물리적 환경(`physical_presence`)에 실제로 존재해야 유효합니다.
3. **상징 (Symbol)**:
   - 기호와 대상체가 오직 **사회적 관습, 법률, 문화적 규약(Arbitrary Habit / Law / Convention)**에 의해서만 연결됩니다 (예: 단어, 교통 신호등, 국가 국기).
   - 유효 접지 조건: 기호가 요구하는 사회적 규범 맥락(`social_context`)이 관측 맥락의 활성 규약 목록(`active_conventions`)에 명시적으로 포함되어 있어야 유효합니다.

### 2. 무한 기호작용(Infinite Semiosis) 추론 단계
각 탐구 과제(`inquiry_tasks`)는 초기 기호(`initial_sign_id`)로부터 시작하여 순차적으로 다음 기호를 탐색합니다:
- 각 단계 $k$ ($1 \le k \le \text{max\_semiosis\_depth}$):
  1. 기호 딕셔너리에서 현재 기호 정보를 조회합니다. (존재하지 않으면 사유 `"UNKNOWN_SIGN"`으로 즉시 중단).
  2. 관측 맥락(`observed_context`)을 바탕으로 위 **기호 접지(Grounding) 유효성**을 검사합니다.
     - 접지 조건을 만족하지 못하면 `grounded = false`로 기록하고, 사유 `"UNGROUNDED_SIGN"`으로 즉시 탐구를 중단합니다.
  3. 해석체의 유형을 결정합니다:
     - `habit_forming`이 참이면 `"FINAL"` (궁극적 해석체: 행동 습관으로 안착).
     - 그렇지 않고 탐구의 첫 번째 단계($k=1$)이면 `"IMMEDIATE"` (직접적 해석체: 초기 직관 표상).
     - 그 외의 중간 추론 단계이면 `"DYNAMICAL"` (역동적 해석체: 실제 맥락에서 파생된 후속 기호).
  4. 단계 정보를 기록한 후 종결 조건을 평가합니다:
     - **궁극적 습관 형성 (`FINAL_HABIT_CONVERGENCE`)**: `habit_forming`이 참이면 탐구가 성공적으로 수렴하여 종료됩니다. `final_belief`는 해당 기호의 `target_object`가 됩니다.
     - **종단 해석체 (`TERMINAL_INTERPRETANT`)**: 후속 기호(`next_sign_id`)가 null이면 추가 기호작용 없이 종료됩니다. `final_belief`는 해당 기호의 `target_object`가 됩니다.
     - **기호 순환 감지 (`SEMIOTIC_CYCLE_DETECTED`)**: 후속 기호(`next_sign_id`)가 이미 현재 탐구 경로(`visited`)에 존재하는 경우, 동어반복적 무한 루프에 빠진 것으로 판정하고 즉시 중단합니다.
     - **최대 깊이 도달 (`MAX_DEPTH_EXCEEDED`)**: $k == \text{max\_semiosis\_depth}$에 도달했으나 종결되지 못한 경우 중단합니다.
     - 위 종결 조건에 해당하지 않으면 `current_sign_id = next_sign_id`로 전이하여 다음 단계를 진행합니다.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "config": {
    "max_semiosis_depth": 10,
    "grounding_threshold": 0.75
  },
  "sign_dictionary": [
    {
      "sign_id": "s_smoke",
      "name": "연기 (Smoke Column)",
      "relation_type": "INDEX",
      "target_object": "연소 불꽃 (Combustion Fire)",
      "grounding": {
        "causal_factor": "화재 (Fire Incident)",
        "physical_proximity": true,
        "correlation": 0.99
      },
      "interpretant_rule": {
        "next_sign_id": "s_fire_hazard",
        "habit_forming": false
      }
    },
    {
      "sign_id": "s_fire_hazard",
      "name": "화재 위험 (Fire Hazard Concept)",
      "relation_type": "SYMBOL",
      "target_object": "신체적 위험 (Physical Threat)",
      "grounding": {
        "convention_rule": "안전 상식 규약",
        "social_context": "공공 안전 규범"
      },
      "interpretant_rule": {
        "next_sign_id": "s_evacuation_action",
        "habit_forming": false
      }
    },
    {
      "sign_id": "s_evacuation_action",
      "name": "대피 행동 습관 (Evacuate Building)",
      "relation_type": "SYMBOL",
      "target_object": "비상탈출 성공 (Safety Preservation)",
      "grounding": {
        "convention_rule": "소방 행동 수칙",
        "social_context": "공공 안전 규범"
      },
      "interpretant_rule": {
        "next_sign_id": null,
        "habit_forming": true
      }
    }
  ],
  "inquiry_tasks": [
    {
      "task_id": "task_smoke_alarm",
      "initial_sign_id": "s_smoke",
      "observed_context": {
        "physical_presence": ["화재 (Fire Incident)", "고온 열기"],
        "active_conventions": ["공공 안전 규범"]
      }
    }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 JSON 객체를 단일 행으로 출력합니다:

```json
{
  "summary": {
    "total_tasks": 1,
    "converged_habits": 1,
    "cycles_detected": 0,
    "ungrounded_failures": 0
  },
  "results": [
    {
      "task_id": "task_smoke_alarm",
      "initial_sign": "s_smoke",
      "chain_length": 3,
      "termination_reason": "FINAL_HABIT_CONVERGENCE",
      "final_belief": "비상탈출 성공 (Safety Preservation)",
      "semiosis_path": ["s_smoke", "s_fire_hazard", "s_evacuation_action"],
      "steps": [
        {
          "step": 1,
          "sign_id": "s_smoke",
          "name": "연기 (Smoke Column)",
          "triad": {
            "representamen": "연기 (Smoke Column)",
            "object": "연소 불꽃 (Combustion Fire)",
            "interpretant_type": "IMMEDIATE"
          },
          "classification": "INDEX",
          "grounded": true
        },
        {
          "step": 2,
          "sign_id": "s_fire_hazard",
          "name": "화재 위험 (Fire Hazard Concept)",
          "triad": {
            "representamen": "화재 위험 (Fire Hazard Concept)",
            "object": "신체적 위험 (Physical Threat)",
            "interpretant_type": "DYNAMICAL"
          },
          "classification": "SYMBOL",
          "grounded": true
        },
        {
          "step": 3,
          "sign_id": "s_evacuation_action",
          "name": "대피 행동 습관 (Evacuate Building)",
          "triad": {
            "representamen": "대피 행동 습관 (Evacuate Building)",
            "object": "비상탈출 성공 (Safety Preservation)",
            "interpretant_type": "FINAL"
          },
          "classification": "SYMBOL",
          "grounded": true
        }
      ]
    }
  ]
}
```

---

## 제약 사항
- `1 <= len(sign_dictionary) <= 500`
- `1 <= len(inquiry_tasks) <= 50`
- `1 <= max_semiosis_depth <= 20`
- `0.0 <= grounding_threshold <= 1.0`
