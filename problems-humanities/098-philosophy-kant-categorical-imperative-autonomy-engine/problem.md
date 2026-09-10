# 임마누엘 칸트의 정언명령: 보편화 가능성 정식, 인간성 정식(목적 자체) 및 자율성 윤리 엔진

## 1. 개요 및 배경

> *"이 세상 안에서, 아니 그 밖에서조차 아무런 제한 없이 선하다고 생각될 수 있는 것은 오직 **선의지(Guter Wille)**뿐이다."*  
> — 임마누엘 칸트(Immanuel Kant), 『윤리형이상학 정초(Grundlegung zur Metaphysik der Sitten)』 (1785) 제1절

서양 근대 철학의 정점을 이룬 임마누엘 칸트는 도덕성의 기초를 '행위의 결과나 효용(공리주의)' 혹은 '신(神)의 계명'이 아닌, **인간 이성 자신의 자율적 입법(Autonomie der Vernunft)**에서 정초했습니다.

칸트에 따르면 도덕 법칙은 어떠한 조건이나 목적 달성을 위한 수단으로서 명령하는 **가언명령(Hypothetischer Imperativ, "칭찬받고 싶다면 정직하라")**이 아니라, 행위 자체의 내재적 원리로서 무조건적으로 명령하는 **정언명령(Kategorischer Imperativ, "정직하라!")**이어야 합니다.

칸트는 행위자의 주관적 행위 원칙인 **준칙(Maxime)**이 도덕 법칙이 될 수 있는지 검증하기 위해 세 가지 위대한 정식을 제시했습니다:

1. **제1정식: 보편화 가능성 정식 (Formel des allgemeinen Gesetzes)**:
   > *"네 의지의 준칙이 언제나 동시에 보편적 입법의 원리가 될 수 있도록 행위하라."*
   - **사유에서의 모순(Widerspruch im Denken)**: 만약 모든 사람이 돈을 빌릴 때 거짓 약속을 한다면, 약속이라는 제도 자체가 파괴되어 누구도 약속을 믿지 않게 됩니다. 준칙이 보편화되는 순간 스스로를 파괴하는 모순이 발생하며, 이는 절대적으로 금지되는 **자신과 타인에 대한 완전한 의무(Vollkommene Pflichten)**를 규정합니다.
   - **의지에서의 모순(Widerspruch im Wollen)**: 곤경에 처한 타인을 돕지 않겠다는 준칙은 사유 자체는 가능하지만, 모든 이성적 존재는 자신이 조력을 필요로 하는 순간이 필연적으로 존재하므로 그러한 세계를 일관되게 '의욕(Wollen)'할 수는 없습니다. 이는 권장되는 **불완전한 의무(Unvollkommene Pflichten)**를 규정합니다.
2. **제2정식: 인간성 정식 / 목적 자체로서의 인간 (Formel der Menschheit als Zweck an sich selbst)**:
   > *"너 자신과 다른 모든 사람의 인격을 결코 단순한 수단(Mittel)으로 취급하지 말고, 언제나 동시에 목적(Zweck)으로 대우하라."*
   - 타인을 속이거나 착취하여 자신의 목적을 달성하는 행위(예: 거짓말, 사기, 동의 없는 개인정보 착취)는 이성적 존재의 자율성을 부인하고 단순한 도구로 전락시키는 행위로서 단호히 금지됩니다.
3. **제3정식: 목적의 왕국 (Reich der Zwecke) 및 의지의 자율 (Autonomie des Willens)**:
   - 모든 이성적 행위자가 스스로 보편적 법칙을 제정하고 동시에 그 법에 복종하는 도덕적 공동체입니다. 행위가 처벌의 공포, 이익 추구, 단순한 동정심과 같은 **타율(Heteronomie)**이 아니라 오직 **"의무에 대한 존경(Aus Pflicht)"**에서 비롯될 때만 진정한 도덕적 가치(Moralischer Wert)를 가집니다.

당신은 자율주행차, 인공지능 정렬(AI Alignment), 개인정보 보호 및 스마트 컨트랙트 규범 검증을 위해, 칸트의 정언명령 3대 정식과 의무/자율성 평가 상태 머신을 정밀하게 구현한 **칸트 정언명령 & 자율성 윤리 엔진**을 설계해야 합니다.

---

## 2. 시스템 아키텍처 및 정언명령 판정 파이프라인

