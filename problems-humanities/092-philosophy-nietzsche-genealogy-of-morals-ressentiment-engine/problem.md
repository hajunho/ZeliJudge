# 프리드리히 니체의 도덕의 계통학: 주인 도덕 대 노예 도덕, 르상티망(Ressentiment) 및 양심의 가책 엔진

## 문제 설명

19세기 말 서양 철학의 망치를 든 사상가 프리드리히 니체(Friedrich Nietzsche)는 1887년 주저 **『도덕의 계통학(Zur Genealogie der Moral)』**에서 도덕적 가치들의 기원과 발생사를 폭로했습니다. 니체는 전통 철학자들이 "선(Good)"과 "악(Evil)"이라는 도덕적 가치를 영원불변한 보편 진리로 간주해 온 것을 비판하며, 도덕이란 특정한 역사적 권력 투쟁과 심리적 원한에서 탄생한 인위적 발명품임을 계통학적(Genealogical)으로 해명했습니다.

니체의 도덕 계통학은 세 편의 논문을 통해 다음의 핵심 메커니즘을 규명합니다:

1. **'좋음과 나쁨' 대 '선과 악'의 두 가지 도덕 레짐**:
   - **주인/귀족 도덕 (Herrenmoral)**: 강력하고 고귀하며 행복한 자들이 스스로를 긍정하며 **"우리는 좋은 자들이다(Gut)"**라고 선언하는 데서 출발합니다. 천하고 가련한 자들을 향한 평가는 경멸 없는 단순한 비하인 **"나쁨(Schlecht)"**에 불과합니다.
   - **노예 도덕 (Sklavenmoral)**: 피억압자, 약자, 무력한 자들의 **원한(Ressentiment)**에서 출발합니다. 노예는 스스로를 긍정할 힘이 없으므로, 먼저 외부의 강자를 **"악(Böse)"**으로 규정하여 저주한 뒤, 그 반대급부로 자신들의 무력함과 비겁함을 **"선(Gut)"**(온유함, 겸손, 인내)으로 미화합니다. 이를 **도덕에서의 노예 반란(Slave Revolt in Morality)**이라 부릅니다.
2. **부채(Schulden)에서 죄(Schuld)로, 그리고 양심의 가책(Schlechtes Gewissen)**:
   - 독일어에서 '죄(Schuld)'의 기원은 도덕적 참회가 아니라 채권자와 채무자 사이의 물질적 '부채(Schulden)' 관계에서 비롯되었습니다.
   - 고대 공동체에서 빚을 갚지 못한 채무자의 신체를 훼손하던 잔혹한 가학 본능은, 국가와 문명의 형성으로 폭력이 금지되자 외부로 발산되지 못하고 인간 **자신의 내면을 향해 돌아서서 스스로를 물어뜯는 고문**으로 전락했습니다. 이것이 바로 **'양심의 가책'**의 기원입니다.
3. **금욕주의적 사제 (The Ascetic Priest)**:
   - 사제는 고통받는 무력한 대중의 르상티망을 "너의 고통은 남 때문이 아니라, 바로 너 자신의 죄 때문이다!"라며 내면화시켜 스스로를 향한 죄의식으로 조직하고 통제합니다.

본 문제에서는 니체의 『도덕의 계통학』을 모델링한 **니체 도덕 계통학 및 르상티망 역학 엔진**을 구현해야 합니다.

---

## 시스템 아키텍처 및 계통학 도식

```
+---------------------------------------------------------------------------------------------------+
|               Friedrich Nietzsche: Genealogy of Morals (Zur Genealogie der Moral) Engine          |
+---------------------------------------------------------------------------------------------------+

     [ Master / Noble Group: Affirmative Vitality ]      [ Slave / Weak Group: Reactive Hostility ]
     +--------------------------------------------+      +----------------------------------------+
     | Vital Potency: V_noble [0..1]              |      | Powerlessness: W_slave [0..1]          |
     | Self-Affirmation: A_noble [0..1]           |      | Suffering: S_slave [0..1]              |
     | Action Primacy: P_act_noble [0..1]         |      | Reactive Hostility: H_slave [0..1]     |
     +--------------------------------------------+      | Action Primacy: P_act_slave [0..1]     |
                           |                             +----------------------------------------+
                           |                                                  |
                           v                                                  v
     [ Master Valuation: Active "Good vs Bad" ]          [ Ressentiment Dynamics & Slave Revolt ]
     - Primary Good:  Good_m = A_noble * V_noble         - Ressentiment:
     - Secondary Bad: Bad_m  = (1 - V_noble) * 0.5         R = H * W * (1 - P_act) * (1 + 0.5*S)
                                                         - Revolt Triggered: R >= 0.45
                                                                              |
                                                                              v
                                                         [ Slave Valuation: Reactive "Evil vs Good" ]
                                                         - Primary Evil:  Evil_s = R * V_noble
                                                         - Secondary Good: Good_s = W * (1 - 0.5*H)
                                                                              |
                                                         +--------------------+
                                                         |
                                                         v
     [ Guilt & Bad Conscience Mechanics ]
     - Contractual Debt: D [0..1]
     - Internalized Cruelty: C_int [0..1]
     - Ascetic Priest Manipulation: P_ascetic [0..1]
     - Bad Conscience: BC = C_int * D * (1.0 + P_ascetic)
                                                         |
                                                         v
     [ Moral Genealogical Regimes ]
     - SLAVE_MORALITY_TRIUMPH    : R >= 0.55 and BC >= 0.45
     - RESSENTIMENT_FERMENTATION : R >= 0.45
     - MASTER_NOBLE_AFFIRMATION  : A_noble >= 0.60 and R < 0.35
     - NIHILISTIC_TRANSITION     : All other value-vacuum transitional states
```

