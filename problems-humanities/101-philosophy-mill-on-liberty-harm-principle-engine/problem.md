# 존 스튜어트 밀의 자유론: 위해 원칙(Harm Principle), 사상·토론의 자유 및 다수의 횡포(Tyranny of the Majority) 방어 엔진

> *"인간 사회가 구성원 개인의 행동의 자유를 침해할 수 있는 유일한 정당한 근거는 **'타인에게 가해지는 위해(Harm to others)를 방지하는 것'**뿐이다. 당사자 자신의 물리적·도덕적 행복은 간섭의 충분한 근거가 되지 못한다."*  
> — 존 스튜어트 밀(John Stuart Mill), 『자유론(On Liberty)』 (1859) 제1장

---

## 1. 개요 및 사상사적 배경

19세기 중엽 대의민주주의와 대중 사회가 정착되면서 인류는 새로운 형태의 억압에 직면했습니다. 군주나 폭군의 물리적 압제뿐만 아니라, **'사회 대중의 다수가 지배적인 여론과 관습을 앞세워 이질적인 소수를 억압하는 다수의 횡포(Tyranny of the Majority)'**가 개인의 정신을 질식시키기 시작한 것입니다.

영국의 사상가 존 스튜어트 밀(John Stuart Mill, 1806–1873)은 1859년 발표한 불후의 고전 『자유론(On Liberty)』을 통해 근대 자유민주주의의 대헌장이자 인류 지성사의 영원한 이정표를 세웠습니다:

1. **위해 원칙 (The Harm Principle)**:
   - 국가 권력이나 사회 여론이 개인의 자유를 강제적으로 제한할 수 있는 유일한 기준은 오직 **'타인에게 실질적인 피해를 입히는 것을 막는 경우'**뿐입니다.
   - 개인 자신의 신체적·도덕적 이익(자기 자신에 대한 위해, Self-harm)을 위한다는 명분으로 국가가 개입하는 온정주의적 간섭(Paternalism)은 결코 정당화될 수 없습니다.
   - **"자기 자신에 대하여, 즉 자신의 신체와 정신에 대하여 개인은 주권자이다(Over himself, over his own body and mind, the individual is sovereign)."**

2. **사상과 토론의 절대적 자유 4대 논거**:
   - **논거 1 (침묵당한 의견이 참인 경우)**: 권력이 금지한 소수 의견이 진리일 수 있습니다. 인간은 무오류(Infallible)가 아니므로, 다른 의견을 탄압하는 것은 미래 세대로부터 진리를 발견할 기회를 강탈하는 범죄입니다 (예: 소크라테스, 예수, 갈릴레오의 재판).
   - **논거 2 (침묵당한 의견이 거짓인 경우)**: 비록 대중의 의견이 절대적 진리라 할지라도, 격렬한 반대 의견과의 치열한 논쟁을 거치지 않으면 그 진리는 생명력을 잃고 맹목적인 **'죽은 독단(Dead Dogma)'**으로 전락합니다.
   - **논거 3 (의견이 부분적 진리인 경우)**: 현실의 대부분의 상충하는 의견들은 각자 진리의 일면만을 담고 있습니다(Partial Truths). 진보와 보수처럼, 자유로운 대립과 변증법적 종합을 통해서만 완전한 진리에 다가설 수 있습니다.
   - **논거 4 (신념의 활력과 실천력)**: 반론을 통해 스스로 방어해보지 않은 교리는 사람들의 마음속에 진정한 도덕적 감화력을 미치지 못하고 공허한 껍데기 구호로 굳어집니다.

3. **개별성(Individuality)과 삶의 실험(Experiments in Living)**:
   - 인류 문명의 진보는 관습과 전통의 맹목적 추종에서 나오는 것이 아니라, 남들과 다른 독창적인 삶의 방식을 시도하는 **'개별성'**과 **'삶의 실험'**에서 태어납니다.
   - 밀은 모든 사람이 똑같은 옷을 입고 똑같은 생각을 하도록 강요당한 결과 천년 동안 문명이 정체된 중국(Chinese Stationariness)을 경고하며, 다양성과 독창성의 보존이야말로 사회 진보의 원동력임을 역설했습니다.

