# 쇠렌 키에르케고르의 실존의 3단계: 미적·윤리적·종교적 실존과 믿음의 도약(Leap of Faith) 및 단독자 엔진

## 문제 설명

19세기 덴마크의 사상가이자 현대 실존주의(Existentialism)의 시조인 **쇠렌 키에르케고르(Søren Kierkegaard, 1813–1855)**는 『이것이냐 저것이냐』(Enten-Eller, 1843), 『공포와 전율』(Frygt og Bæven, 1843), 『죽음에 이르는 병』(Sygdommen til Døden, 1849)을 통해 서양 철학에 거대한 실존적 충격을 가했습니다.

키에르케고르는 헤겔의 거대한 역사철학적 체계 속에서 정작 피를 흘리고 고뇌하는 개별적 인간이 익명화되어 질식해 버렸다고 비판했습니다. 그는 외칩니다:
> *"진리는 주체성이다 (Sandheden er Subjektiviteten)."*
> *"체계는 완성될 수 있을지 몰라도, 살아 숨 쉬는 실존(Existenz)은 결코 사변적 체계 속에 갇힐 수 없다."*

인간은 구경꾼이 아니라 무대 위에서 자신의 삶을 결단해야 하는 행위자이며, 유한성과 무한성의 긴장 속에서 진정한 자아를 완성해 나가는 **실존의 3단계(Three Stages on Life's Way)**를 거칩니다:

```
        [ 1. 미적 실존 (Aesthetic Stage) ]  *전형: 돈 후안(Don Juan)*
          - 삶의 원리: 감각적 쾌락, 순간의 흥미, 유혹
          - 내적 필연성: 쾌락의 반복 -> 권태(Boredom) -> 찰나의 허무와 절망(Despair)
                        │
                        ▼ [ 결단: 이것이냐 저것이냐 (Enten-Eller) ]
        [ 2. 윤리적 실존 (Ethical Stage) ]  *전형: 빌헬름 판사(Judge Wilhelm)*
          - 삶의 원리: 보편적 도덕 법칙, 의무(Duty), 사회적 책임, 결혼
          - 내적 필연성: 유한한 인간은 도덕률의 완전성을 충족할 수 없음 -> 죄책감(Guilt)
                        │
                        ▼ [ 회개(Repentance)와 심연 앞에서의 선택 ]
        [ 3. 종교적 실존 (Religious Stage) ]  *전형: 아브라함(신앙의 기사, Knight of Faith)*
          - 삶의 원리: "신 앞의 단독자(The Single Individual before God)"
          - 핵심 도약:
            * 윤리의 목적론적 정지 (Teleological Suspension of the Ethical)
            * 7만 파톰(Fathoms)의 심연 위에서 행하는 믿음의 도약 (Leap of Faith)
            * 이성을 초월한 역설(Paradox)과 불합리(Absurd)의 수용
```

본 시스템은 키에르케고르의 실존 3단계 전이 메커니즘, 쾌락-권태-절망 전이, 윤리적 의무와 죄책감, 그리고 윤리의 목적론적 정지와 신앙의 기사 판정을 정밀하게 모델링하는 **키에르케고르 실존주의 지성 엔진**을 구현합니다.

---

## 핵심 엔진 아키텍처 및 규칙

### 1. 실존 단계 전이 상태 머신
1. **미적 실존 (`AESTHETIC`)**:
   - `SEEK_PLEASURE`: 쾌락 지수(`hedonic_level`)를 증가시키지만, 동시에 권태(`boredom_level`)를 누적합니다.
   - 권태가 20.0을 초과하면 찰나의 무의미함에서 비롯된 **절망(`despair_level`)**이 급격히 발생합니다.
   - 절망의 심연에서 보편적 의무를 선택(`MAKE_ETHICAL_CHOICE`)하면 즉시 **윤리적 실존(`ETHICAL`)**으로 질적 도약합니다.
2. **윤리적 실존 (`ETHICAL`)**:
   - `MAKE_ETHICAL_CHOICE`: 도덕적 의무와 사회적 충실성을 이행하여 윤리 점수(`ethical_duty_score`)를 쌓습니다.
   - 그러나 유한한 인간은 도덕적 완전성에 도달할 수 없으므로 필연적으로 **죄책감(`guilt_accumulated`)**이 누적됩니다.
   - 자신의 유한성을 고백하고 참회(`CONFESS_GUILT`)한 뒤, 7만 파톰의 심연 위에서 역설을 수용하는 믿음의 도약(`LEAP_OF_FAITH`, `accept_paradox: true`)을 감행하면 **종교적 실존(`RELIGIOUS`)**으로 비약합니다.
3. **종교적 실존 (`RELIGIOUS`)**:
   - 주체는 더 이상 군중 속에 숨지 않고 **신 앞의 단독자(`is_single_individual = true`)**로 섭니다.
   - **윤리의 목적론적 정지 (`SUSPEND_ETHICAL`)**:
     - 신의 절대적 명령(`divine_command == true`)과 절대적 신앙 헌신(`faith_commitment >= 0.75`)이 결합될 때만 정당한 **신앙의 기사(`KNIGHT_OF_FAITH`)**로 승인됩니다.
     - 공동체적 대의를 위한 희생은 **비극적 영웅(`TRAGIC_HERO`)**으로 판정됩니다.

---

## 입력 형식

JSON 문자열이 표준 입력(`stdin`)으로 주어집니다:

```json
{
  "agent_id": "Abraham_Pilgrim",
  "initial_stage": "AESTHETIC",
  "actions": [
    {"type": "SEEK_PLEASURE", "params": {"hedonic_value": 40.0}},
    {"type": "MAKE_ETHICAL_CHOICE", "params": {"duty_fulfillment": 25.0, "social_fidelity": 25.0}},
    {"type": "CONFESS_GUILT", "params": {"sincerity": 1.0}},
    {"type": "LEAP_OF_FAITH", "params": {"depth_fathoms": 70000.0, "accept_paradox": true}},
    {"type": "SUSPEND_ETHICAL", "params": {"faith_commitment": 1.0, "divine_command": true}}
  ]
}
```

---

## 출력 형식

실존적 지표와 단계 전이 이력, 상세 행위 로그를 JSON 형태로 표준 출력(`stdout`)에 공백 없이 출력합니다:

```json
{
  "agent_id": "Abraham_Pilgrim",
  "metrics": {
    "current_stage": "RELIGIOUS",
    "stage_history": ["AESTHETIC", "ETHICAL", "RELIGIOUS"],
    "hedonic_level": 40.0,
    "boredom_level": 24.0,
    "despair_level": 3.2,
    "ethical_duty_score": 50.0,
    "guilt_accumulated": 10.0,
    "faith_depth_fathoms": 70000.0,
    "is_single_individual": true,
    "existential_authenticity_score": 100.0
  },
  "verdict": "KNIGHT_OF_FAITH",
  "action_log": [
    {
      "type": "SEEK_PLEASURE",
      "stage": "AESTHETIC",
      "status": "PLEASURE_SOUGHT_BOREDOM_ACCUMULATED",
      "hedonic": 40.0,
      "boredom": 24.0,
      "despair": 3.2
    }
  ]
}
```

---

## 점수 산출 및 판정 공식

1. **실존적 진정성 점수 (`existential_authenticity_score`)**:
   - `AESTHETIC`: $\max(10.0, \min(40.0, 	ext{hedonic} 	imes 0.5) - \min(20.0, 	ext{despair} 	imes 0.5))$
   - `ETHICAL`: $\min(75.0, 40.0 + 	ext{ethical\_duty} 	imes 0.5)$
   - `RELIGIOUS`: $\min(100.0, 80.0 + (20.0 	ext{ if knight\_of\_faith else } 10.0))$
2. **최종 판정 (`verdict`)**:
   - `current_stage == "RELIGIOUS"`이고 신앙의 기사 검증 완료: `"KNIGHT_OF_FAITH"`
   - `current_stage == "ETHICAL"`이거나 비극적 영웅: `"TRAGIC_HERO_OR_ETHICAL_CITIZEN"`
   - `current_stage == "AESTHETIC"`이거나 절망에 침전: `"DESPAIRING_AESTHETE"`
