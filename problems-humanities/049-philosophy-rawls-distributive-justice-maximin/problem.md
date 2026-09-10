# 존 롤스의 정의론: 무지의 베일과 맥시민 분배 정의 최적화 엔진 (John Rawls Theory of Justice: Maximin Social Welfare Optimizer)

## 문제 설명

20세기 정치철학의 거장 **존 롤스(John Rawls, 1921–2002)**는 1971년 저서 『정의론(A Theory of Justice)』에서 공리주의(Utilitarianism)의 '최대 다수의 최대 행복'이 초래하는 소수자의 희생과 불평등을 비판하고, 사회 계약론을 현대적으로 재해석하여 공정으로서의 정의(Justice as Fairness)를 제창했습니다.

롤스는 사회 구성원들이 자신의 선천적 재능, 사회적 지위, 부, 성별 등을 전혀 모르는 **원초적 입장(Original Position)**에서 **무지의 베일(Veil of Ignorance)**을 쓰고 정의의 원칙을 합의한다면, 불확실성 하의 합리적 선택 규칙인 **맥시민 규칙(Maximin Rule - Maximum Minimorum)**에 따라 **최소 수혜자(The Least Advantaged)의 번영을 극대화하는 정책**에 필연적으로 합의할 것이라고 증명했습니다.

본 문제에서는 사회 계층별 효용 분포와 정책 제안들을 입력받아, 롤스의 **정의의 두 원칙(Two Principles of Justice)**의 사전식 우선성(Lexical Priority)을 검증하고, 롤스주의적 맥시민(Leximin) 승자와 공리주의적 총효용 승자를 비교 평가하는 **분배 정의 시뮬레이션 엔진**을 구현합니다.

---

## 롤스의 정의의 두 원칙과 사전식 우선성 (Lexical Priority)

어떤 사회 정책이 정의로운 것으로 인정받기 위해서는 다음 원칙들을 순서대로(사전식으로) 만족해야 합니다:

### 1. 제1원칙: 평등한 기본적 자유의 원칙 (Principle of Equal Basic Liberties)
- 모든 사람은 언론, 양심, 신체, 사유재산 등 기본적 자유에 대한 평등한 권리를 갖습니다.
- **사전식 우선성**: 어떠한 거대한 경제적 이익이나 총효용 증가로도 기본적 자유의 제한을 정당화할 수 없습니다 (`violates_basic_liberties == true`이면 즉시 실격).

### 2. 제2원칙: 사회적·경제적 불평등의 정당화 조건
사회적·경제적 불평등은 다음 두 조건을 동시에 충족할 때만 정당화됩니다:
- **(b) 공정한 기회균등의 원칙 (Fair Equality of Opportunity)**:
  모든 직위와 직책은 공정한 기회균등 아래 모든 사람에게 개방되어야 합니다 (`opportunity_index >= min_opportunity_index`).
- **(a) 차등의 원칙 (Difference Principle)**:
  사회적 불평등은 **사회 내 최소 수혜자에게 최대의 이익(Maximin)**이 돌아가도록 편성되어야 합니다.

---

## 동작 모드

### 1. 정책 평가 모드 (`mode: "evaluate_policies"`)
- 입력된 복수의 정책 제안들을 심사합니다:
  1. `violates_basic_liberties == true`이면 `VIOLATES_EQUAL_BASIC_LIBERTIES`로 실격.
  2. `opportunity_index < min_opportunity_index`이면 `INSUFFICIENT_FAIR_OPPORTUNITY`로 실격.
  3. 적격 정책들에 대해 각 계층 효용 분포의 지니 계수(Gini Coefficient), 총효용(공리주의 후생), 최소 수혜자 효용(롤스주의 후생), 내시 후생(로그 효용 합)을 계산합니다.
- **롤스주의 승자 선정 (Leximin Rule)**:
  - 최소 수혜자 효용($\min u_i$)이 가장 높은 정책을 선정합니다.
  - 최소값이 동일한 동점인 경우, 차하위 계층($u_{(2)}, u_{(3)}, \dots$)의 효용을 순차적으로 비교하여 우열을 가립니다.
- **공리주의 승자 선정 (Utilitarian Rule)**:
  - 총효용($\sum u_i$)이 가장 높은 정책을 선정합니다.
- **괴리 분석 (`comparison`)**:
  - 두 승자가 상이한지 여부(`is_divergent`), 롤스주의 정책 채택 시 최소 수혜자가 얻는 추가 효용(`least_advantaged_gain_under_rawls`), 총효용 효율성 희생분(`utilitarian_efficiency_tradeoff`)을 산출합니다.

### 2. 무지의 베일 시뮬레이션 모드 (`mode: "veil_of_ignorance_simulation"`)
- 무지의 베일 하에서 불평등 기피도(Inequality Aversion $ho$)에 따른 앳킨슨 사회 후생 함수(Atkinson Social Welfare Function)를 계산합니다:
  $$W(ho) = egin{cases} rac{1}{N} \sum_{i=1}^N u_i & (ho = 0, 	ext{벤담 공리주의}) \ \exp\left(rac{1}{N} \sum_{i=1}^N \ln(u_i)ight) & (ho = 1, 	ext{내시 후생/비례적 희생}) \ \left(rac{1}{N} \sum_{i=1}^N u_i^{1-ho}ight)^{rac{1}{1-ho}} & (ho > 0, ho 
eq 1) \end{cases}$$
- $ho 	o \infty$일 때 앳킨슨 후생 함수는 롤스의 맥시민 값($\min u_i$)으로 수렴함을 증명합니다.

---

## 입출력 예시

### 입력 (`evaluate_policies`)
```json
{
  "mode": "evaluate_policies",
  "config": {"min_opportunity_index": 0.5},
  "proposals": [
    {
      "id": "P1",
      "name": "현상 유지",
      "utility_distribution": [10, 20, 30, 40, 50],
      "violates_basic_liberties": false,
      "opportunity_index": 0.6
    },
    {
      "id": "P2",
      "name": "안전망 확충",
      "utility_distribution": [18, 25, 35, 45, 60],
      "violates_basic_liberties": false,
      "opportunity_index": 0.85
    }
  ]
}
```

### 출력
```json
{
  "mode": "evaluate_policies",
  "evaluated_proposals": [
    {
      "id": "P1",
      "name": "현상 유지",
      "eligible": true,
      "utility_distribution": [10, 20, 30, 40, 50],
      "least_advantaged_utility": 10,
      "total_utility": 150,
      "average_utility": 30.0,
      "nash_welfare": 16.3,
      "gini_coefficient": 0.2667,
      "opportunity_index": 0.6
    },
    {
      "id": "P2",
      "name": "안전망 확충",
      "eligible": true,
      "utility_distribution": [18, 25, 35, 45, 60],
      "least_advantaged_utility": 18,
      "total_utility": 183,
      "average_utility": 36.6,
      "nash_welfare": 17.566,
      "gini_coefficient": 0.2273,
      "opportunity_index": 0.85
    }
  ],
  "rawlsian_winner": {
    "id": "P2",
    "name": "안전망 확충",
    "least_advantaged_utility": 18,
    "total_utility": 183,
    "gini_coefficient": 0.2273
  },
  "utilitarian_winner": {
    "id": "P2",
    "name": "안전망 확충",
    "least_advantaged_utility": 18,
    "total_utility": 183,
    "gini_coefficient": 0.2273
  },
  "comparison": {
    "is_divergent": false,
    "least_advantaged_gain_under_rawls": 0.0,
    "utilitarian_efficiency_tradeoff": 0.0
  }
}
```
