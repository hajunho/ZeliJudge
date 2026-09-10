# 문제 059: 자크 데리다의 해체주의: 차연(Différance), 흔적(Trace) 및 위계적 2항 대립 아포리아(Aporia) 분석 엔진 (Jacques Derrida's Deconstruction Engine)

## 문제 배경
20세기 후반 프랑스의 철학자 **자크 데리다(Jacques Derrida, 1930~2004)**는 1967년 출간된 세 권의 저작(『그라마톨로지에 대하여』, 『글쓰기와 차이』, 『목소리와 현상』)을 통해 서양 철학 2,500년의 근간인 **현전의 형이상학(Metaphysics of Presence)**과 **로고스중심주의(Logocentrism)**를 근본적으로 뒤흔드는 **해체주의(Deconstruction)**를 주창했습니다.

전통 서양 형이상학은 언제나 개념의 순수한 자아 현전(Self-Presence)을 가정하며, 세계를 불평등한 **위계적 2항 대립(Hierarchical Binary Opposition)**으로 구성해 왔습니다:
- **음성(Speech)** vs **문자(Writing)**: 말(음성)은 영혼의 호흡이자 순수한 진리의 현전으로 특권화된 반면, 글(문자)은 음성을 왜곡하고 오염시키는 2차적이고 죽은 대리물로 억압받음 (음성중심주의, Phonocentrism).
- **이성(Reason)** vs **광기(Madness)**, **본질(Literal)** vs **비유(Metaphor)**, **정신(Mind)** vs **육체(Body)**.

데리다는 이 견고한 도식을 해체하기 위해 다음과 같은 3단계 전복 및 개념 장치를 고안했습니다:
1. **차연 (Différance)**:
   - 프랑스어 동사 *différer*의 두 가지 의미, 즉 공간적인 **'다름(Differing)'**과 시간적인 **'지연/유예(Deferral)'**를 결합한 신조어.
   - 의미는 기호 안에 영원히 고정되어 있지 않으며, 다른 기호들과의 차이 속에서 끊임없이 미래로 연기됩니다.
2. **흔적 (Trace)**:
   - 기호는 독자적으로 존재하지 못하며, 이미 지나간 부재의 흔적(과거)과 다가올 차이의 흔적(미래)을 간직할 때만 비로소 기능합니다.
3. **아포리아 (Aporia, 막다른 골목 / 자가당착)**:
   - 텍스트가 특권화된 제1항의 순수성을 주장하면서도, 이를 서술하고 증명하기 위해 필연적으로 열등하다고 배척했던 제2항에 전적으로 의존할 수밖에 없는 내적 균열과 모순.
4. **미결정항으로의 재기입 (Re-inscription via Undecidables)**:
   - 이항 대립의 틀 자체를 무력화하는 제3의 개념들:
     - **파르마콘 (Pharmakon)**: 독(Poison)이면서 동시에 치료약(Remedy).
     - **보충 (Supplement)**: 잉여의 덧붙임이면서 동시에 근원적 결핍을 메우는 필수 조건.
     - **원-문자 (Arche-Writing)**: 음성과 문자의 구분을 선행하여 가능하게 하는 차이와 반복의 조건.

본 문제에서는 텍스트에 내재된 위계적 2항 대립의 비대칭성을 계량화하고, 맹점(Blind Spot) 분석을 통해 위계를 전복하며, 자가당착적 아포리아를 도출하고 미결정항으로 재기입하는 **데리다 해체주의 분석 엔진**을 구현해야 합니다.

---

## 시스템 동작 규칙 및 엔진 명세

### 1. 비대칭성 및 로고스중심주의 편향 분석
- 타깃 텍스트(`target_texts`)에서 특권화된 항(`privileged_count`)과 주변화된 항(`marginalized_count`)의 출현 빈도를 분석합니다.
- 지배 비율: $\text{dominance\_ratio} = \frac{\text{privileged\_count}}{\text{privileged\_count} + \text{marginalized\_count}}$ (소수점 4자리 반올림).
- `dominance_ratio >= asymmetry_threshold`이면 `bias_status = "LOGOCENTRIC_HIERARCHY"`, 미만이면 `"BALANCED_OR_AMBIGUOUS"`.

### 2. 위계의 해체적 전복 (Deconstructive Inversion)
- 텍스트 내부의 맹점 인용문(`blind_spot_quotes`)이 1개 이상 존재하면:
  - 억압받던 제2항이 제1항의 존립을 위한 필수 조건임이 드러나므로, `status = "HIERARCHY_OVERTURNED"`.
