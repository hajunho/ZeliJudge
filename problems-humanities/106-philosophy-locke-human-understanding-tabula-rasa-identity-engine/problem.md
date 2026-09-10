# 존 로크의 인간지성론 백지설과 인격 동일성 엔진 (Locke's Tabula Rasa & Personal Identity Engine)

## 문제 설명

근대 영국의 경험주의 철학자 **존 로크(John Locke, 1632–1704)**는 1689년 출간된 기념비적 저작 **『인간지성론』(An Essay Concerning Human Understanding)**을 통해 서양 철학의 인식론과 인격 이론에 혁명적 전환점을 마련했습니다.

로크는 데카르트와 플라톤주의자들이 주장하던 '본유관념(Innate Ideas, 날 때부터 마음에 각인된 선천적 지식)'을 전면적으로 거부하고, 인간의 마음은 태어날 때 아무런 글자도 적히지 않은 **백지(White Paper)** 또는 **타불라 라사(Tabula Rasa)**와 같다고 선언했습니다.

```
       [ 외부 세계 사물 (External Objects) ]      [ 내면의 정신 활동 (Internal Mind) ]
                       │                                         │
               감각 (Sensation)                          반성 (Reflection)
                       │                                         │
                       ▼                                         ▼
           [ 단순 관념 (Simple Ideas) ]             [ 단순 관념 (Simple Ideas) ]
           - 제1성질: 고체성, 연장, 형태, 운동          - 지각, 사유, 의지, 회의
           - 제2성질: 색, 소리, 맛, 냄새, 온도
                       └───────────────────┬───────────────────┘
                                           │
                                           ▼
                            [ 마음의 능동적 지성 조작 ]
                         ┌─────────────────────────────────┐
                         │ 1. 결합 (Combine)  -> 복합 관념 │
                         │    (실체 Substance, 양태 Mode)  │
                         │ 2. 비교 (Compare)  -> 관계 관념 │
                         │ 3. 추상 (Abstract) -> 보편 관념 │
                         └─────────────────┬───────────────┘
                                           │
                                           ▼
                           [ 인격 동일성 (Personal Identity) ]
                             의식(Consciousness)과 기억의 연속
                             "왕자와 구두수선공", 법정적 책임
```

본 시스템은 로크의 경험론적 인식 구조와 인격 동일성 이론을 모델링한 **로크 인지 시뮬레이션 엔진**을 구현합니다.

### 1. 관념의 기원과 성질 분류
- **경험의 두 통로**:
  - `SENSATION` (감각): 외계 사물이 우리 감각 기관에 미치는 인상
  - `REFLECTION` (반성): 마음이 자신의 고유한 작용(지각, 사유, 의지 등)을 되돌아보는 내적 감각
- **제1성질 vs 제2성질**:
  - **제1성질 (Primary Qualities)**: 대상 자체에 본래 내재하며, 마음에 형성된 관념이 실재와 정확히 닮아있는 성질 (`SOLIDITY`, `EXTENSION`, `FIGURE`, `SHAPE`, `MOTION`, `REST`, `NUMBER`, `BULK`).
  - **제2성질 (Secondary Qualities)**: 대상 자체에는 입자들의 미세한 배열과 운동력만 존재하며, 우리 감각에 특정 느낌을 일으키는 힘에 불과한 성질 (`COLOR`, `SOUND`, `TASTE`, `SMELL`, `HEAT`, `COLD`). 실재 대상 자체에는 색이나 맛이 '닮은 꼴'로 존재하지 않습니다.
  - 기타 정신 활동 및 복합 성질은 `OPERATIONAL_OR_COMPOSITE`로 분류됩니다.

### 2. 마음의 능동적 조작과 복합 관념 형성
마음은 단순 관념을 수동적으로 수용한 뒤, 세 가지 능동적 연산을 수행합니다:
1. **결합 (COMBINE)**: 여러 단순 관념을 묶어 하나의 복합 관념(Complex Idea)을 형성합니다. 복합 관념은 실체(`SUBSTANCE`), 혼합 양태(`MODE`), 또는 관계(`RELATION`)로 분류됩니다.
2. **비교 (COMPARE)**: 두 관념을 나란히 놓아 비교하여 관계(`RELATION`)를 형성합니다.
3. **추상 (ABSTRACT)**: 특정 시간과 장소의 구체적 맥락을 분리해 보편/일반 관념(`ABSTRACT_IDEA`)을 창출합니다.

### 3. 인격 동일성 (Personal Identity)과 법정적 책임
로크는 인간(Man/신체)이나 영혼(Substance)의 동일성과 구별되는 **'인격(Person)'**의 고유한 개념을 정립했습니다:
- **인격의 정의**: 생각하고 반성할 수 있으며, 서로 다른 시간과 장소에서 스스로를 '동일한 자신'으로 인식할 수 있는 지적 존재.
- **동일성의 기준**: 신체의 불변이나 불멸의 영혼이 아니라, **과거의 행위를 현재 되살리는 "의식(Consciousness)과 기억(Memory)"의 연속성**입니다.
  - **왕자와 구두수선공(Prince and Cobbler)**: 왕자의 의식과 기억이 구두수선공의 육체로 이전되면, 그는 '인간(Man)'으로서는 구두수선공이지만 '인격(Person)'으로서는 왕자입니다.
  - **만취자와 법정적 책임(Forensic Accountability)**: 의식의 끈이 완전히 끊어져 과거 행위를 기억할 수 없다면, 최후의 심판대에서 그 행위에 대한 인격적 책임은 성립하지 않습니다.

