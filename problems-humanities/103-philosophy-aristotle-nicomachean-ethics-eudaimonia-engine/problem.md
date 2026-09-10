# 아리스토텔레스의 니코마코스 윤리학: 최고선 행복(Eudaimonia), 중용(Mesotes) 3분법, 도덕적·지적 덕 및 의지의 나약함(Akrasia) 시뮬레이션 엔진

## 문제 설명

기원전 4세기 아리스토텔레스(Aristotle, BC 384~322)가 아들 니코마코스에게 헌정한 『니코마코스 윤리학(Ethica Nicomachea)』은 서양 목적론적 윤리학(Teleological Ethics)과 덕 윤리학(Virtue Ethics)의 영원한 원형입니다. 아리스토텔레스는 인간의 모든 행위, 기술(Techne), 탐구(Methodos)는 궁극적으로 어떤 '좋음(Agathon)'을 목적으로 추구하며, 다른 모든 목적들의 수단이 아닌 오직 그 자체로서 추구되는 인간 삶의 궁극적 최고선을 **에우다이모니아(Eudaimonia, 행복 / 완전한 번영)**라고 선언했습니다.

아리스토텔레스 윤리학의 핵심 테제는 다음과 같습니다:
1. **에우다이모니아의 본질**: 행복은 수동적인 감각적 쾌락(Hedone)이나 대중의 인정인 명예(Time), 물질적 부(Ploutos)가 아니라, **'탁월성(Arete, 덕)에 부합하는 영혼의 능동적 활동'**입니다.
2. **도덕적 덕(Ethike Arete)과 중용(Mesotes, $\mu\epsilon\sigma\acute{o}\tau\eta\varsigma$)**: 도덕적 덕은 이성적 원리에 따라 감정과 행위에서 **과도(Hyperbole)**와 **결핍(Elleipsis)**이라는 양극단의 악덕을 피하고, 우리와의 관계에서 **중용(Mesotes)**을 선택하는 품성상태(Hexis)입니다.
3. **습관화(Ethismos, $\epsilon\theta\iota\sigma\mu\acute{o}\varsigma$)**: 인간은 태어날 때부터 유덕한 것이 아니라, 중용에 맞는 올바른 행동을 반복적으로 실천함으로써 내재적 성품을 훈련하고 습관화합니다.
4. **자발성(Hekousion)과 비자발성(Akousion)**: 물리적 외력에 의해 강제되었거나(Bia) 개별적 행위 상황에 대한 무지(Agnoia)로 인해 일어난 행위는 비자발적이므로 도덕적 책임과 칭찬/비난의 대상에서 제외됩니다.
5. **도덕적 행위자의 4대 심리 위계**:
   - **유덕한 자(Sophron)**: 이성과 욕망이 완전히 일치하여 갈등 없이 자연스럽게 중용을 행하고 기쁨을 느끼는 최고 상태.
   - **자제력 있는 자(Enkrates)**: 나쁜 욕망을 느끼지만 강력한 의지력으로 정념을 제어하여 중용을 지켜내는 상태.
   - **자제력 없는 자 / 의지의 나약함(Akrates / Akrasia)**: 무엇이 선인지 알면서도 순간적인 정념과 쾌락에 굴복하여 중용을 벗어나며, 사후에 뼈아픈 후회와 가책을 느끼는 상태.
   - **방종하고 사악한 자(Akolastos)**: 이성이 완전히 마비/왜곡되어 악을 선으로 믿고 중용을 파괴하며 일말의 후회조차 없는 타락 상태.

본 과제에서는 아리스토텔레스의 『니코마코스 윤리학』 전 10권의 정수를 수리적으로 완벽히 모델링하여, 행위자의 개별 행위들을 평가하고, 습관화에 따른 성품 전이를 추적하며, 행위자의 궁극적 에우다이모니아 지수와 삶의 양식을 판정하는 **Aristotle Ethics & Eudaimonia Engine**을 구현합니다.

---

## 8대 기본 덕목과 중용 3분법 체계

