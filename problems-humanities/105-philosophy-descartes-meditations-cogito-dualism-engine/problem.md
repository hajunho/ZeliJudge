# 르네 데카르트의 제일철학에 관한 성찰: 방법적 회의(Methodological Doubt), 코기토(Cogito Ergo Sum), 명석판명한 진리 및 심신이원론(Substance Dualism) 엔진

## 문제 설명

1641년 라틴어로 출간된 르네 데카르트(René Descartes, 1596~1650)의 『제일철학에 관한 성찰(Meditationes de Prima Philosophia)』은 중세 스콜라 철학의 권위와 맹신을 무너뜨리고, 인간 주체 중심의 근대 인식론(Epistemology)과 합리주의(Rationalism)를 탄생시킨 서양 철학사의 가장 거대한 분수령입니다.

데카르트는 조금이라도 의심의 여지가 있는 모든 믿음을 과감히 거짓으로 간주하여 뿌리째 무너뜨리는 **방법적 회의(Methodological Doubt)**를 단행합니다:
1. **제1성찰: 의심할 수 있는 것들에 관하여**:
   - 감각의 오류(원거리 탑의 착시) $\to$ 꿈의 가설(지금 깨어있는지 꿈꾸는지 구분 불가) $\to$ 전능한 악마 가설(**Malin Génie**: 수학적 진리 $2+3=5$조차 속이는 전능한 기만자).
2. **제2성찰: 인간 정신의 본성에 관하여**:
   - 아르키메데스의 고정점: 악마가 나를 아무리 철저히 속인다 해도, 속고 있는 '나'라는 주체가 존재하지 않는다면 속는 일조차 불가능하다.
   - **"나는 생각한다, 고로 존재한다(Cogito, ergo sum / Ego sum, ego existo)"**: 어떠한 악마도 파괴할 수 없는 제1의 절대적 진리.
   - 밀랍의 비유(The Piece of Wax): 감각적 속성(향기, 형태, 차가움)이 불에 녹아 모두 변해도 물체는 여전히 동일한 밀랍으로 지속되며, 이는 감각이 아닌 순수 지성(Intellectus)에 의해서만 파악된다.
3. **제3·5성찰: 신의 존재와 성실성(Non-Deceiver)**:
   - 유한한 나에게 무한한 완전성의 관념(신)이 존재한다는 것은, 그 관념을 찍어 넣은 무한한 원인(신)이 실재함을 증명한다(상표 논변 & 존재론적 논변). 신은 완전하므로 기만자일 수 없다.
4. **제4성찰: 참과 거짓(Error Theory)**:
   - 신이 주신 지성은 오류를 낳지 않는다. 오류의 원인은 무엇인가?
   - **지성(Intellectus)은 유한**하지만 **의지(Voluntas)는 무한**하기 때문에, 의지가 지성의 명석판명한 인식을 넘어서 성급하게 긍정하거나 부정할 때 오류가 발생한다. 지성이 명석판명하게 인식하지 못한 것에 대해서는 의지를 보류하고 **판단을 중지(Suspension / Epoché)**해야 한다.
5. **제6성찰: 물질의 존재 및 심신이원론(Substance Dualism)**:
   - 사유하며 연장을 갖지 않는 비물질적 실체인 **사유실체(Res Cogitans, 마음)**와, 연장을 가지며 사유하지 않고 무한히 분할 가능한 **연장실체(Res Extensa, 신체/물질)**의 실재적 구분(Real Distinction).
   - 성실한 신의 보증에 의해 수학적·기하학적 법칙을 따르는 물질세계의 실재성이 최종적으로 복원된다.

본 과제에서는 데카르트의 6개 성찰 전체를 수리적·인식론적 엔진으로 구현하여, 다양한 명제들에 대해 방법적 회의, 코기토 확립, 명석판명 판정, 의지의 과도성 오류 진단, 그리고 궁극의 근대적 주체 확립 과정을 시뮬레이션합니다.

---

## 6성찰 인식론적 파이프라인

```
+-------------------------------------------------------------------------+
|                       Incoming Proposition                              |
|  - Category: SENSORY, MATHEMATICAL, METAPHYSICAL, COGITO, GOD           |
|  - Intellect Clarity & Distinctness (C, D in [0.0, 1.0])                |
|  - Will Action: AFFIRM, DENY, SUSPEND                                   |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                  1. Foundational Axiom Checks                           |
|  - If COGITO: Immutable Truth -> Establish Cogito (Archimedean Point)   |
|  - If ONTOLOGICAL_GOD: Requires Cogito established -> Divine Proof      |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                  2. Methodological Doubt Filter (Meditation I)          |
|  - If God not proven yet:                                               |
|    * SENSORY: Doubted by Dream / Sensory illusion                       |
|    * MATHEMATICAL: Doubted if evil_demon_active = true                  |
|    * Must SUSPEND judgment! (Affirmation -> Error of Infinite Will)     |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                  3. Rule of Truth & Error Theory (Meditation IV)        |
|  - Clear & Distinct: (C >= clarity_thresh) and (D >= distinct_thresh)   |
|  - Rule: Affirming Clear & Distinct -> TRUTH                            |
|  - Rule: Affirming Confused / Unclear -> ERROR (Will exceeded Intellect)|
|  - Rule: Suspending when unclear -> VIRTUOUS RESTRAINT                  |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|       4. Epistemic Health & World Restoration (Meditation VI)           |
+-------------------------------------------------------------------------+
```