- 맹점 인용문이 없으면 `status = "HIERARCHY_MAINTAINED"`.

### 3. 아포리아 도출 (Aporia Detection)
- 텍스트의 명시적 주장(`explicit_assertions`)과 맹점 인용문(`blind_spot_quotes`)이 모두 존재하면:
  - `aporia_detected = true`
  - 아포리아 설명: `"텍스트는 {privileged_term}의 순수성을 주장하나, 이를 확립하기 위해 필연적으로 {marginalized_term}에 기생·의존하는 자기모순적 아포리아 노출"` 기록.

### 4. 미결정항으로의 재기입 (Re-inscription)
- 해당 2항 대립의 미결정항(`undecidable_concept`)을 호출하여:
  - `"이항 대립을 해체하고 양자를 동시에 조건짓는 미결정항 '{undecidable_concept}'로 재기입"`을 생성합니다.

### 5. 차연(Différance) 의미 지연 추적 (Trace Traversal)
- `start_trace_term_id`부터 시작하여 `sign_traces`의 `future_deferrals`를 순차적으로 최대 `max_deferral_depth`까지 탐색합니다.
- 이미 방문한 기호가 재방문되면 순환 지연(`"{term_id} (CIRCULAR_DEFERRAL)"`)을 기록하고 즉시 종료합니다.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "config": {
    "max_deferral_depth": 10,
    "asymmetry_threshold": 0.60
  },
  "binary_hierarchies": [
    {
      "pair_id": "speech_vs_writing",
      "privileged_term": "Speech (음성 / 현전)",
      "marginalized_term": "Writing (문자 / 대리물)",
      "undecidable_concept": "Supplement / Arche-Writing (원-문자 / 보충)"
    }
  ],
  "sign_traces": [
    {
      "term_id": "speech",
      "term_name": "음성",
      "future_deferrals": ["voice_breath"]
    },
    {
      "term_id": "voice_breath",
      "term_name": "숨결",
      "future_deferrals": ["spiritual_soul"]
    }
  ],
  "target_texts": [
    {
      "text_id": "rousseau_essay",
      "title": "루소의 언어 기원론",
      "primary_pair_id": "speech_vs_writing",
      "term_frequencies": {
        "privileged_count": 85,
        "marginalized_count": 15
      },
      "explicit_assertions": [
        "음성 언어는 영혼의 살아있는 직접적 호흡이다."
      ],
      "blind_spot_quotes": [
        "루소는 자신의 내면 음성이 결핍되어 있음을 고백하며 글쓰기에 의존했다."
      ],
      "start_trace_term_id": "speech"
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
    "total_texts_deconstructed": 1,
    "logocentric_hierarchies_found": 1,
    "hierarchies_overturned": 1,
    "aporias_exposed": 1
  },
  "deconstruction_reports": [
    {
      "text_id": "rousseau_essay",
      "title": "루소의 언어 기원론",
      "binary_pair": {
        "pair_id": "speech_vs_writing",
        "privileged_term": "Speech (음성 / 현전)",
        "marginalized_term": "Writing (문자 / 대리물)",
        "undecidable_concept": "Supplement / Arche-Writing (원-문자 / 보충)"
      },
      "asymmetry_analysis": {
        "privileged_count": 85,
        "marginalized_count": 15,
        "dominance_ratio": 0.85,
        "bias_status": "LOGOCENTRIC_HIERARCHY"
      },
      "deconstructive_inversion": {
        "status": "HIERARCHY_OVERTURNED",
        "blind_spot_evidence_count": 1
      },
      "aporia": {
        "aporia_detected": true,
        "description": "텍스트는 Speech (음성 / 현전)의 순수성을 주장하나, 이를 확립하기 위해 필연적으로 Writing (문자 / 대리물)에 기생·의존하는 자기모순적 아포리아 노출"
      },
      "re_inscription": {
        "undecidable_concept": "Supplement / Arche-Writing (원-문자 / 보충)",
        "resolution": "이항 대립을 해체하고 양자를 동시에 조건짓는 미결정항 'Supplement / Arche-Writing (원-문자 / 보충)'로 재기입"
      },
      "differance_trace": {
        "start_term": "speech",
        "deferral_chain": ["speech", "voice_breath", "spiritual_soul"],
        "chain_length": 3
      }
    }
  ]
}
```

---

## 제약 사항
- `1 <= len(binary_hierarchies) <= 50`
- `1 <= len(target_texts) <= 50`
- `1 <= max_deferral_depth <= 20`
- `0.0 <= asymmetry_threshold <= 1.0`