---

## 입력 형식

JSON 형식의 단일 문자열이 표준 입력(`stdin`)으로 주어집니다:

```json
{
  "agent_id": "Locke_Scholar",
  "experiences": [
    {
      "source": "SENSATION",
      "ideas": [
        {"id": "RED_01", "name": "Redness", "quality": "COLOR"},
        {"id": "ROUND_01", "name": "Roundness", "quality": "SHAPE"}
      ]
    },
    {
      "source": "REFLECTION",
      "ideas": [
        {"id": "THINK_01", "name": "Thinking", "quality": "THINKING"}
      ]
    }
  ],
  "operations": [
    {
      "id": "OP_01",
      "type": "COMBINE",
      "complex_id": "APPLE",
      "name": "Ripe Apple",
      "category": "SUBSTANCE",
      "simple_idea_ids": ["RED_01", "ROUND_01"]
    },
    {
      "id": "OP_02",
      "type": "ABSTRACT",
      "base_idea_id": "APPLE",
      "general_concept": "Fruit"
    }
  ],
  "identity_chains": [
    {
      "chain_id": "PRINCE_COBBLER_TRANS",
      "chronological_events": [
        {"t": 1, "body": "Prince_Palace", "action": "Pass_Law", "memory_of_prev": true},
        {"t": 2, "body": "Cobbler_Workshop", "action": "Mend_Shoe", "memory_of_prev": true}
      ]
    }
  ]
}
```

---

## 출력 형식

계산된 지성 메트릭, 복합 관념 풀, 연산 결과, 인격 동일성 판정 결과를 JSON으로 표준 출력(`stdout`)에 공백 없이 출력합니다:

```json
{
  "agent_id": "Locke_Scholar",
  "metrics": {
    "sensation_events": 1,
    "reflection_events": 1,
    "simple_ideas_count": 3,
    "primary_qualities_count": 1,
    "secondary_qualities_count": 1,
    "complex_ideas_count": 1,
    "operations_executed": 2,
    "epistemic_maturity_score": 64.0
  },
  "verdict": "DEVELOPING_COMPLEX_COGNITION",
  "complex_ideas": {
    "APPLE": {
      "id": "APPLE",
      "name": "Ripe Apple",
      "category": "SUBSTANCE",
      "constituents_count": 2,
      "has_primary": true,
      "has_secondary": true
    }
  },
  "operation_results": [
    {
      "op_id": "OP_01",
      "type": "COMBINE",
      "result_id": "APPLE",
      "status": "COMPLEX_IDEA_FORMED",
      "category": "SUBSTANCE"
    },
    {
      "op_id": "OP_02",
      "type": "ABSTRACT",
      "general_concept": "Fruit",
      "status": "ABSTRACT_IDEA_CREATED"
    }
  ],
  "identity_chains": [
    {
      "chain_id": "PRINCE_COBBLER_TRANS",
      "is_same_person": true,
      "conscious_events_count": 2,
      "forensic_status": "FULLY_ACCOUNTABLE_PERSON"
    }
  ]
}
```

---

## 평가 및 판정 규칙

1. **단순 관념 품질 판정**:
   - `PRIMARY_QUALITIES`: `{"SOLIDITY", "EXTENSION", "FIGURE", "SHAPE", "MOTION", "REST", "NUMBER", "BULK"}` $ightarrow$ `quality_type = "PRIMARY"`, `resembles_reality = true`.
   - `SECONDARY_QUALITIES`: `{"COLOR", "SOUND", "TASTE", "SMELL", "HEAT", "COLD"}` $ightarrow$ `quality_type = "SECONDARY"`, `resembles_reality = false`.
   - 기타 $ightarrow$ `quality_type = "OPERATIONAL_OR_COMPOSITE"`, `resembles_reality = false`.
2. **지성 성숙도 점수 (`epistemic_maturity_score`)**:
   - $	ext{base\_score} = \min(40.0, 	ext{simple\_ideas} 	imes 4.0) + \min(30.0, 	ext{complex\_ideas} 	imes 10.0)$
   - `identity_bonus`:
     - `identity_chains`가 비어있으면 `0.0`
     - 하나라도 `is_same_person == true`인 체인이 존재하면 `30.0`
     - 체인은 있으나 모두 연속성이 단절되었으면 `10.0`
   - $	ext{epistemic\_score} = 	ext{round}(\min(100.0, 	ext{base\_score} + 	ext{identity\_bonus}), 2)$
3. **인식 단계 판정 (`verdict`)**:
   - $\ge 80.0$: `"MATURE_EMPIRICAL_UNDERSTANDING"`
   - $\ge 50.0$: `"DEVELOPING_COMPLEX_COGNITION"`
   - $< 50.0$: `"EARLY_TABULA_RASA_IMPRESSION"`
