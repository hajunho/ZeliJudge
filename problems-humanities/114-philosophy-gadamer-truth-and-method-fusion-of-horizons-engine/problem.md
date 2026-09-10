# 한스-게오르크 가다머의 진리와 방법: 선이해와 영향사의식, 지평융합(Horizontverschmelzung) 및 해석학적 순환 엔진

## 문제 설명

20세기 현대 철학적 해석학(Philosophical Hermeneutics)의 태두 **한스-게오르크 가다머(Hans-Georg Gadamer, 1900–2002)**는 필생의 역작 『진리와 방법』(Wahrheit und Methode, 1960)을 통해, 계몽주의 이래 서양 근대 과학주의가 강요해 온 '방법론적 객관주의'의 허상을 통렬히 비판하고, 인문학적 경험(예술, 역사, 언어) 속에 내재된 고유하고 자율적인 **진리(Wahrheit)**의 지평을 회복시켰습니다.

가다머 해석학의 핵심 통찰은 다음과 같습니다:

```
        [ 가다머 철학적 해석학의 4대 핵심 기둥 ]

  1. 선이해와 선입견(Vorurteil)의 복권:
     - 계몽주의는 모든 선입견을 오류로 단정했으나, 가다머는 인간이 역사의 진공 상태에서 사유할 수 없음을 지적.
     - 선입견은 인식을 가로막는 장애물이 아니라, 이해를 가능하게 하는 필수적 출발점(선이해, Vorverständnis).
     - 생산적 선입견(열린 전통) vs 맹목적 독단(Dogma)의 비판적 구분.
                         │
                         ▼
  2. 해석학적 순환 (Hermeneutischer Zirkel):
     - 텍스트 부분(단어/문장)은 전체(문맥/저작)를 통해서만 이해되고, 전체는 부분들의 종합을 통해서만 이해됨.
     - 끝없는 선이해의 수정과 점진적 심화 과정.
                         │
                         ▼
  3. 영향사 의식 (Wirkungsgeschichtliches Bewusstsein):
     - 우리는 과거의 텍스트를 외부의 박제된 화석처럼 관찰하는 초연한 구경꾼이 아님.
     - 우리는 이미 그 텍스트가 낳은 역사적 영향의 그물망(전통, Wirkungsgeschichte) 안에 서 있음.
     - 시간적 거리(Temporal Distance)는 장애물이 아니라 이해를 풍요롭게 하는 생산적 여과 장치.
                         │
                         ▼
  4. 지평 융합 (Horizontverschmelzung):
     - 이해는 과거 저자의 심리로 들어가는 복원이 아님.
     - 텍스트의 역사적 지평(Text Horizon)과 해석자의 현재적 지평(Interpreter Horizon)이
       열린 대화(Gespräch)를 통해 만나 서로를 변형시키며 새로운 더 넓은 통일 지평으로 승화하는 사건.
```

본 시스템은 가다머의 선이해·선입견 분류, 해석학적 순환(부분-전체 반복 심화), 영향사 의식 각성, 그리고 과거 텍스트 지평과 현재 해석자 지평 간의 **지평 융합(Horizontverschmelzung)**을 정밀하게 모델링하는 **가다머 철학적 해석학 지성 엔진**을 구현합니다.

---

## 핵심 엔진 아키텍처 및 규칙

### 1. 선입견(Vorurteil) 구조
1. 해석자는 초기 선입견 목록을 지닙니다:
   - 생산적 선입견(`PRODUCTIVE`): 전통과 권위에 대한 신뢰, 대화에 열린 선이해.
   - 독단적 편견(`DOGMATIC`): 실증주의적 맹신, 현대 우월주의 등 텍스트의 진리를 차단하는 편견.
2. 독단적 편견은 해석학적 순환의 응집도(`coherence_score`)를 저하시킵니다.
3. `REVISE_PREJUDICE`: 텍스트와의 대화를 통해 독단적 편견을 극복(`DOGMATIC_PREJUDICE_OVERCOME`)하고 생산적 선이해로 전환합니다.

