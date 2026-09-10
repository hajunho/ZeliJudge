# 문제 053: 오스틴-설 화행 이론 및 적정 조건 검증 엔진 (Austin-Searle Speech Act Theory & Felicity Condition Engine)

## 문제 설명

20세기 언어철학자 **J. L. 오스틴(John L. Austin, 1911–1960)**은 1962년 저서 『말로 하는 일(How to Do Things with Words)』에서 언어가 단순히 사실을 기술하고 참/거짓(True/False)만을 다루는 도구가 아니라는 **기술적 오류(Descriptive Fallacy)**를 비판하며 **화행 이론(Speech Act Theory)**을 창시했습니다.

오스틴에 따르면 우리는 말을 함으로써 세상을 변화시키는 행위를 수행합니다:
- **발화 행위(Locutionary Act)**: 소리와 문법, 의미를 갖춘 말을 물리적으로 발음하는 행위.
- **발화 수반 행위(Illocutionary Act)**: 말 속에서 실현되는 화자의 소통적 행위(약속, 명령, 선언, 사과, 단언 등).
- **발화 효과(Perlocutionary Act)**: 발화를 통해 청자에게 도출되는 심리적·행동적 결과(설득, 위안, 당황 등).

이후 **존 설(John R. Searle, 1932–)**은 발화 수반 행위를 5대 범주로 체계화하고, 발화가 성공적으로 효력을 발휘하기 위해 충족해야 할 **적정 조건(Felicity Conditions)**을 정립했습니다:
1. **단언(Assertives)**: 화자가 명제의 진실성에 전념함 (진술, 보고, 주장).
2. **지시(Directives)**: 청자로 하여금 특정 미래 행동을 취하도록 유도함 (요청, 명령, 질문).
3. **약속/커미시브(Commissives)**: 화자 자신이 미래의 특정 행동을 이행하겠다는 구속력을 부담함 (약속, 맹세, 보증).
4. **표현(Expressives)**: 특정 상황에 대한 화자의 심리적 태도를 표출함 (감사, 축하, 사과).
5. **선언(Declarations)**: 적법한 제도적 권능을 바탕으로 현실 세계의 상태를 즉시 변화시킴 (선전포고, 명명식, 해고, 혼인 선언).

적정 조건이 결여된 발화는 오스틴의 기준에 따라 다음과 같이 분류됩니다:
- **불발/실효(Misfire)**: 화자의 권한 결여나 절차적 결함으로 인해 발화 행위 자체가 법적·제도적으로 성립되지 않고 원천 무효가 되는 결함.
- **남용/불성실(Abuse)**: 행위 자체는 겉으로 성립되었으나, 지킬 의도 없는 거짓 약속이나 믿지 않는 거짓말처럼 내적 성실성이 결여된 결함.

본 문제에서는 대화 맥락(화자, 청자, 권한, 능력, 신념, 제도적 상태)과 발화 스트림을 입력받아, 직접/간접 화행을 분류하고 적정 조건 위반 여부 및 제도적 상태 변화를 추적하는 **오스틴-설 화행 분석 엔진**을 구현해야 합니다.

---

## 입력 형식

표준 입력(stdin)으로 다음과 같은 단일 JSON 객체가 주어집니다:

```json
{
  "context": {
    "authorities": {"Captain": ["ship_commander"]},
    "capabilities": {"Audience": ["applaud"]},
    "hearer_prefers_action": true,
    "speaker_intentions": {"Captain": {"intends_to_perform": true}},
    "speaker_beliefs": {},
    "institutional_state": {"ship_name": "Unnamed", "christened": false}
  },
  "utterances": [
    {
      "id": "u1",
      "speaker": "Captain",
      "hearer": "Audience",
      "syntactic_form": "Declarative",
      "performative_verb": "baptize",
      "required_authority": "ship_commander",
      "proposition": {"actor": "speaker", "time": "present", "action": "name_ship"},
      "state_transformation": {"ship_name": "Queen Elizabeth", "christened": true}
    }
  ]
}
```

- `context`: 대화가 이루어지는 사회적·제도적 환경:
  - `authorities`: 화자별 보유 권한 리스트 (`{"이름": ["권한1", ...]}`).
  - `capabilities`: 청자별 수행 가능 행위 리스트.
  - `hearer_prefers_action`: 청자가 약속된 행위를 선호하는지 여부 (boolean).
  - `speaker_intentions`: 화자의 실제 이행 의도 (`intends_to_perform`: bool).
  - `speaker_beliefs`: 화자의 실제 참/거짓 신념 딕셔너리.
  - `institutional_state`: 초기 제도적/공식적 상태 딕셔너리.
- `utterances`: 순차적으로 주어지는 발화 리스트:
  - `id`: 발화 고유 ID.
  - `speaker`, `hearer`: 발화자와 청자.
  - `syntactic_form`: 통사적 문장 유형 (`"Declarative"`, `"Imperative"`, `"Interrogative"`, `"Exclamative"`).
  - `performative_verb` (선택): 명시적 수행 동사 (`"promise"`, `"order"`, `"claim"`, `"baptize"` 등).
  - `indirect_cue` (선택): 간접 화행 신호 (`"ability_request"`, `"desire_statement"` 등).
  - `required_authority` (선택): 선언(Declaration) 수행 시 요구되는 권한 명칭.
  - `proposition`: 명제 내용 (`actor`, `time`, `action` 또는 `claim`).
  - `state_transformation` (선택): 유효한 선언 화행 시 변경될 상태 키-값 쌍.

---

## 출력 형식

표준 출력(stdout)으로 다음 구조를 갖는 단일 JSON 객체를 한 줄로 출력합니다:

```json
{
  "evaluations": [
    {
      "utterance_id": "u1",
      "evaluation": {
        "direct_force": "DECLARATION",
        "effective_force": "DECLARATION",
        "is_indirect": false,
        "is_felicitous": true,
        "verdict": "FELICITOUS",
        "flaw_type": null,
        "violations": [],
        "updated_institutional_state": {
          "ship_name": "Queen Elizabeth",
          "christened": true
        }
      }
    }
  ],
  "final_institutional_state": {
    "ship_name": "Queen Elizabeth",
    "christened": true
  }
}
```

- `evaluations`: 발화별 분석 결과:
  - `direct_force`: 통사적/동사적 표면 화행 유형.
  - `effective_force`: 간접 화행 맥락을 반영한 최종 유효 화행 유형.
  - `is_indirect`: 간접 화행 여부 (boolean).
  - `is_felicitous`: 적정 조건 충족 여부 (boolean).
  - `verdict`: 판정 결과 (`"FELICITOUS"`, `"MISFIRE"`, `"ABUSE"`).
  - `flaw_type`: 결함 유형 (`"MISFIRE"`, `"ABUSE"`, 결함 없을 시 `null`).
  - `violations`: 위반된 적정 조건 상세 리스트.
  - `updated_institutional_state`: 해당 발화 처리 후의 제도적 상태.
- `final_institutional_state`: 모든 발화가 완료된 후의 최종 제도적 상태.

---

## 제약 사항

- $1 \le \text{utterances} \le 50$
- 모든 명칭 및 키는 공백 없는 영문자/밑줄 문자열
- 화행 분류: `ASSERTIVE`, `DIRECTIVE`, `COMMISSIVE`, `EXPRESSIVE`, `DECLARATION`
- 메모리 제한: 512 MB
- 실행 시간 제한: 3.0 초