4. **행위의 한계와 곡물상(Corn-Dealer) 선동의 알레고리**:
   - 순수한 사상과 출판의 자유는 무제한적이지만, 타인에게 급박하고 직접적인 물리적 위해를 가하는 폭력 선동(Incitement)은 표현의 자유로 보호받을 수 없습니다.
   - "곡물상이 가난한 자들을 굶겨 죽이고 있다"는 의견을 신문에 기고하는 것은 자유이나, 곡물상의 집 앞에 모인 흥분한 군중을 향해 그 말을 외치며 방화를 유도하는 행위는 처벌 대상입니다.

본 과제에서는 밀의 『자유론』에 기반하여, 다양한 개인 행위와 의견 표현, 사회적 동조 압력 및 온정주의 성향을 입력받아 위해 원칙 적용, 다수의 횡포 차단, 사상과 토론의 활력 및 문명 체제 진단을 수행하는 **밀 자유론 위해 원칙 시뮬레이션 엔진**을 구축합니다.

---

## 2. 시스템 아키텍처 및 철학적 판정 모델

```
+-------------------------------------------------------------------------+
|                  사회적 풍토 (Social Climate)                            |
|     동조 압력 (conformity_pressure)  |  온정주의 편향 (paternalism_bias)    |
+-------------------------------------------------------------------------+
                                   |
                                   v
+-------------------------------------------------------------------------+
|            개인 행위 및 발언 스트림 (Individual Actions)                 |
|   action_id, agent, action_type, harm_severity_to_others,               |
|   offense_or_dislike_level, is_opinion_or_debate, truth_veracity        |
+-------------------------------------------------------------------------+
                                   |
                                   v
+-------------------------------------------------------------------------+
| [1단계] 위해 원칙 (Harm Principle) 판정                                  |
|   · 타인 위해(harm_others) >= 0.5:                                      |
|       -> COERCIVE_INTERVENTION_JUSTIFIED (자유 제한 / 공권력 개입)       |
|   · 타인 위해 < 0.2 AND 단순 불쾌감(offense) >= 0.4 AND                 |
|     (동조 압력 >= 0.5 OR 온정주의 >= 0.4):                               |
|       -> TYRANNY_OF_MAJORITY_BLOCKED (다수의 횡포 차단 / 자유 보호)      |
|   · 기타:                                                               |
|       -> INDIVIDUAL_SOVEREIGNTY_PROTECTED (자기 주권 / 절대적 자유)      |
+-------------------------------------------------------------------------+
                                   |
                                   v
+-------------------------------------------------------------------------+
| [2단계] 사상과 토론의 인식론적 활력 분석 (Epistemic Vitality)           |
|   (is_opinion_or_debate == True AND 자유가 제한되지 않은 경우)          |
|   · truth_veracity == "TRUE":                                           |
|       -> DISSENTIENT_TRUTH_REVEALED (새로운 진리의 개시, 활력 +1.0)     |
|   · truth_veracity == "PARTIAL_TRUTH":                                  |
|       -> DIALECTICAL_SYNTHESIS_REFINED (변증법적 종합, 활력 +0.75)       |
|   · truth_veracity == "FALSE":                                          |
|       -> LIVING_TRUTH_PRESERVED_OVER_DEAD_DOGMA (독단 방지, 활력 +0.5)   |
|   (자유가 제한된 선동의 경우: SPEECH_RESTRICTED_DUE_TO_CLEAR_AND_PRESENT_HARM)|
+-------------------------------------------------------------------------+
                                   |
                                   v
+-------------------------------------------------------------------------+
| [3단계] 개별성 기여도 및 문명 체제 진단 (Civilization Health)            |
|   · 개별성 기여: round(max(0.1, 1.0 - (conformity_pressure * 0.5)), 4)  |
|   · 사회 진보 지수: (누적 진리 활력 * 0.5) + (누적 개별성 * 0.5)         |
|   · 문명 체제 분류:                                                     |
|       - 자유 보존율 >= 80% AND 진보 지수 >= 3.0: FLOURISHING_FREE_SOCIETY|
|       - 동조 압력 >= 0.7 AND 다수의 횡포 차단 == 0:                       |
|           STAGNANT_CHINESE_STATIONARY_MODEL (정체된 중국식 획일 체제)    |
|       - 개입 수 > 보호 수: COERCIVE_DISCIPLINARY_REGIME                  |
|       - 기타: CONTESTED_LIBERAL_TRANSITION                              |
+-------------------------------------------------------------------------+
```

