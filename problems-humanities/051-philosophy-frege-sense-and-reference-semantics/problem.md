# 고틀로프 프레게의 뜻과 지시체: 동일성 퍼즐과 내포적 맥락 의미론 엔진 (Gottlob Frege Sense and Reference & Propositional Attitude Evaluator)

## 문제 설명

현대 기호 논리학, 수리철학, 그리고 형식 의미론(Formal Semantics)의 아버지인 **고틀로프 프레게(Gottlob Frege, 1848–1925)**는 1892년 발표한 기념비적 논문 『뜻과 지시체에 관하여(Über Sinn und Bedeutung)』에서 언어 표현이 대상을 가리키는 관계에 대한 심오한 의미론적 모델을 확립했습니다.

프레게는 고전적 지칭론이 해결하지 못한 두 가지 거대한 철학적 난제인 **'동일성의 퍼즐(Frege's Puzzle of Identity)'**과 **'내포적 맥락(Intensional Contexts)에서의 동일자 대치 원리(Salva Veritate) 파탄'**을 해결하기 위해, 언어 기호(Zeichen)가 단순히 대상(지시체 - Bedeutung)에 일대일 대응하는 것이 아니라, 대상이 의식에 주어지는 고유한 방식인 **뜻(Sinn / Mode of Presentation)**을 매개로 한다는 혁신적인 이론을 제시했습니다.

본 문제에서는 온톨로지(객체, 뜻, 행위자의 신념 네트워크)를 바탕으로, 동일성 명제의 인지적 가치(Cognitive Value), 지시체 결여(Empty Names), 그리고 믿음이나 지식과 같은 명제 태도(Propositional Attitudes) 환경에서 발생하는 대치 원리의 성립 및 실패를 판정하는 **프레게식 형식 의미론 엔진**을 구현합니다.

---

## 핵심 이론 및 동작 명세

### 1. 세 가지 구성 요소: 기호, 뜻, 지시체
- **기호 (Zeichen / Expression)**: 언어적 이름이나 기호 (예: "샛별", "개밥바라기별").
- **뜻 (Sinn / Sense)**: 지시체가 생각 속에 드러나는 방식(Mode of Presentation).
- **지시체 (Bedeutung / Reference)**: 기호가 현실 세계에서 지시하는 실제 대상(Object)이나 명제의 진리값(Truth-Value: 참 또는 거짓).

### 2. 동일성의 퍼즐 (Frege's Puzzle of Identity)
- $a = a$ (예: "샛별은 샛별이다"):
  - 동일한 기호, 동일한 뜻, 동일한 지시체.
  - 경험적 연구 없이 논리적으로 자명한 선험적(A Priori) 분석 명제 (`TRIVIAL_APRIORI`).
- $a = b$ (예: "샛별은 개밥바라기별이다"):
  - $a$와 $b$는 **서로 다른 뜻(Sinn)**을 지니지만, 천문학적 관측과 경험을 통해 **동일한 지시체(Bedeutung - 금성)**를 가리킴이 밝혀짐.
  - 인류의 지식을 확장하는 귀중한 경험적 종합 판단 (`INFORMATIVE_APOSTERIORI_DISCOVERY`).

### 3. 지시체 없는 기호 (Empty Names & Truth-Value Gap)
- 예: "현재의 프랑스 왕(The present King of France)", "페가수스(Pegasus)".
- 명확한 뜻(Sinn)은 존재하지만, 현실 세계에 대응하는 지시체(Bedeutung)가 존재하지 않습니다.
- 프레게에 따르면 지시체가 결여된 기호가 포함된 명제는 참도 거짓도 될 수 없는 **진리값의 결여(Truth-Value Gap)** 상태가 됩니다 (`EMPTY_NAME_LACKS_TRUTH_VALUE`).

### 4. 내포적 맥락과 명제 태도 (Intensional / Indirect Contexts)
- **라이프니츠의 법칙 (Salva Veritate - 진리값 보존 대치)**:
  동일한 지시체를 갖는 두 표현 $a$와 $b$가 있을 때, 외연적(Extensional) 문맥에서는 $a$ 대신 $b$를 치환해도 전체 문장의 참/거짓이 보존되어야 합니다.
- **간접 화법(Oratio Obliqua) 및 명제 태도(Belief, Knowledge)**:
  "로이스 레인은 슈퍼맨이 날 수 있다고 믿는다"라는 문장에서 "슈퍼맨"과 "클라크 켄트"는 현실에서 동일 인물(동일 지시체)입니다.
  그러나 로이스 레인이 그 동일성을 모른다면, "로이스 레인은 클라크 켄트가 날 수 있다고 믿는다"는 거짓이 됩니다!
- **프레게의 설명**:
  믿음이나 지식과 같은 간접 맥락에서 단어의 지시체는 실제 대상이 아니라 **통상적인 뜻(Indirect Reference is Customary Sense)**으로 전환됩니다. 로이스 레인의 생각 속에서 '슈퍼맨'의 뜻과 '클라크 켄트'의 뜻은 다르기 때문에, 대치 원리가 파탄납니다 (`salva_veritate_failed == true`).

---

## 지원 명령

1. `evaluate_identity`:
   - 파라미터: `expr_a`, `expr_b`.
   - 두 표현의 동일성 판정, 지시체 일치 여부, 인지적 가치(`TRIVIAL_APRIORI`, `INFORMATIVE_APOSTERIORI_DISCOVERY`, `EMPTY_NAME_LACKS_TRUTH_VALUE`, `FALSE_SYNTHETIC`) 산출.
2. `evaluate_propositional_attitude`:
   - 파라미터: `agent_id`, `expr_subject`, `expr_predicate`, `substituted_subject`.
   - 행위자의 신념망을 기반으로 원본 믿음과 치환된 믿음의 진위, 실제 지시체 일치 여부, 동일자 대치 원리 파탄 여부(`salva_veritate_failed`) 판정.

---

## 입출력 예시

### 입력 (`evaluate_identity`)
```json
{
  "ontology": { ... },
  "operation": "evaluate_identity",
  "params": {"expr_a": "morning_star", "expr_b": "evening_star"}
}
```

### 출력
```json
{
  "identity_statement": "morning_star = evening_star",
  "referent": "VENUS",
  "referent_a": "VENUS",
  "referent_b": "VENUS",
  "is_identical": true,
  "truth_value": true,
  "cognitive_value": "INFORMATIVE_APOSTERIORI_DISCOVERY (a = b)"
}
```
