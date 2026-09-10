# 에드문트 후설의 현상학: 자연적 태도와 에포케(판단중지), 노에시스-노에마 및 선험적 환원 엔진

## 문제 설명

20세기 현대 대륙철학의 거대한 분수령인 **현상학(Phenomenology)**의 창시자 **에드문트 후설(Edmund Husserl, 1859–1938)**은 『논리 연구』(Logische Untersuchungen, 1900/1901)와 『순수 현상학과 현상학적 철학의 이념들』(Ideen zu einer reinen Phänomenologie, 1913)을 통해, 서구 근대 철학을 지배해 온 소박한 실재론과 심리학주의(Psychologism)를 비판하며 철학을 엄밀한 학문(Strenge Wissenschaft)으로 정초하고자 했습니다.

후설의 위대한 모토는 다음과 같습니다:
> *"사태 자체로 돌아가라! (Zu den Sachen selbst!)"*

우리는 일상생활에서 대상들이 우리 의식과 무관하게 저 바깥에 객관적으로 실재한다는 독단적인 믿음, 즉 **자연적 태도(Natural Attitude, Natürliche Einstellung)**에 빠져 있습니다. 후설은 이 자연적 태도의 실재성 가정을 괄호 안에 집어넣고 판단을 보류하는 **에포케(Epoche, 판단중지)**를 단행함으로써, 모든 존재가 의식에 어떻게 나타나고 의미화되는지를 탐구하는 **현상학적 환원(Phenomenological Reduction)**의 지평을 열었습니다:

```
        [ 1. 자연적 태도 (Natural Attitude) ]
          - 외부 세계가 객관적으로 독립 실재한다는 소박한 실재론적 독단.
                         │
                         ▼ [ 에포케(Epoche): 존재 정립적 판단의 괄호치기 ]
        [ 2. 현상학적 환원 (Phenomenological Reduction) ]
          - 오직 의식에 나타나는 순수 현상(Phänomen)의 영역으로 시선 전환.
                         │
                         ▼ [ 자유 상상 변경 (Freie Variation) ]
        [ 3. 형상적 환원 (Eidetic Reduction) ]
          - 우연한 사실성을 벗겨내고 사물의 불변적 본질(Eidos) 추출.
                         │
                         ▼ [ 구성의 궁극적 원천 추적 ]
        [ 4. 선험적 환원 (Transcendental Reduction) ]
          - 의미 구성의 절대적 원천인 선험적 자아(Transcendental Ego)와
            생활세계(Lebenswelt)의 지평 규명.
```

동시에 후설은 프란츠 브렌타노의 **지향성(Intentionality, Intentionalität)** 개념을 발전시켜, **"모든 의식은 언제나 어떤 대상에 대한 의식이다"**라고 천명했습니다. 의식은 수동적인 거울이 아니라 대상을 향해 의미를 부여하는 능동적 작용입니다:
- **노에시스 (Noesis, 사유작용)**: 지각(Perception), 회상(Recollection), 상상(Imagination), 기대(Anticipation) 등 대상을 지향하는 의식의 작용.
- **노에마 (Noema, 사유대상 / 뜻)**: 노에시스 작용에 의해 구성된 대상의 의미적 통일체.
- **지평 구조 (Horizontstruktur)**: 우리가 정육면체를 볼 때 3개의 면만 눈에 보이지만(직접 소여), 보이지 않는 뒷면 3개 또한 암묵적으로 함께 지향하는 **내적 지평(Internal Horizon)**과 대상이 놓여 있는 방과 세계의 맥락인 **외적 지평(External Horizon)**이 결합되어 완전한 하나의 사물로 구성(Constitution)됩니다.

본 시스템은 후설의 자연적 태도 $\leftrightarrow$ 에포케 전이, 자유 상상 변경을 통한 형상적 본질 추출, 노에시스-노에마 지향적 구성 및 선험적 자아 판정을 수행하는 **후설 현상학 인지 지성 엔진**을 구현합니다.

---

## 핵심 엔진 아키텍처 및 규칙

### 1. 태도 전이 상태 머신 (`current_attitude`)
1. **자연적 태도 (`NATURAL_ATTITUDE`)**:
   - 기본 상태. 외부 세계의 실재성을 의심 없이 신뢰합니다 (`world_bracketed = false`).
2. **에포케 (`PERFORM_EPOCHE`)**:
   - `bracket_world == true` 이면 외부 세계 실재성 가정을 괄호치며(`world_bracketed = true`), 에포케 깊이(`epoche_depth += 40.0`, 최대 100.0)를 증가시키고 **현상학적 환원(`PHENOMENOLOGICAL_REDUCTION`)**으로 진입합니다.
   - `bracket_world == false` 이면 에포케를 풀고 즉시 자연적 태도로 복귀합니다.