---

## 수리 및 계통학적 계산 공식

### 1. 르상티망(Ressentiment) 형성 공식
무력한 자들의 억압된 적개심($H$)과 직접적 행동 불능($1 - P_{\text{act}}$), 그리고 고통($S$)의 가중 결합으로 계산됩니다:
$$R = \min(1.0, H_{\text{slave}} \times W_{\text{slave}} \times (1.0 - P_{\text{act\_slave}}) \times (1.0 + 0.5 \times S_{\text{slave}}))$$
- $R \ge 0.45$이면 **도덕에서의 노예 반란(`slave_revolt_triggered`)**이 참으로 판정됩니다.

### 2. 귀족 도덕(좋음 대 나쁨)과 노예 도덕(악 대 선)의 대립적 가치화
- **귀족 도덕 (능동적 긍정 우선)**:
  $$\text{Good}_{\text{master}} = A_{\text{noble}} \times V_{\text{noble}}$$
  $$\text{Bad}_{\text{master}} = \max(0.0, 1.0 - V_{\text{noble}}) \times 0.5$$
- **노예 도덕 (반동적 부정 우선)**:
  $$\text{Evil}_{\text{slave}} = \min(1.0, R \times V_{\text{noble}})$$
  $$\text{Good}_{\text{slave}} = W_{\text{slave}} \times (1.0 - 0.5 \times H_{\text{slave}})$$

### 3. 부채(Schulden)와 양심의 가책(Schlechtes Gewissen)
- 계약적 부채($D$)와 문명화로 내면화된 잔혹성($C_{\text{int}}$), 그리고 이를 조장하는 금욕주의 사제의 영향력($P_{\text{ascetic}}$)의 결합:
  $$\text{BadConscience} = \min(1.0, C_{\text{int}} \times D \times (1.0 + P_{\text{ascetic}}))$$

### 4. 도덕 계통학 레짐 4단계 판정
1. $R \ge 0.55$ 이고 $\text{BadConscience} \ge 0.45$인 경우:
   $$\to \mathbf{SLAVE\_MORALITY\_TRIUMPH} \quad (\text{노예 도덕의 승리: 가치의 전도와 죄책감의 제도화})$$
2. 그렇지 않고 $R \ge 0.45$인 경우:
   $$\to \mathbf{RESSENTIMENT\_FERMENTATION} \quad (\text{르상티망의 발효와 도덕적 적개심 축적})$$
3. 그렇지 않고 $A_{\text{noble}} \ge 0.60$ 이고 $R < 0.35$인 경우:
   $$\to \mathbf{MASTER\_NOBLE\_AFFIRMATION} \quad (\text{귀족 도덕의 능동적 자기 긍정})$$
4. 그 외의 모든 경우:
   $$\to \mathbf{NIHILISTIC\_TRANSITION} \quad (\text{허무주의적 과도기 상태})$$

---

## 입력 형식

표준 입력(stdin)으로 다음 구조의 JSON 객체가 주어집니다:

```json
{
  "nobles": {
    "vital_potency": 0.95,
    "self_affirmation": 0.90,
    "action_primacy": 0.95
  },
  "slaves": {
    "powerlessness": 0.95,
    "suffering": 0.90,
    "reactive_hostility": 0.95,
    "action_primacy": 0.05
  },
  "guilt_mechanics": {
    "contractual_debt": 0.85,
    "internalized_cruelty": 0.80,
    "ascetic_priest_influence": 0.90
  }
}
```

---

## 출력 형식

표준 출력(stdout)으로 르상티망 지표, 대립 도덕 체계, 죄책감 지표, 최종 계통학 레짐을 담은 JSON 객체를 공백 없는 압축 형식(`separators=(',', ':')`)으로 출력합니다:

```json
{
  "ressentiment_metrics": {
    "ressentiment_score": 0.95,
    "slave_revolt_triggered": true,
    "reactive_hostility": 0.95,
    "powerlessness": 0.95
  },
  "valuation_systems": {
    "master_morality": {
      "mode": "GOOD_VS_BAD",
      "primary_good_affirmation": 0.855,
      "derivative_bad": 0.025
    },
    "slave_morality": {
      "mode": "EVIL_VS_GOOD",
      "primary_evil_imputation": 0.8075,
      "derivative_good_sanctification": 0.4988
    }
  },
  "guilt_and_conscience": {
    "contractual_debt": 0.85,
    "bad_conscience_index": 1.0,
    "ascetic_priest_influence": 0.9
  },
  "genealogical_regime": "SLAVE_MORALITY_TRIUMPH"
}
```

(모든 수치는 소수점 4자리까지 반올림하여 표기합니다.)

---

## 제약 조건

- 모든 수치 파라미터($V, A, P, W, S, H, D, C_{\text{int}}, P_{\text{ascetic}}$): $[0.0, 1.0]$ 범위의 실수
- 표준 라이브러리만을 사용하여 순수 파이썬으로 구현해야 함