---

## 핵심 계산 및 전이 규칙

### 1. 특수 기초 명제 처리
- **`COGITO`**:
  - `cogito_established = true`, `is_truth = true`, `verdict = "COGITO_IMMUTABLE_TRUTH"`, `will_status = "PROPERLY_ALIGNED"`, `clear_and_distinct_truths` 1 증가.
- **`ONTOLOGICAL_GOD`**:
  - `cogito_established == true`인 경우: `god_existence_proven = true`, `is_truth = true`, `verdict = "DIVINE_TRADEMARK_VERIFIED"`, `will_status = "PROPERLY_ALIGNED"`, `clear_and_distinct_truths` 1 증가.
  - `cogito_established == false`인 경우: 코기토 없는 신학적 독단이므로 `verdict = "PREMATURE_THEOLOGY_WITHOUT_COGITO"`, `will_status = "ERROR_OF_WILL"`.

### 2. 방법적 회의(Methodological Doubt) 검사
`god_existence_proven == false`인 상태에서:
- `category == "SENSORY"`: 감각의 불확실성 또는 꿈 가설에 의해 회의 대상(`is_doubted = true`, `doubt_reason = "SENSORY_ILLUSION_OR_DREAM"`).
- `category == "MATHEMATICAL"`이고 `evil_demon_active == true`: 악마 가설에 의해 수학적 참도 회의 대상(`is_doubted = true`, `doubt_reason = "MALICIOUS_DEMON_DECEPTION"`).
- **회의 대상인 경우 판정**:
  - `will_action == "SUSPEND"`: 올바른 방법적 판단 중지 (`verdict = "METHODOLOGICAL_DOUBT_SUSPENSION"`, `will_status = "VIRTUOUS_RESTRAINT"`, `beliefs_doubted_and_suspended` 1 증가, `judgments_suspended` 1 증가).
  - `will_action != "SUSPEND"`: 회의해야 할 것에 성급히 동의함 (`verdict = f"PREMATURE_ASSENT_DOUBTED_{doubt_reason}"`, `will_status = "ERROR_OF_INFINITE_WILL"`, `epistemic_errors_committed` 1 증가).

### 3. 제4성찰 오차론 및 명석판명 판정
회의 대상이 아니거나 신 존재 증명으로 악마가 퇴치된 경우:
- `is_clear_and_distinct = (clarity >= clarity_threshold) and (distinctness >= distinct_threshold)`.
- **명석판명한 경우 (`is_clear_and_distinct == true`)**:
  - `will_action == "AFFIRM"`: 명석판명한 진리 긍정 (`verdict = "CLEAR_AND_DISTINCT_TRUTH"`, `will_status = "PROPERLY_ALIGNED"`, `clear_and_distinct_truths` 1 증가).
  - `will_action == "SUSPEND"`: 자명한 진리에 대한 불필요한 과도한 회의 (`verdict = "EXCESSIVE_SKEPTICISM_OF_CLEAR_TRUTH"`, `will_status = "UNNECESSARY_SUSPENSION"`, `judgments_suspended` 1 증가).
  - `will_action == "DENY"`: 명백한 진리 부정 (`verdict = "DENIAL_OF_EVIDENT_TRUTH"`, `will_status = "ERROR_OF_INFINITE_WILL"`, `epistemic_errors_committed` 1 증가).
- **혼란스럽고 불명석한 경우 (`is_clear_and_distinct == false`)**:
  - `will_action == "SUSPEND"`: 불명석한 것에 대한 지혜로운 판단 중지 (`verdict = "CONFUSED_IDEA_PRUDENTLY_SUSPENDED"`, `will_status = "VIRTUOUS_RESTRAINT"`, `judgments_suspended` 1 증가).
  - `will_action != "SUSPEND"`: 의지가 지성의 명석함을 초과하여 동의함 (`verdict = "ERROR_WILL_EXCEEDED_INTELLECT"`, `will_status = "ERROR_OF_INFINITE_WILL"`, `epistemic_errors_committed` 1 증가).

