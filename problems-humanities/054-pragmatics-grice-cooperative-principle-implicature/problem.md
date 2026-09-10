# 문제 054: 그라이스의 협력 원칙과 대화 격률 및 대화 함축 추론기 (H. P. Grice Cooperative Principle & Conversational Implicature Engine)

## 문제 설명

20세기 언어철학자이자 화용론(Pragmatics)의 거장 **H. P. 그라이스(H. Paul Grice, 1913–1988)**는 1975년 논문 『논리와 대화(Logic and Conversation)』에서 인간이 일상 언어를 구사할 때 문자 그대로의 의미(What is said)를 넘어 어떻게 맥락적 행간의 의미인 **대화 함축(Conversational Implicature)**을 전달하고 이해하는지를 밝혀냈습니다.

그라이스에 따르면 성공적인 의사소통은 참여자들이 암묵적으로 공유하는 대전제인 **협력 원칙(Cooperative Principle)**에 의해 지배됩니다:
> *"대화가 진행되는 각 단계에서 대화의 합의된 목적이나 방향이 요구하는 만큼 대화에 기여하라."*

협력 원칙은 다음과 같은 **4대 대화 격률(Four Conversational Maxims)**로 구체화됩니다:
1. **양의 격률(Maxim of Quantity)**:
   - 필요한 만큼의 정보를 제공하라 (너무 적게 제공하지 말 것).
   - 필요 이상의 지나친 정보를 제공하지 말 것.
2. **질의 격률(Maxim of Quality)**:
   - 진실된 기여를 하도록 노력하라.
   - 거짓이라고 믿는 것을 말하지 말 것.
   - 적절한 증거가 결여된 것을 말하지 말 것.
3. **관계의 격률 / 관련성의 격률(Maxim of Relation / Relevance)**:
   - 적절하고 관련성 있게(Relevant) 말하라.
4. **태도의 격률(Maxim of Manner)**:
   - 명료하게(Perspicuous) 말하라. 모호성과 중의성을 피하고, 간결하며 조리 있게 말하라.

화자가 대화 격률을 대하는 태도는 크게 세 가지로 나뉩니다:
- **준수(Observing)**: 격률을 정직하고 충실하게 따르는 일상적 진술.
- **위반(Violating)**: 청자를 속이거나 호도하기 위해 은밀하게 격률을 어기는 행위 (거짓말, 의도적 은폐).
- **조롱/노골적 위반(Flouting / Exploitation)**: 화자가 격률을 명백하고 노골적으로 어김으로써, 청자로 하여금 "화자가 협력 원칙 자체를 버린 것이 아니라면, 왜 일부러 저렇게 말했을까?"를 추론하게 하여 **대화 함축**을 전달하는 고차원적 소통 기법 (반어/풍자, 동어반복, 주제 회피, 완곡어법).

본 문제에서는 대화의 사실적 맥락(실제 진실, 화자의 신념)과 발화 턴의 정보량, 관련성, 명료성, 노골성(Blatancy) 메트릭을 입력받아, 4대 격률의 준수/위반/조롱 여부를 판정하고 **대화 함축 및 수사적 기법**을 유도하는 **그라이스 화용론 엔진**을 구현해야 합니다.

---

## 입력 형식

표준 입력(stdin)으로 다음과 같은 단일 JSON 객체가 주어집니다:

```json
{
  "context": {
    "truth_states": {"weather_is_nice": false},
    "speaker_beliefs": {"Bob": {"weather_is_nice": false}}
  },
  "turns": [
    {
      "id": "t1",
      "speaker": "Bob",
      "statement_claim": "weather_is_nice",
      "informative_score": 1.0,
      "relevance_score": 1.0,
      "clarity_score": 1.0,
      "is_blatant": true,
      "figure_type": "IRONY",
      "intended_implicature": "The weather is terribly catastrophic.",
      "cooperative_presumption": true
    }
  ]
}
```

- `context`: 대화 배경 지식:
  - `truth_states`: 현실 세계의 객관적 진리 상태 (`{"클레임명": bool}`).
  - `speaker_beliefs`: 화자별 주관적 신념 딕셔너리 (`{"화자": {"클레임명": bool}}`).
- `turns`: 대화 턴 리스트:
  - `id`: 턴 고유 식별자.
  - `speaker`: 발화자 이름.
  - `statement_claim` (선택): 명제 클레임 키.
  - `informative_score`: 정보량 점수 (1.0 기준, $< 0.4$는 정보 결핍, $> 1.6$은 과잉).
  - `relevance_score`: 대화 관련성 점수 (1.0 기준, $< 0.4$는 무관/탈선).
  - `clarity_score`: 태도/명료성 점수 (1.0 기준, $< 0.4$는 모호/장황).
  - `is_blatant`: 격률 위탈의 노골성 여부 (boolean, `true`이면 청자가 즉시 눈치챌 수 있는 의도적 위탈).
  - `figure_type` (선택): 수사적 기법 유형 (`"IRONY"`, `"TAUTOLOGY"`, `"DAMNING_WITH_FAINT_PRAISE"`, `"TOPIC_DEFLECTION"` 등).
  - `intended_implicature` (선택): 화자가 전달하고자 의도한 대화 함축 내용 문자열.
  - `cooperative_presumption`: 심층 수준에서 대화 협력 원칙을 공유하고 있는지 여부 (boolean).

---

## 출력 형식

표준 출력(stdout)으로 다음 구조를 갖는 단일 JSON 객체를 한 줄로 출력합니다:

```json
{
  "turn_evaluations": [
    {
      "turn_id": "t1",
      "evaluation": {
        "maxims": {
          "Quantity": {"status": "OBSERVED", "reason": "Speaker provides the appropriate amount of information required."},
          "Quality": {"status": "FLOUTED", "reason": "Speaker blatantly states an obvious falsehood (Irony/Metaphor/Hyperbole)."},
          "Relation": {"status": "OBSERVED", "reason": "Speaker contribution is directly relevant to current conversational purpose."},
          "Manner": {"status": "OBSERVED", "reason": "Speaker is clear, brief, orderly, and avoids obscurity."}
        },
        "cooperative_principle_preserved": true,
        "implicature_generated": true,
        "conversational_implicature": "The weather is terribly catastrophic.",
        "rhetorical_figure": "IRONY"
      }
    }
  ]
}
```

---

## 제약 사항

- $1 \le \text{turns} \le 50$
- 격률 판정 상태: `"OBSERVED"`, `"VIOLATED"`, `"FLOUTED"`
- 메모리 제한: 512 MB
- 실행 시간 제한: 3.0 초