| 덕목 (Virtue) | 결핍 (Deficiency, $x < 35$) | 중용 (Mean, $35 \le x \le 65$) | 과도 (Excess, $x > 65$) |
|:---:|:---:|:---:|:---:|
| **용기 (COURAGE)** | 비겁 (Cowardice / Deilia) | **용기 (Andreia)** | 만용·무모 (Rashness / Thrasytes) |
| **절제 (TEMPERANCE)** | 무감각 (Insensibility / Anaisthesia) | **절제 (Sophrosyne)** | 방종 (Self-Indulgence / Akolasia) |
| **관대함 (GENEROSITY)** | 인색 (Stinginess / Aneleutheria) | **관대함 (Eleutheriotes)** | 낭비 (Prodigality / Asotia) |
| **호탕함·긍지 (MAGNANIMITY)** | 비굴·소심 (Pusillanimity / Mikropsychia) | **긍지 (Megalopsychia)** | 허영 (Vanity / Chaunotes) |
| **온유함 (MILDNESS)** | 유약·무기력 (Spiritlessness / Aorgesia) | **온유함 (Praotes)** | 분노·격노 (Irascibility / Orgylotes) |
| **진실함 (TRUTHFULNESS)** | 자기비하·반어 (Self-Deprecation / Eironeia) | **진실함 (Aletheia)** | 허풍·과장 (Boastfulness / Alazoneia) |
| **재치 (WITTINESS)** | 촌스러움 (Boorishness / Agroikia) | **재치 (Eutrapelia)** | 익살·경박 (Buffoonery / Bomolochia) |
| **친애 (FRIENDLINESS)** | 까다로움·호전성 (Quarrelsomeness / Dyseris) | **친애 (Philia)** | 아첨 (Flattery / Areskeia) |

---

## 핵심 계산 및 전이 규칙

1. **중용 상태 판정**:
   - 행위 값 $x$에 대해, $x < 35$이면 `DEFICIENCY`, $35 \le x \le 65$이면 `MEAN`, $x > 65$이면 `EXCESS`로 판정합니다.
2. **자발성(Voluntariness) 판정**:
   - `compelled_by_force = true` (물리적 강제) 또는 `ignorant_of_circumstance = true` (상황에 대한 무지)인 경우 `is_voluntary = false` (비자발적)입니다.
3. **도덕적 행위자 상태(Moral State) 판정**:
   - 비자발적 행위(`is_voluntary = false`): 무조건 `INVOLUNTARY`.
   - 자발적 행위 중 `mean_state == "MEAN"`인 경우:
     - `appetite_intensity <= 30`: 욕망과 이성이 조화로우므로 `VIRTUOUS` (Sophron).
     - `appetite_intensity > 30`:
       - `willpower_resolve >= appetite_intensity`: 의지력으로 유혹을 극복했으므로 `CONTINENT` (Enkrates).
       - `willpower_resolve < appetite_intensity`: 욕망에 흔들렸으므로 `INCONTINENT` (Akrates).
   - 자발적 행위 중 `mean_state != "MEAN"` (중용 일탈)인 경우:
     - `reason_knows_good = true`이고 `has_remorse = true`: 선을 알면서도 정념에 굴복하고 후회하므로 `INCONTINENT` (Akrasia).
     - `reason_knows_good = false`이거나 `has_remorse = false`: 이성이 부패하였거나 후회가 없으므로 `VICIOUS` (Akolastos).
4. **습관화(Ethismos) 전이**:
   - 자발적 행위인 경우에만 해당 덕목의 성품 습관치 $H_v$를 갱신합니다:
     $$H_{v, t+1} = \text{round}(H_{v, t} + \alpha \cdot (x_t - H_{v, t}), 2)$$
   - 비자발적 행위는 성품에 영향을 주지 않으므로 $H_v$가 변하지 않습니다.