3. **자유 상상 변경 (`FREE_EIDETIC_VARIATION`)**:
   - 에포케 상태(`world_bracketed == true`)에서만 수행 가능합니다.
   - 대상의 크기, 색상, 재질 등을 상상 속에서 자유롭게 변경(`variation_traits`)하면서 어떤 변형에도 무너지지 않는 불변적 성질(`invariable_traits`)인 **형상(Eidos)**을 추출합니다.
   - 형상 명료도(`eidetic_clarity += len(variations) * 15.0`)가 40.0 이상이면 **형상적 환원(`EIDETIC_REDUCTION`)** 상태로 승격합니다.
4. **선험적 환원 (`TRANSCENDENTAL_REDUCTION`)**:
   - 세계가 괄호쳐져 있고(`world_bracketed == true`), `eidetic_clarity >= 30.0` 일 때만 성공하여 **선험적 자아(`TRANSCENDENTAL_EGO`)** 상태로 도약합니다.

### 2. 노에시스-노에마 지향적 구성 (`CONSTITUTE_NOEMA`)
1. 사유작용 양태(`noesis_mode`)에 따라 구성 타당도(`constitutional_validity`)가 결정됩니다:
   - 자연적 태도일 때 기본값: $0.5$, 에포케 환원 상태일 때: $1.0$.
   - `PERCEPTION`: 직관적 현전 $\times 1.0$
   - `RECOLLECTION`: 과거 회상 $\times 0.85$
   - `IMAGINATION`: 순수 상상 $\times 0.70$
2. 노에마는 보이는 면(`visible_aspects`), 함께 지향된 보이지 않는 뒷면인 내적 지평(`co_intended_horizon`), 그리고 주변 맥락인 외적 지평(`lifeworld_context`)의 종합으로 구성됩니다.

### 3. 최종 판정 (`verdict`)
1. `current_attitude == "TRANSCENDENTAL_EGO"` 이고 구성된 노에마가 1개 이상: **`TRANSCENDENTAL_PHENOMENOLOGIST`**
2. `current_attitude == "EIDETIC_REDUCTION"`: **`EIDETIC_RESEARCHER`**
3. `current_attitude == "PHENOMENOLOGICAL_REDUCTION"`: **`BRACKETED_INVESTIGATOR`**
4. `current_attitude == "NATURAL_ATTITUDE"`: **`NAIVE_REALIST_OBSERVER`**

---

## 입력 형식

표준 입력(`stdin`)으로 JSON 객체가 주어집니다:

```json
{
  "agent_id": "Edmund_Husserl_Master",
  "initial_attitude": "NATURAL_ATTITUDE",
  "operations": [
    {"op": "PERFORM_EPOCHE", "params": {"bracket_world": true}},
    {"op": "FREE_EIDETIC_VARIATION", "params": {
      "target_class": "MATERIAL_THING",
      "variation_traits": ["color_blue", "metallic", "spherical", "heavy"],
      "invariable_traits": ["spatial_extension", "temporal_duration", "sensory_sheen"]
    }},
    {"op": "CONSTITUTE_NOEMA", "params": {
      "noesis_mode": "PERCEPTION",
      "target_object": "HEXAHEDRON_DICE",
      "visible_aspects": ["side_1", "side_2", "side_3"],
      "co_intended_horizon": ["side_4", "side_5", "side_6"],
      "lifeworld_context": "WOODEN_TABLE_PARLOR"
    }},
    {"op": "TRANSCENDENTAL_REDUCTION", "params": {}}
  ]
}
```

---

## 출력 형식

표준 출력(`stdout`)으로 JSON 객체를 공백 없이 출력합니다:

```json
{
  "agent_id": "Edmund_Husserl_Master",
  "metrics": {
    "current_attitude": "TRANSCENDENTAL_EGO",
    "attitude_history": ["NATURAL_ATTITUDE", "PHENOMENOLOGICAL_REDUCTION", "EIDETIC_REDUCTION", "TRANSCENDENTAL_EGO"],
    "world_bracketed": true,
    "epoche_depth": 100.0,
    "eidetic_clarity": 60.0,
    "intentional_synthesis_score": 25.0,
    "total_noemata_count": 1,
    "eidetic_invariants": ["sensory_sheen", "spatial_extension", "temporal_duration"]
  },
  "verdict": "TRANSCENDENTAL_PHENOMENOLOGIST",
  "constituted_noemata": [
    {
      "noematic_core": "HEXAHEDRON_DICE",
      "noesis_act": "PERCEPTION",
      "internal_horizon": ["side_4", "side_5", "side_6"],
      "external_horizon": "WOODEN_TABLE_PARLOR",
      "constitutional_validity": 1.0
    }
  ],
  "action_log": [
    ...
  ]
}
```