---

## 3. 세부 판정 알고리즘 및 규칙 명세

### 3.1 1단계: 위해 원칙 (Harm Principle) 검증
각 행위(`individual_actions`)에 대해:
- `harm_severity_to_others` ($H \in [0.0, 1.0]$): 타인의 신체, 자유, 재산에 가해지는 실질적 피해 강도.
- `offense_or_dislike_level` ($O \in [0.0, 1.0]$): 사회 대중의 단순한 감정적 불쾌감, 도덕적 혐오, 종교적 반감.
- 판정 규칙:
  1. $H \ge 0.5$:
     - `ruling: "COERCIVE_INTERVENTION_JUSTIFIED"`
     - `liberty_status: "RESTRICTED"`
     - `justification: "Direct and substantial harm to others detected"`
  2. $H < 0.2$ 이고 $O \ge 0.4$ 이며 ($	ext{conformity\_pressure} \ge 0.5$ 또는 $	ext{paternalism\_bias} \ge 0.4$):
     - `ruling: "TYRANNY_OF_MAJORITY_BLOCKED"`
     - `liberty_status: "PROTECTED_AGAINST_SOCIAL_TYRANNY"`
     - `justification: "Dislike or moral aversion without other-harm cannot justify suppression"`
  3. 그 외:
     - `ruling: "INDIVIDUAL_SOVEREIGNTY_PROTECTED"`
     - `liberty_status: "SOVEREIGN_LIBERTY"`
     - `justification: "Self-regarding action or harmless diversity of lifestyle"`

### 3.2 2단계: 사상과 토론의 활력 (`epistemic_verdict`)
- `is_opinion_or_debate == true`이고 `liberty_status != "RESTRICTED"`인 경우:
  - `truth_veracity == "TRUE"`: `"DISSENTIENT_TRUTH_REVEALED"` (활력 이득 $+1.0$)
  - `truth_veracity == "PARTIAL_TRUTH"`: `"DIALECTICAL_SYNTHESIS_REFINED"` (활력 이득 $+0.75$)
  - `truth_veracity == "FALSE"`: `"LIVING_TRUTH_PRESERVED_OVER_DEAD_DOGMA"` (활력 이득 $+0.5$)
- `is_opinion_or_debate == true`이고 `liberty_status == "RESTRICTED"`인 경우:
  - `"SPEECH_RESTRICTED_DUE_TO_CLEAR_AND_PRESENT_HARM"` (활력 이득 $+0.0$)
- 토론이 아닌 경우 (`is_opinion_or_debate == false`): `"NOT_APPLICABLE"`

### 3.3 3단계: 개별성 및 사회 진보 지수 산출
- 자유가 보호된 행위(`PROTECTED_AGAINST_SOCIAL_TYRANNY`, `SOVEREIGN_LIBERTY`)의 경우:
  $$	ext{individuality\_contribution} = 	ext{round}\left(\max\left(0.1, \ 1.0 - (	ext{conformity\_pressure} 	imes 0.5)ight), \ 4ight)$$
