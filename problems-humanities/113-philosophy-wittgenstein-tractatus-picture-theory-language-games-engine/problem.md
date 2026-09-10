# 루트비히 비트겐슈타인: 초기 논리철학 논고(그림 이론·말할 수 없는 것)와 후기 철학적 탐구(언어놀이·가족유사성) 엔진

## 문제 설명

20세기 언어철학의 지형을 혼자 힘으로 두 번이나 완전히 전복시킨 세기의 철학자 **루트비히 비트겐슈타인(Ludwig Wittgenstein, 1889–1951)**은 전기의 『논리철학 논고』(Tractatus Logico-Philosophicus, 1921)와 후기의 『철학적 탐구』(Philosophische Untersuchungen, 1953)를 통해 서양 철학의 모든 형이상학적 난제들이 '언어의 논리를 오해한 데서 비롯된 언어의 질병'임을 통찰했습니다.

비트겐슈타인의 철학은 서로 대립하면서도 깊은 연속성을 지닌 전기와 후기의 두 봉우리로 구성됩니다:

```
        [ 전기: 논리철학 논고 (Tractatus Logico-Philosophicus) ]
          - 모토: "세계는 일어나는 모든 것(사실)이다" (Die Welt ist alles, was der Fall ist. 1)
          - 그림 이론 (Picture Theory): 명제는 실재의 논리적 모형(Logical Picture)이다.
            * 이름(Name) ──(대응)──> 대상(Object)
            * 요소명제(Elementary Prop) ──(동형성)──> 사태(State of Affairs)
            * 복합명제 ──(진리함수)──> 사실(Fact)
          - 언어의 한계와 침묵 (Proposition 7):
            * 뜻을 지닌 명제(Sinn): 자연과학적·경험적 사실 명제.
            * 무의미(Sinnlos): 논리적 동어반복($P \lor \neg P$) 및 모순.
            * 말도 안 되는 것(Unsinn): 윤리학, 미학, 종교, 삶의 의미 등 초월적 가치.
            * "말할 수 없는 것에 대해서는 침묵해야 한다." (Wovon man nicht sprechen kann, darüber muss man schweigen. 7)
                         │
                         ▼ [ 패러다임 전환: 본질주의·이상언어 거부 -> 일상언어로의 귀환 ]
        [ 후기: 철학적 탐구 (Philosophical Investigations) ]
          - 모토: "단어의 의미는 언어 안에서의 그것의 사용이다" (Bedeutung als Gebrauch. §43)
          - 언어 놀이 (Language-Games / Sprachspiele):
            * 언어는 고정된 거울이 아니라 벽돌공의 연장통 속 도구처럼 삶의 실천과 엮인 활동.
          - 삶의 양식 (Form of Life / Lebensform):
            * "언어를 상상한다는 것은 삶의 한 양식을 상상하는 것이다." (§19)
          - 가족 유사성 (Family Resemblance / Familienähnlichkeit):
            * '게임(Game)'을 포괄하는 단일한 공통 본질은 없음.
            * 수많은 특징들이 얽히고설킨 유사성의 그물망(Criss-crossing similarities)만 존재.
          - 사적 언어 논변 (Private Language Argument / 상자 속의 딱정벌레):
            * 오직 나 혼자만의 내밀한 감각에 붙인 사적 기호는 객관적 규칙 검증이 불가능하므로 성립 불가.
```

본 시스템은 전기 비트겐슈타인의 그림 이론 기반 명제 논리 검증(Sinn / Sinnlos / Unsinn 구분 및 명제 7번 침묵 판정)과 후기 비트겐슈타인의 언어놀이(사용으로서의 의미), 가족 유사성 네트워크 및 사적 언어 비판을 통합 시뮬레이션하는 **비트겐슈타인 언어철학 분석 엔진**을 구현합니다.

---

## 핵심 엔진 아키텍처 및 규칙

### 1. 전기 논고 모드 (`ANALYZE_PROPOSITION_TRACTATUS`)
1. **경험적 사실 명제 (`category == "EMPIRICAL"`)**:
   - 명제 속 모든 이름(용어)이 세계 내 알려진 대상(`known_objects`)과 1:1 대응되고, 해당 사태가 세계 사실(`world_facts`)과 일치하면 `HAS_SENSE_TRUE`, 일치하지 않더라도 구조가 유효하면 `HAS_SENSE_FALSE`로 판정합니다.
   - 분류: **`SINN`** (뜻을 가짐).
2. **논리적 형식 명제 (`category == "TAUTOLOGY"`)**:
   - 경험적 정보를 담지 않으나 논리적 비계 역할을 수행합니다.
   - 분류: **`SINNLOS`** (무의미, 논리적 필연).