5. **에우다이모니아 종합 점수 및 삶의 판정**:
   - 성품 왜곡 페널티: $\text{habit\_penalty} = \frac{1}{8} \sum_{v} |H_v - 50.0|$
   - 행위 탁월성 비율:
     $$\text{virtue\_ratio} = \frac{1.0 \cdot N_{\text{virtuous}} + 0.75 \cdot N_{\text{continent}} - 0.5 \cdot N_{\text{akrasia}} - 1.0 \cdot N_{\text{vicious}}}{N_{\text{total}}}$$
     (단, $N_{\text{total}} = 0$이면 $\text{virtue\_ratio} = 1.0$)
   - 에우다이모니아 행복 점수 ($0.00 \le E \le 100.00$):
     $$E = \text{round}(\max(0.0, \min(100.0, 50.0 + 40.0 \cdot \text{virtue\_ratio} - 0.5 \cdot \text{habit\_penalty})), 2)$$
   - 삶의 최종 평가 (`life_verdict`):
     - $E \ge 80.0$: `EUDAIMON_LIFE` (완전한 탁월성에 도달한 최고의 번영)
     - $50.0 \le E < 80.0$: `CONTINENT_STRUGGLE_LIFE` (욕망과 분투하며 중용을 지킨 삶)
     - $30.0 \le E < 50.0$: `AKRATIC_ERRATIC_LIFE` (의지의 나약함과 후회가 반복된 삶)
     - $E < 30.0$: `VICIOUS_DEBASED_LIFE` (이성이 타락하고 중용을 상실한 파멸의 삶)

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 전달됩니다:
```json
{
  "agent_id": "Aristotle_Disciple",
  "habituation_rate": 0.2,
  "initial_habits": {
    "COURAGE": 40.0,
    "TEMPERANCE": 50.0,
    "GENEROSITY": 30.0
  },
  "actions": [
    {
      "id": "ACT_01",
      "virtue": "COURAGE",
      "action_value": 52.0,
      "reason_knows_good": true,
      "appetite_intensity": 20.0,
      "willpower_resolve": 80.0,
      "has_remorse": false
    },
    {
      "id": "ACT_02",
      "virtue": "TEMPERANCE",
      "action_value": 85.0,
      "reason_knows_good": true,
      "appetite_intensity": 90.0,
      "willpower_resolve": 30.0,
      "has_remorse": true
    },
    {
      "id": "ACT_03",
      "virtue": "GENEROSITY",
      "action_value": 10.0,
      "reason_knows_good": false,
      "has_remorse": false
    },
    {
      "id": "ACT_04",
      "virtue": "COURAGE",
      "action_value": 10.0,
      "compelled_by_force": true
    }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 공백 없는 압축 JSON(`separators=(',', ':')`, `ensure_ascii=False`)을 출력합니다:
```json
{
  "agent_id": "Aristotle_Disciple",
  "final_habits": {
    "COURAGE": 42.4,
    "TEMPERANCE": 57.0,
    "GENEROSITY": 26.0,
    "MAGNANIMITY": 50.0,
    "MILDNESS": 50.0,
    "TRUTHFULNESS": 50.0,
    "WITTINESS": 50.0,
    "FRIENDLINESS": 50.0
  },
  "action_evaluations": [
    {
      "action_id": "ACT_01",
      "virtue": "COURAGE",
      "mean_state": "MEAN",
      "classification": "Andreia",
      "moral_state": "VIRTUOUS",
      "is_voluntary": true,
      "updated_habit": 42.4
    },
    {
      "action_id": "ACT_02",
      "virtue": "TEMPERANCE",
      "mean_state": "EXCESS",
      "classification": "Self-Indulgence (Akolasia)",
      "moral_state": "INCONTINENT",
      "is_voluntary": true,
      "updated_habit": 57.0
    },
    {
      "action_id": "ACT_03",
      "virtue": "GENEROSITY",
      "mean_state": "DEFICIENCY",
      "classification": "Stinginess (Aneleutheria)",
      "moral_state": "VICIOUS",
      "is_voluntary": true,
      "updated_habit": 26.0
    },
    {
      "action_id": "ACT_04",
      "virtue": "COURAGE",
      "mean_state": "DEFICIENCY",
      "classification": "Cowardice (Deilia)",
      "moral_state": "INVOLUNTARY",
      "is_voluntary": false,
      "updated_habit": 42.4
    }
  ],
  "summary_counts": {
    "total_actions": 4,
    "virtuous_count": 1,
    "continent_count": 0,
    "akrasia_count": 1,
    "vicious_count": 1,
    "involuntary_count": 1
  },
  "habit_mean_deviation": 4.83,
  "eudaimonia_score": 42.59,
  "life_verdict": "AKRATIC_ERRATIC_LIFE"
}
```

---

## 제약 사항

- $1 \le \text{len}(actions) \le 100$
- $0.01 \le \text{habituation\_rate} \le 1.0$
- 모든 수치 필드는 $0.0 \le x \le 100.0$ 범위의 실수
- 덕목은 8대 공인 덕목(`COURAGE`, `TEMPERANCE`, `GENEROSITY`, `MAGNANIMITY`, `MILDNESS`, `TRUTHFULNESS`, `WITTINESS`, `FRIENDLINESS`) 중 하나로 주어집니다.
