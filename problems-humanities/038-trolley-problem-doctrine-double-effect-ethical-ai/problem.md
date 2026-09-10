# 문제 #038: 5명을 살리기 위해 1명을 희생시켜도 될까요?!: 윤리학(Ethics) & 규범철학: 전차 문제(Trolley Problem), 칸트 의무론(목적 자체의 공식), 이중결과의 원리(Doctrine of Double Effect) 및 MIT 모럴 머신 자율주행 AI 의사결정 엔진

## 실무 및 학술 배경: 레벨 4 자율주행차의 불가피한 충돌(Crash Inevitability)과 AI 윤리 알고리즘의 딜레마
완전 자율주행(레벨 4/5) 상용화를 앞둔 글로벌 모빌리티 기업의 ADAS/자율주행 제어 연구팀은 비상 제동 시스템(AEB) 고장으로 시속 60km로 질주하는 차량이 횡단보도를 덮치는 극한의 위기 상황 시뮬레이션을 분석하고 있었습니다.

차량 전방에는 파란 불에 정상 보행 중인 초등학생 5명이 있고, 핸들을 급히 꺾어 우측 인도나 콘크리트 방호벽으로 돌진하면 무단횡단 중인 성인 1명 또는 차에 타고 있는 단독 탑승자가 사망하게 됩니다:
* *"단순히 사망자 수를 최소화하는 것이 소프트웨어의 절대 선인가요?"* (행위 공리주의의 단순 계산)
* *"탑승자를 살리기 위해 무고한 보행자를 들이받거나, 보행자를 방패 삼아 충돌을 흡수하도록 코딩하는 것은 살인인가요?"* (칸트 의무론 및 목적 자체의 공식 위반)
* *"선로를 전환하여 1명이 우연히 말려들어 사망하는 것과, 사람을 육교에서 밀어 물리적 충격 흡수체(means)로 사용하는 것은 도덕적으로 왜 다를까요?"* (필리파 풋과 주디스 톰슨의 이중결과의 원리, Doctrine of Double Effect)

전통적인 철학적 사고실험이었던 **전차 문제(Trolley Problem)**는 이제 독일 윤리위원회(Ethics Commission for Automated Driving), 미국 도로교통안전국(NHTSA), 그리고 MIT의 4천만 건 글로벌 실험인 **모럴 머신(Moral Machine)**을 거쳐 실제 자율주행 인공지능이 판단해야 하는 법적·수리적 알고리즘의 최전선이 되었습니다.

AI 윤리 및 시스템 정책 설계자로서, **행위 공리주의(Act Utilitarianism)**, **칸트의 정언명령 제2공식(Kantian Humanity as an End Formulation)**, **토마스 아퀴나스-필리파 풋의 이중결과의 원리(DDE)**, 그리고 **MIT 모럴 머신 다변수 인구통계·준법 가중치 모델**을 결합한 자율주행 다중 규범 윤리 심판 엔진을 구현하십시오.

---

## 4대 윤리 평가 프레임워크 사양

### 1. 개체 효용 및 사회적 가치 가중치 산출 (MIT Moral Machine Augmented Model)
각 피해자/생존자 개체 $e$에 대해 다음 공식으로 가치 점수 $V(e)$를 계산합니다:
$$V(e) = 100.0 	imes 	ext{weight} + \Delta_{	ext{age}} + \Delta_{	ext{law}}$$
* 기본 생명 가치: $100.0 	imes 	ext{weight}$ (기본 `weight = 1.0`).
* 연령 보정치 ($\Delta_{	ext{age}}$):
  - 18세 미만 미성년자 (`age < 18`): `+child_bonus` (기본 $+30.0$)
  - 65세 초과 고령자 (`age > 65`): `-elderly_penalty` (기본 $-10.0$)
  - 그 외: $0.0$
* 준법 여부 보정치 ($\Delta_{	ext{law}}$):
  - 신호 준수 등 법규 준수자 (`law_abiding == True`): `+law_bonus` (기본 $+20.0$)
  - 무단횡단자 (`law_abiding == False`): `-law_bonus` (기본 $-20.0$)

각 선택지(Option)의 순 효용 $U_{	ext{MM}}$:
$$U_{	ext{MM}} = \sum_{s \in 	ext{saved}} V(s) - \sum_{c \in 	ext{casualties}} V(c) - (	ext{omission\_hurdle if is\_active\_intervention else } 0)$$
* 능동적 개입(Commission, `is_active_intervention == True`)을 선택할 경우, 부작위 편향(Omission Bias) 및 형법상 작위의 책임 허들을 반영하여 `omission_hurdle`(기본 $15.0$)의 감점을 부여합니다.
* 최고 점수를 획득한 선택지를 최종 채택합니다.

---

### 2. 행위 공리주의 (Pure Act Utilitarianism)
* 단순 생명 수의 극대화를 평가합니다:
  $$\Delta U_{	ext{lives}} = |	ext{saved}| - |	ext{casualties}|$$
* `net_lives`가 가장 큰 선택지를 채택합니다.

---