```
                  [ 에이전트의 주관적 행위 준칙 (Maxim) ]
          (agent_id, action_type, motive, treats_as_mere_means, consent)
                                     │
                                     ▼
             [ 1단계: 제1정식 - 보편화 가능성 테스트 (Universalizability) ]
                                     │
             ┌───────────────────────┴───────────────────────┐
             ▼                                               ▼
     [ 사유에서의 모순 검사 ]                        [ 의지에서의 모순 검사 ]
   (Contradiction in Conception)                   (Contradiction in the Will)
             │                                               │
   거짓 약속 / 절망적 자살                        재능 낭비 / 조력 거부
   -> 완전한 의무 위반 판정                        -> 불완전한 의무 위반 판정
             │                                               │
             └───────────────────────┬───────────────────────┘
                                     ▼
             [ 2단계: 제2정식 - 인간성 정식 테스트 (Humanity as End) ]
           (단순한 수단 취급 여부 및 고지된 동의 informed_consent 검증)
                                     │
             ┌───────────────────────┴───────────────────────┐
             ▼                                               ▼
   [ 도구적 착취 / 동의 결여 ]                      [ 목적 자체로 존중 ]
   -> 완전한 의무 위반 판정                                  │
             │                                               │
             ▼                                               ▼
   [ STRICTLY_IMPERMISSIBLE ]               [ 3단계: 제3정식 - 자율성 평가 ]
    (정언명령 절대 금지 명령)                (순수 의무 동기 vs 타율적 동기)
                                                             │
                                             ┌───────────────┴───────────────┐
                                             ▼                               ▼
                             [ 도덕적 가치 있음: 자율 ]       [ 적법하나 타율적 ]
                             (MORALLY_WORTHY_AUTONOMOUS)     (LEGAL_BUT_HETERONOMOUS)
```

---

## 3. 핵심 규칙 및 알고리즘 명세

### 3.1 행위 준칙(Maxim) 데이터 모델
각 준칙은 다음 필드로 정의됩니다:
- `maxim_id`: 고유 식별자 문자열.
- `agent_id`: 행위자 식별자 문자열.
- `action_type`: 행위 유형 문자열:
  - `LYING_PROMISE`, `DECEPTIVE_BORROWING`: 거짓 약속 및 사기 대출.
  - `SUICIDE_DESPAIR`, `SELF_DESTRUCTION`: 고통 회피를 위한 자살.
  - `REFUSE_AID`, `INDIFFERENCE_TO_SUFFERING`: 타인의 곤경 외면.
  - `WASTE_TALENTS`, `SLOTH_IDLENESS`: 자신의 재능 방치 및 나태.
  - `TELL_TRUTH`, `CONTRACT_FULFILL`, `HELP_NEEDY`: 정직, 계약 이행, 구호 행위.
- `motive`: 내면적 동기 문자열:
  - `DUTY`: 오직 도덕 법칙에 대한 존경심과 순수 의무(`Aus Pflicht`).
  - `INCLINATION`, `PRUDENCE_REPUTATION`, `FEAR_OF_PUNISHMENT`, `CALCULATED_PROFIT`: 이기적 경향성, 평판, 처벌 공포, 이익 계산(`Heteronomie`).
- `treats_others_as_mere_means`: 불리언 (타인을 단순한 수단으로 이용하는지 여부).
- `informed_consent`: 불리언 (상대방의 고지된 자율적 동의가 존재하는지 여부).

### 3.2 정언명령 3단계 검증 알고리즘

1. **보편화 가능성 테스트 (제1정식)**:
   - **사유에서의 모순 (`contradiction_in_conception`)**:
     - `action_type`이 `LYING_PROMISE`, `DECEPTIVE_BORROWING`, `SUICIDE_DESPAIR`, `SELF_DESTRUCTION` 중 하나인 경우 참(`true`)입니다.
     - 사유 모순이 발생하면 타인 또는 자신에 대한 **완전한 의무(Perfect Duty)**를 위반한 것입니다.
   - **의지에서의 모순 (`contradiction_in_will`)**:
     - `action_type`이 `REFUSE_AID`, `INDIFFERENCE_TO_SUFFERING`, `WASTE_TALENTS`, `SLOTH_IDLENESS` 중 하나인 경우 참(`true`)입니다.
     - 의지 모순이 발생하면 타인 또는 자신에 대한 **불완전한 의무(Imperfect Duty)**를 위반한 것입니다.