### 2. 해석학적 순환 (`HERMENEUTIC_CIRCLE_CYCLE`)
1. 부분-전체 왕복 단계수(`steps`)에 따라 이해의 내적 일관성 점수를 심화합니다:
   $$\text{coherence\_score} = \min(100.0, \max(0.0, \text{coherence} + \text{steps} \times 15.0 - \text{len}(\text{dogmatic\_prejudices}) \times 5.0))$$

### 3. 영향사 의식 (`ACKNOWLEDGE_EFFECTIVE_HISTORY`)
1. 시간적 거리(`temporal_distance_years`)를 인식하고, 해석자 자신이 전통의 영향사 속에 있음을 인정(`historically_effected_awareness == true`)하면 영향사 의식이 각성되고 일관성 점수가 상승합니다.
2. 이를 거부하고 객관주의적 관찰자 흉내를 내면 지평 융합 계수가 $50\%$ 감쇄됩니다.

### 4. 지평 융합 (`FUSE_HORIZONS`)
1. 텍스트 지평 개념군(`text_horizon`)과 해석자 지평 개념군(`interpreter_horizon`) 간의 자카드 유사도(Jaccard Index)와 대화적 개방성(`dialogue_openness`, $0.0 \sim 1.0$)을 결합하여 지평 융합도(`fusion_degree`)를 계산합니다:
   $$\text{fusion\_degree} = (\text{jaccard} \times 60.0) + (\text{dialogue\_openness} \times 40.0)$$
2. 만약 영향사 의식이 결여된 상태라면 $\times 0.5$ 페널티를 적용합니다.
3. `fusion_degree >= 50.0` 이면 **지평 융합 성취(`HORIZONTVERSCHMELZUNG_ACHIEVED`)**로 판정하며, 공통 의미 지평에 기반한 통찰(`fused_insights`)을 산출합니다.

### 5. 최종 판정 (`verdict`)
1. 지평 융합이 달성되고 영향사 의식이 각성되었으며 `coherence_score >= 70.0`: **`AUTHENTIC_HERMENEUTIC_UNDERSTANDING`** (진정한 해석학적 이해)
2. 영향사 의식을 거부하고 융합도가 저조한 경우: **`OBJECTIVIST_HISTORICISM`** (객관주의적 역사주의의 오류)
3. 독단적 편견이 생산적 선이해를 초과하는 경우: **`ANACHRONISTIC_DOGMATISM`** (시대착오적 독단론)
4. 그 외: **`PRE_HERMENEUTIC_EXPLORER`**

---

## 입력 형식

표준 입력(`stdin`)으로 JSON 객체가 주어집니다:

```json
{
  "agent_id": "Hans_Georg_Gadamer_Master",
  "prejudices": [
    {"name": "enlightenment_prejudice_against_prejudice", "type": "DOGMATIC"},
    {"name": "hermeneutic_openness", "type": "PRODUCTIVE"}
  ],
  "operations": [
    {"op": "ACKNOWLEDGE_EFFECTIVE_HISTORY", "params": {"temporal_distance_years": 2300, "historically_effected_awareness": true}},
    {"op": "HERMENEUTIC_CIRCLE_CYCLE", "params": {"steps": 3}},
    {"op": "REVISE_PREJUDICE", "params": {"remove_dogma": "enlightenment_prejudice_against_prejudice"}},
    {"op": "FUSE_HORIZONS", "params": {
      "text_horizon": ["eudaimonia", "mesotes", "ergon"],
      "interpreter_horizon": ["eudaimonia", "human_flourishing", "mesotes"],
      "dialogue_openness": 0.95
    }}
  ]
}
```

---

## 출력 형식

표준 출력(`stdout`)으로 JSON 객체를 공백 없이 출력합니다:

```json
{
  "agent_id": "Hans_Georg_Gadamer_Master",
  "metrics": {
    "coherence_score": 100.0,
    "hermeneutic_iterations": 3,
    "effective_history_acknowledged": true,
    "fusion_degree": 68.0,
    "fusion_achieved": true,
    "productive_prejudices_count": 2,
    "dogmatic_prejudices_count": 0
  },
  "verdict": "AUTHENTIC_HERMENEUTIC_UNDERSTANDING",
  "fused_insights": [
    "FUSED_INSIGHT_ON_eudaimonia_AND_mesotes"
  ],
  "action_log": [
    ...
  ]
}
```