3. **가치/형이상학적 명제 (`category in ("ETHICAL", "METAPHYSICAL", "MYSTICAL")`)**:
   - 언어로 그릴 수 없는 초월적 영역입니다.
   - 분류: **`UNSINN`** (말도 안 됨 / 비의미).
   - 상태: `TRANSCENDS_LANGUAGE_MUST_BE_SILENT`.
   - 비트겐슈타인 7번 명제 적용 (`proposition_7_applied = true`), `silence_invoked_count += 1`.

### 2. 후기 탐구 모드
1. **언어 놀이 (`PLAY_LANGUAGE_GAME`)**:
   - 주어진 삶의 양식(`form_of_life`, 예: `BUILDER_SITE`)과 실천적 맥락(`action_context`) 속에서 기호의 의미를 도출합니다:
     $$\text{meaning\_as\_use} = \text{"USE\_AS\_" + action\_context + "\_IN\_" + form\_of\_life}$$
2. **가족 유사성 검사 (`CHECK_FAMILY_RESEMBLANCE`)**:
   - 개념에 속하는 여러 사례(`instances`)의 특징들을 비교합니다.
   - 모든 사례에 100% 공통된 단일 본질이 없고, 특징들이 복합적으로 겹쳐 있을 때 `CRISS_CROSSING_SIMILARITIES`로 판정하여 전통적 본질주의를 해체합니다.
3. **사적 언어 논변 (`TEST_PRIVATE_LANGUAGE`)**:
   - 감각 기호가 공적 교정 기준(`has_public_criterion`)을 갖추지 못하면 규칙 따르기 실패(`PRIVATE_LANGUAGE_FALLACY_BEETLE_DROPPED`)로 판정합니다.

### 3. 최종 판정 (`verdict`)
1. 후기 언어놀이나 가족유사성, 사적언어 연산이 1개 이상 수행된 경우: **`ORDINARY_LANGUAGE_THERAPIST`** (일상언어 치유자)
2. 침묵 명령이 호출되고 논고 분석만 수행된 경우: **`TRACTARIAN_LOGICAL_ATOMIST`** (논고적 논리원자론자)
3. 그 외: **`METAPHYSICAL_DOGMATIST`**

---

## 입력 형식

표준 입력(`stdin`)으로 JSON 객체가 주어집니다:

```json
{
  "agent_id": "Ludwig_Wittgenstein_Universal",
  "initial_paradigm": "TRACTATUS",
  "known_objects": ["paris", "france"],
  "world_facts": ["paris capital of france"],
  "operations": [
    {"op": "ANALYZE_PROPOSITION_TRACTATUS", "params": {"text": "paris capital of france", "category": "EMPIRICAL", "terms": ["paris", "france"]}},
    {"op": "ANALYZE_PROPOSITION_TRACTATUS", "params": {"text": "Beauty is objective harmony", "category": "ETHICAL", "terms": ["beauty", "harmony"]}},
    {"op": "PLAY_LANGUAGE_GAME", "params": {"form_of_life": "PHILOSOPHY_SEMINAR", "token": "SHOW_FLY_OUT_OF_BOTTLE", "action_context": "CONCEPTUAL_CLARIFICATION"}},
    {"op": "CHECK_FAMILY_RESEMBLANCE", "params": {
      "concept": "NUMBER",
      "instances": [
        {"name": "natural_numbers", "features": ["counting", "discrete", "positive"]},
        {"name": "integers", "features": ["discrete", "negative_included"]},
        {"name": "real_numbers", "features": ["continuum", "measurement"]}
      ]
    }},
    {"op": "TEST_PRIVATE_LANGUAGE", "params": {"sensation_name": "Inner_Qualia_Q", "has_public_criterion": false}}
  ]
}
```

---

## 출력 형식

표준 출력(`stdout`)으로 JSON 객체를 공백 없이 출력합니다:

```json
{
  "agent_id": "Ludwig_Wittgenstein_Universal",
  "paradigm": "TRACTATUS",
  "metrics": {
    "propositions_analyzed": 2,
    "silence_invoked_count": 1,
    "nonsense_detected_count": 1,
    "language_games_count": 1,
    "family_resemblance_cases": 1,
    "private_language_tests": 1
  },
  "verdict": "ORDINARY_LANGUAGE_THERAPIST",
  "tractatus_analysis": [
    ...
  ],
  "language_games": [
    ...
  ],
  "family_resemblances": [
    ...
  ],
  "private_language_evaluations": [
    ...
  ],
  "action_log": [
    ...
  ]
}
```