2. **인간성 정식 테스트 (제2정식)**:
   - `treats_others_as_mere_means == true`이거나 `informed_consent == false`인 경우 인간성 정식 위반(`humanity_violated = true`)입니다.
   - 또한 `action_type`이 기만 행위(`LYING_PROMISE`, `DECEPTIVE_BORROWING`)인 경우도 상대방의 동의 가능성을 원천 박탈하므로 인간성 정식 위반입니다.

3. **의지의 자율성 및 동기 평가 (제3정식)**:
   - `motive == "DUTY"`인 경우에만 순수 의무 동기(`pure_duty_motive = true`)이자 자율적 의지(Autonomie)로 인정됩니다.
   - 그 외의 동기는 행위의 외형이 법칙과 일치하더라도 타율적 동기(Heteronomie)로 분류됩니다.

### 3.3 최종 판정 및 목적의 왕국 구성원 자격
- **`STRICTLY_IMPERMISSIBLE`**:
  - 조건: `contradiction_in_conception == true` 또는 `humanity_violated == true`
  - 의무 분류: `PERFECT_DUTY_VIOLATION`
  - 목적의 왕국 승인 여부: `false`
  - `stats.strictly_impermissible` 1 증가.
- **`DEFICIENT_IMPERFECT_DUTY`**:
  - 조건: 위 절대 금지 사유가 없으나 `contradiction_in_will == true`
  - 의무 분류: `IMPERFECT_DUTY_VIOLATION`
  - 목적의 왕국 승인 여부: `false`
  - `stats.deficient_imperfect_duty` 1 증가.
- **목적의 왕국 조화 승인 (`kingdom_of_ends_member == true`)**:
  - 조건: 보편화 가능성 및 인간성 정식을 모두 통과한 준칙 (`stats.kingdom_of_ends_approved` 1 증가).
  - **`MORALLY_WORTHY_AUTONOMOUS`**:
    - `pure_duty_motive == true`인 경우
    - 의무 분류: `DUTIFUL_AND_AUTONOMOUS`
    - `stats.morally_worthy_autonomous` 1 증가.
  - **`LEGAL_BUT_HETERONOMOUS`**:
    - `pure_duty_motive == false`인 경우 (외적 적법성)
    - 의무 분류: `CONFORMS_TO_DUTY_EXTERNALLY`
    - `stats.legal_but_heteronomous` 1 증가.

### 3.4 도덕적 정렬률 (Alignment Score)
전체 평가 준칙 중 정언명령에 부합하는 가중 비율(소수점 둘째 자리 반올림):
$$\text{alignment\_score\_pct} = \text{round}\left(\frac{\text{autonomous} \times 1.0 + \text{heteronomous} \times 0.5}{\max(1, \text{total\_maxims})} \times 100, \ 2\right)$$

---

## 4. 입출력 형식 및 제약 조건

### 입력 형식 (JSON)
```json
{
  "maxims": [
    {
      "maxim_id": "m1",
      "agent_id": "borrower",
      "action_type": "LYING_PROMISE",
      "motive": "INCLINATION",
      "treats_others_as_mere_means": true,
      "informed_consent": false
    },
    {
      "maxim_id": "m2",
      "agent_id": "merchant",
      "action_type": "CONTRACT_FULFILL",
      "motive": "PRUDENCE_REPUTATION",
      "treats_others_as_mere_means": false,
      "informed_consent": true
    }
  ]
}
```

### 출력 형식 (JSON)
```json
{
  "stats": {
    "morally_worthy_autonomous": 0,
    "legal_but_heteronomous": 1,
    "strictly_impermissible": 1,
    "deficient_imperfect_duty": 0,
    "kingdom_of_ends_approved": 1
  },
  "alignment_score_pct": 25.0,
  "evaluation_logs": [
    {
      "maxim_id": "m1",
      "agent_id": "borrower",
      "action_type": "LYING_PROMISE",
      "motive": "INCLINATION",
      "tests": {
        "universalizability": {
          "contradiction_in_conception": true,
          "conception_reason": "Universal lying destroys the institution of promising itself (Self-defeating).",
          "contradiction_in_will": false,
          "will_reason": null
        },
        "humanity_as_end": {
          "violated": true,
          "reason": "Rational humanity treated merely as a means (instrumental exploitation without informed consent)."
        },
        "autonomy": {
          "pure_duty_motive": false
        }
      },
      "duty_classification": "PERFECT_DUTY_VIOLATION",
      "final_verdict": "STRICTLY_IMPERMISSIBLE",
      "kingdom_of_ends_member": false
    },
    { ... }
  ]
}
```