### 4. 최종 인식론적 상태 및 건강성 지수
- 실체 유형 집계: `substance_type == "RES_COGITANS"`이면 `res_cogitans_count` 1 증가, `RES_EXTENSA`이면 `res_extensa_count` 1 증가.
- 인식론적 도달 상태 (`epistemic_state`):
  - `cogito_established and god_existence_proven`: `CARTESIAN_FOUNDATIONAL_CERTAINTY` (물질세계까지 복원된 완벽한 기초주의 확신)
  - `cogito_established and not god_existence_proven`: `SOLIPSISTIC_COGITO_ISOLATION` (외부 세계를 믿지 못하는 유아론적 고립)
  - `not cogito_established`: `RADICAL_PYRRHONIAN_CHAOS` (모든 것이 무너진 피론주의적 회의주의 혼돈)
- 인식 건강성 점수 ($0.0 \le \text{epistemic\_health\_score} \le 100.0$):
  $$\text{epistemic\_health\_score} = \text{round}(\max(0.0, \min(100.0, N_{\text{truths}} \times 25.0 + N_{\text{doubted\_suspended}} \times 15.0 - N_{\text{errors}} \times 20.0)), 2)$$

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 전달됩니다:
```json
{
  "agent_id": "Meditator_Descartes",
  "config": {
    "clarity_threshold": 0.7,
    "distinct_threshold": 0.7,
    "evil_demon_active": true
  },
  "propositions": [
    {"id": "P1", "statement": "Tower at distance is round", "category": "SENSORY", "clarity": 0.3, "distinctness": 0.2, "will_action": "SUSPEND", "substance_type": "RES_EXTENSA"},
    {"id": "P2", "statement": "2 + 3 = 5", "category": "MATHEMATICAL", "clarity": 0.9, "distinctness": 0.9, "will_action": "SUSPEND", "substance_type": "RES_COGITANS"},
    {"id": "P3", "statement": "Cogito, ergo sum", "category": "COGITO", "clarity": 1.0, "distinctness": 1.0, "will_action": "AFFIRM", "substance_type": "RES_COGITANS"},
    {"id": "P4", "statement": "God is infinitely perfect, hence exists", "category": "ONTOLOGICAL_GOD", "clarity": 0.95, "distinctness": 0.95, "will_action": "AFFIRM", "substance_type": "RES_COGITANS"},
    {"id": "P5", "statement": "Body occupies 3D space", "category": "SENSORY", "clarity": 0.8, "distinctness": 0.8, "will_action": "AFFIRM", "substance_type": "RES_EXTENSA"}
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 공백 없는 압축 JSON(`separators=(',', ':')`, `ensure_ascii=False`)을 출력합니다:
```json
{
  "agent_id": "Meditator_Descartes",
  "epistemic_state": "CARTESIAN_FOUNDATIONAL_CERTAINTY",
  "cogito_established": true,
  "god_existence_proven": true,
  "material_world_restored": true,
  "epistemic_health_score": 100.0,
  "metrics": {
    "propositions_evaluated": 5,
    "beliefs_doubted_and_suspended": 2,
    "clear_and_distinct_truths": 3,
    "epistemic_errors_committed": 0,
    "judgments_suspended": 2,
    "res_cogitans_count": 3,
    "res_extensa_count": 2
  },
  "evaluations": [
    {"prop_id": "P1", "statement": "Tower at distance is round", "verdict": "METHODOLOGICAL_DOUBT_SUSPENSION", "is_clear_and_distinct": false, "will_status": "VIRTUOUS_RESTRAINT"},
    {"prop_id": "P2", "statement": "2 + 3 = 5", "verdict": "METHODOLOGICAL_DOUBT_SUSPENSION", "is_clear_and_distinct": true, "will_status": "VIRTUOUS_RESTRAINT"},
    {"prop_id": "P3", "statement": "Cogito, ergo sum", "verdict": "COGITO_IMMUTABLE_TRUTH", "is_truth": true, "will_status": "PROPERLY_ALIGNED"},
    {"prop_id": "P4", "statement": "God is infinitely perfect, hence exists", "verdict": "DIVINE_TRADEMARK_VERIFIED", "is_truth": true, "will_status": "PROPERLY_ALIGNED"},
    {"prop_id": "P5", "statement": "Body occupies 3D space", "verdict": "CLEAR_AND_DISTINCT_TRUTH", "is_clear_and_distinct": true, "will_status": "PROPERLY_ALIGNED"}
  ]
}
```

---

## 제약 사항

- $1 \le \text{len}(propositions) \le 100$
- $0.0 \le \text{clarity}, \text{distinctness} \le 1.0$
- $\text{category} \in \{\text{"SENSORY"}, \text{"MATHEMATICAL"}, \text{"METAPHYSICAL"}, \text{"COGITO"}, \text{"ONTOLOGICAL\_GOD"}\}$
- $\text{will\_action} \in \{\text{"AFFIRM"}, \text{"DENY"}, \text{"SUSPEND"}\}$
- $\text{substance\_type} \in \{\text{"RES\_COGITANS"}, \text{"RES\_EXTENSA"}\}$