### 3. 칸트 의무론 (Kantian Deontology: 목적 자체의 공식)
인간을 다른 목적을 위한 단순한 도구(mere means)나 물리적 수단으로 전락시키는 행위를 엄격히 금지합니다:
* 만약 `is_harm_instrumental_means == True`이거나 `action_type`이 신체 직접 가해(`PHYSICAL_PUSH`, `ORGAN_HARVEST_MURDER`)인 경우:
  - 판정: `"FORBIDDEN"`
  - 사유: `"VIOLATION_OF_HUMANITY_FORMULATION_USED_AS_MERE_MEANS"` 또는 `"DIRECT_BATTERY_ASSAULT_OF_RATIONAL_AGENT"`
* 그렇지 않은 경우 (예: 선로 전환으로 인한 부수적 사망, 위험 회피 조향 등):
  - 판정: `"PERMITTED"`
  - 사유: `"NO_CATEGORICAL_IMPERATIVE_BREACH"`

---

### 4. 이중결과의 원리 (Doctrine of Double Effect, DDE)
좋은 결과를 낳지만 나쁜 결과가 예견되는 행위가 도덕적으로 정당화되기 위한 3대 엄격 검정을 수행합니다:
1. **행위 자체의 도덕적 성격 (`act_nature`)**:
   - `action_type`이 본질적 악(직접적 물리 폭력, 강제 살해 등: `PHYSICAL_PUSH`, `DIRECT_BATTERY`, `ORGAN_HARVEST_MURDER`)이면 탈락 $	o$ `"FAILED_ACT_NATURE_INHERENTLY_EVIL"`.
2. **수단-목적 인과성 (`means_end_causality`)**:
   - 악한 결과(사망)가 선한 결과를 달성하기 위한 필수 수단(`is_harm_instrumental_means == True`)으로 사용되었다면 탈락 $	o$ `"FAILED_EVIL_AS_INSTRUMENTAL_MEANS"`. (악한 결과는 오직 부수적 효과(side-effect)로서만 예견되어야 함).
3. **비례성의 원칙 (`proportionality`)**:
   - 선한 결과가 예견된 악한 결과보다 크거나 같지 못하면 탈락 $	o$ `"FAILED_PROPORTIONALITY_NET_HARM_GREATER_OR_EQUAL"` ($|	ext{saved}| \le |	ext{casualties}|$ 이고 $|	ext{casualties}| > 0$).
* 모든 검정을 통과하면 `status = "PERMISSIBLE"`, 하나라도 실패하면 `status = "IMPERMISSIBLE"` 및 실패 목록 반환.

---

## 입력 형식
표준 입력(stdin)으로 JSON 데이터가 주어집니다:
```json
{
  "config": {
    "child_bonus": 30.0,
    "elderly_penalty": 10.0,
    "law_bonus": 20.0,
    "omission_hurdle": 15.0
  },
  "scenarios": [
    {
      "name": "classic_switch",
      "options": [
        {
          "id": "switch_divert",
          "action_type": "SWITCH_TRACK",
          "is_active_intervention": true,
          "is_harm_instrumental_means": false,
          "casualties": [{"id": "bystander_1", "age": 30, "law_abiding": true}],
          "saved": [
            {"id": "worker_0", "age": 40, "law_abiding": true},
            {"id": "worker_1", "age": 40, "law_abiding": true},
            {"id": "worker_2", "age": 40, "law_abiding": true},
            {"id": "worker_3", "age": 40, "law_abiding": true},
            {"id": "worker_4", "age": 40, "law_abiding": true}
          ]
        },
        {
          "id": "do_nothing",
          "action_type": "MAINTAIN_COURSE",
          "is_active_intervention": false,
          "is_harm_instrumental_means": false,
          "casualties": [
            {"id": "worker_0", "age": 40, "law_abiding": true},
            {"id": "worker_1", "age": 40, "law_abiding": true},
            {"id": "worker_2", "age": 40, "law_abiding": true},
            {"id": "worker_3", "age": 40, "law_abiding": true},
            {"id": "worker_4", "age": 40, "law_abiding": true}
          ],
          "saved": []
        }
      ]
    }
  ]
}
```

## 출력 형식
표준 출력(stdout)으로 JSON 단일 라인으로 평가 결과를 출력합니다:
```json
{
  "scenarios_evaluated": 1,
  "evaluations": [
    {
      "scenario": "classic_switch",
      "utilitarian_evaluation": {
        "selected_option": "switch_divert",
        "scores": {
          "switch_divert": {"net_lives": 4, "saved_count": 5, "lost_count": 1},
          "do_nothing": {"net_lives": -5, "saved_count": 0, "lost_count": 5}
        }
      },
      "kantian_deontology": {
        "switch_divert": {"verdict": "PERMITTED", "reason": "NO_CATEGORICAL_IMPERATIVE_BREACH"},
        "do_nothing": {"verdict": "PERMITTED", "reason": "NO_CATEGORICAL_IMPERATIVE_BREACH"}
      },
      "doctrine_of_double_effect": {
        "switch_divert": {"status": "PERMISSIBLE", "failed_tests": []},
        "do_nothing": {"status": "IMPERMISSIBLE", "failed_tests": ["FAILED_PROPORTIONALITY_NET_HARM_GREATER_OR_EQUAL"]}
      },
      "moral_machine_evaluation": {
        "selected_option": "switch_divert",
        "scores": {
          "switch_divert": 465.0,
          "do_nothing": -600.0
        }
      }
    }
  ]
}
```