- 자유가 제한된 경우 기여도는 `0.0`입니다.
- 누적 총계:
  - $	ext{accumulated\_truth\_vitality} = \sum 	ext{vitality\_gain}$
  - $	ext{accumulated\_individuality} = \sum 	ext{individuality\_contribution}$
  - $	ext{social\_progress\_index} = 	ext{round}\left((	ext{accumulated\_truth\_vitality} 	imes 0.5) + (	ext{accumulated\_individuality} 	imes 0.5), \ 4ight)$
  - $	ext{liberty\_preservation\_rate\_pct} = 	ext{round}\left(rac{	ext{protected\_liberties}}{	ext{total\_actions}} 	imes 100.0, \ 2ight)$

### 3.4 문명 체제 레짐 판정 (`civilization_regime`)
1. $	ext{liberty\_preservation\_rate\_pct} \ge 80.0$ 이고 $	ext{social\_progress\_index} \ge 3.0$:
   - `"FLOURISHING_FREE_SOCIETY"` (만개하는 자유롭고 역동적인 개방 사회)
2. $	ext{conformity\_pressure} \ge 0.7$ 이고 $	ext{tyranny\_of\_majority\_blocked} == 0$:
   - `"STAGNANT_CHINESE_STATIONARY_MODEL"` (획일적 관습에 질식된 정체 체제)
3. $	ext{justified\_interventions} > 	ext{protected\_liberties}$:
   - `"COERCIVE_DISCIPLINARY_REGIME"` (강제적 억압 체제)
4. 그 외:
   - `"CONTESTED_LIBERAL_TRANSITION"` (자유주의적 각축 및 전환기 사회)

---

## 4. 입출력 형식 및 제약 조건

### 입력 형식 (JSON)
```json
{
  "social_climate": {
    "conformity_pressure": 0.85,
    "paternalism_bias": 0.70
  },
  "individual_actions": [
    {
      "action_id": "ACT_HELIOCENTRISM",
      "agent": "Galileo_Galilei",
      "action_type": "EXPRESSION_DISSENT",
      "harm_severity_to_others": 0.0,
      "offense_or_dislike_level": 0.95,
      "is_opinion_or_debate": true,
      "truth_veracity": "TRUE"
    }
  ]
}
```

### 출력 형식 (JSON)
```json
{
  "harm_principle_summary": {
    "total_actions": 1,
    "protected_liberties": 1,
    "justified_interventions": 0,
    "tyranny_of_majority_blocked": 1,
    "liberty_preservation_rate_pct": 100.0
  },
  "epistemic_and_individual_vitality": {
    "accumulated_truth_vitality": 1.0,
    "accumulated_individuality": 0.575,
    "social_progress_index": 0.7875,
    "civilization_regime": "CONTESTED_LIBERAL_TRANSITION"
  },
  "action_evaluations": [
    {
      "action_id": "ACT_HELIOCENTRISM",
      "agent": "Galileo_Galilei",
      "action_type": "EXPRESSION_DISSENT",
      "harm_to_others": 0.0,
      "offense_level": 0.95,
      "ruling": "TYRANNY_OF_MAJORITY_BLOCKED",
      "liberty_status": "PROTECTED_AGAINST_SOCIAL_TYRANNY",
      "epistemic_verdict": "DISSENTIENT_TRUTH_REVEALED",
      "individuality_contribution": 0.575,
      "justification": "Dislike or moral aversion without other-harm cannot justify suppression"
    }
  ]
}
```

### 제약 조건
- $0.0 \le \text{conformity\_pressure}, \text{paternalism\_bias} \le 1.0$
- $1 \le \text{len(individual\_actions)} \le 100$
- $0.0 \le \text{harm\_severity\_to\_others}, \text{offense\_or\_dislike\_level} \le 1.0$
- 모든 부동소수점 연산은 소수점 4자리 또는 백분율 2자리로 엄격히 반올림(`round`)되어야 합니다.
