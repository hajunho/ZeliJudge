# 장 폴 사르트르의 존재와 무: 즉자존재와 대자존재, 자기기만(Mauvaise Foi) 및 타자의 시선(Le Regard) 엔진

## 문제 설명

20세기 프랑스 실존주의의 기수 장 폴 사르트르(Jean-Paul Sartre)는 1943년 주저 **『존재와 무(L'Être et le Néant)』**에서 인간 의식의 이중적 구조와 자유의 급진적 본질을 해명했습니다.

사르트르는 세계의 존재를 두 가지 근본 범주로 구분합니다:
1. **즉자존재 (Être-en-soi, In-itself)**: 바위나 책상처럼 스스로 충족되어 있으며, 어떠한 결여나 틈도 없이 자기 자신과 완전히 일치하는 불투명하고 빽빽한 사물의 존재 방식.
2. **대자존재 (Être-pour-soi, For-itself)**: 인간의 의식처럼 자기 자신과 결코 일치할 수 없으며, 끊임없이 자신 속에 '무(Néant)'를 도입하여 현재의 상태를 부정하고(무화, *Néantisation*) 미래의 가능성을 향해 스스로를 내던지는(기투, *Projet*) 존재 방식.

인간 실존은 결코 벗어날 수 없는 **사실성(Facticity)**(출생, 신체 조건, 과거 행적, 사회적 상황)과 그것을 뚫고 미래를 선택하는 **초월성(Transcendence)** 사이의 영원한 긴장 속에 놓여 있습니다. 사르트르는 이 실존적 긴장에서 비롯되는 핵심 현상들을 정식화했습니다:

1. **자기기만 (Mauvaise Foi, Bad Faith)**:
   인간은 절대적으로 자유롭기 때문에 자신의 선택에 대해 무한한 책임을 져야 하며, 이로 인해 극심한 **실존적 불안(Angoisse)**을 겪습니다. 자기기만은 이 불안으로부터 도피하기 위해 스스로를 속이는 의식의 기교입니다:
   - **유형 A (사물화/역할극)**: 초월성을 사실성으로 축소시키는 기만. 카페 웨이터가 손동작을 기계처럼 과장하며 "나는 어쩔 수 없는 웨이터일 뿐이다"라고 자신을 사물(즉자)로 동일시하는 것.
   - **유형 B (사실성 부인/순수 초월)**: 사실성을 부정하고 자신을 순수한 잠재력으로 도피시키는 기만. "과거의 비겁한 행동은 진정한 내가 아니다"라며 과거의 구체적 책임을 지우는 것.
2. **타자의 시선 (Le Regard, The Look)**:
   열쇠 구멍을 통해 방 안을 엿보던 주체가 등 뒤에서 들려오는 발자국 소리에 놀라 돌아보는 순간, 나는 더 이상 세계를 조직하는 전능한 '주체'가 아니라 타자의 시선에 포착되어 굳어버린 '대상(객체)'으로 전락합니다.
   - 나의 세계는 타자라는 블랙홀을 향해 통제를 잃고 쏟아져 나가며(**세계의 유출, Hémorragie du monde**),
   - 주체는 자신의 객체성을 자각하며 원초적인 **부끄러움(Honte)**을 느끼게 됩니다(**대타존재, Être-pour-autrui**).
3. **근본적 자유 (Liberté Radicale)**:
   "인간은 자유롭도록 선고받았다(L'homme est condamné à être libre)." 어떠한 신이나 본성, 결정론적 핑계도 인간의 선택을 대신할 수 없습니다. 자기기만을 걷어내고 불안 속에서 자신의 행동을 전적으로 책임질 때 비로소 **본래적 자유(Authentic Freedom)**가 열립니다.

본 문제에서는 사르트르의 『존재와 무』 실존론적 존재론을 모델링한 **사르트르 실존 역학 엔진**을 구현해야 합니다.

---

## 시스템 아키텍처 및 실존 존재론 도식

```
+---------------------------------------------------------------------------------------------------+
|               Jean-Paul Sartre: Being and Nothingness (L'Être et le Néant) Engine                 |
+---------------------------------------------------------------------------------------------------+

     [ Facticity: The Unalterable Given ]             [ Transcendence: Freedom & Nihilation ]
     +----------------------------------+             +-------------------------------------+
     | Facticity List: {f_1, ..., f_k}  |             | Freedom Projection: Proj [0..1]     |
     | Weights: w(f_i) [0..1]           |             | Nihilation Capacity: Nih [0..1]     |
     | F_total = avg(w(f_i))            |             | T_total = min(1.0, Proj*(1+0.5*Nih))|
     +----------------------------------+             +-------------------------------------+
                      |                                                  |
                      +-------------------+   +--------------------------+
                                          |   |
                                          v   v
     [ Bad Faith (Mauvaise Foi) Mechanics ]
     - Mode A (Thingification / Role):   BF_A = max(0, F - T) * role_rigidity
     - Mode B (Facticity Disavowal):     BF_B = max(0, T - F) * commitment_denial
     - Total Bad Faith:                  BadFaith = min(1.0, BF_A + BF_B)
                                          |
                                          v
     [ Intersubjective Gaze: The Look of the Other (Le Regard) ]
     - Gaze Intensity: G [0..1] (if other_present else 0.0)
     - World Hemorrhage: Hem = G * (1.0 - defensiveness)
     - Objectification:  Obj = G * F_total
     - Shame Index:      Shame = Obj * (1.0 - 0.5 * BadFaith)
                                          |
                                          v
     [ Radical Freedom & Anguish (Angoisse) ]
     - Anguish = T_total * (1.0 - BadFaith)
     - Authentic Choice Capacity = max(0, 1.0 - BadFaith)
                                          |
                                          v
     [ Existential Regimes ]
     - MAUVAISE_FOI           : BadFaith >= 0.50
     - LE_REGARD_OBJECTIFIED  : G >= 0.60 and Obj >= 0.45
     - AUTHENTIC_FREEDOM      : Anguish >= 0.50 and BadFaith < 0.35
     - EN_SOI_POUR_SOI_TENSION: All other everyday existential balances
```

---

## 수리 및 존재론적 계산 공식

### 1. 사실성(Facticity)과 초월성(Transcendence) 정량화
- 사실성 요소 목록이 주어질 때 총 사실성 지수:
  $$F_{\text{total}} = \frac{1}{K} \sum_{i=1}^K w(f_i)$$
- 자유의 투사와 무화 능력이 결합된 총 초월성 지수:
  $$T_{\text{total}} = \min(1.0, \text{freedom\_projection} \times (1.0 + 0.5 \times \text{nihilation\_capacity}))$$

### 2. 자기기만(Mauvaise Foi) 2대 양식
- **유형 A (사물화/역할극)**: 초월성을 사실성에 종속시키는 역할 집착:
  $$\text{BF}_A = \max(0.0, F_{\text{total}} - T_{\text{total}}) \times \text{role\_rigidity}$$
- **유형 B (사실성 부인/허위 초월)**: 과거의 구체적 사실성을 부인하는 도피:
  $$\text{BF}_B = \max(0.0, T_{\text{total}} - F_{\text{total}}) \times \text{commitment\_denial}$$
- 총 자기기만 지수:
  $$\text{BadFaith} = \min(1.0, \text{BF}_A + \text{BF}_B)$$

### 3. 타자의 시선(Le Regard)과 부끄러움(Honte)
타자가 현존할 때(`other_present == True`):
- 시선 강도 $G = \text{gaze\_intensity}$ (부재 시 $G = 0.0$).
- 세계의 유출 지수:
  $$\text{Hemorrhage} = G \times (1.0 - \text{defensiveness})$$
- 대상화 지수(나의 신체와 상황이 타자의 객체로 응고됨):
  $$\text{Objectification} = G \times F_{\text{total}}$$
- 부끄러움 지수:
  $$\text{Shame} = \text{Objectification} \times (1.0 - 0.5 \times \text{BadFaith})$$

### 4. 실존적 불안(Angoisse)
변명 없는 자유의 직시에서 발생하는 불안:
$$\text{Anguish} = T_{\text{total}} \times (1.0 - \text{BadFaith})$$

### 5. 실존 레짐 4단계 판정
1. $\text{BadFaith} \ge 0.50$인 경우:
   $$\to \mathbf{MAUVAISE\_FOI} \quad (\text{자기기만: 고정된 역할극 또는 과거 부인에 숨은 자유 회피})$$
2. 그렇지 않고 $G \ge 0.60$ 이고 $\text{Objectification} \ge 0.45$인 경우:
   $$\to \mathbf{LE\_REGARD\_OBJECTIFIED} \quad (\text{타자의 시선에 포착됨: 대타존재로의 응고와 부끄러움})$$
3. 그렇지 않고 $\text{Anguish} \ge 0.50$ 이고 $\text{BadFaith} < 0.35$인 경우:
   $$\to \mathbf{AUTHENTIC\_FREEDOM} \quad (\text{본래적 자유: 변명 없는 불안의 인수와 결단적 기투})$$
4. 그 외의 모든 경우:
   $$\to \mathbf{EN\_SOI\_POUR\_SOI\_TENSION} \quad (\text{즉자와 대자의 일상적 실존적 긴장})$$

---

## 입력 형식

표준 입력(stdin)으로 다음 구조의 JSON 객체가 주어집니다:

```json
{
  "facticity": [
    {"name": "WaiterApron", "weight": 0.90},
    {"name": "EmploymentContract", "weight": 0.85}
  ],
  "transcendence": {
    "freedom_projection": 0.20,
    "nihilation_capacity": 0.10
  },
  "role_rigidity": 0.90,
  "commitment_denial": 0.0,
  "the_look": {
    "other_present": true,
    "gaze_intensity": 0.35,
    "defensiveness": 0.40
  }
}
```

---

## 출력 형식

표준 출력(stdout)으로 실존론적 구조, 타자의 시선 지표, 자유 지표, 최종 실존 레짐을 담은 JSON 객체를 공백 없는 압축 형식(`separators=(',', ':')`)으로 출력합니다:

```json
{
  "ontological_structure": {
    "facticity_score": 0.875,
    "transcendence_score": 0.21,
    "bad_faith_index": 0.5985,
    "bad_faith_components": {
      "role_thingification": 0.5985,
      "facticity_disavowal": 0.0
    }
  },
  "intersubjective_gaze_metrics": {
    "other_present": true,
    "gaze_intensity": 0.35,
    "world_hemorrhage": 0.21,
    "objectification_index": 0.3063,
    "shame_index": 0.2146
  },
  "existential_freedom": {
    "anguish_score": 0.0843,
    "authentic_choice_capacity": 0.4015
  },
  "existential_regime": "MAUVAISE_FOI"
}
```

(모든 수치는 소수점 4자리까지 반올림하여 표기합니다.)

---

## 제약 조건

- 사실성 항목 수: $1 \le |F| \le 100$
- 모든 가중치, 투사 계수, 시선 강도, 방어율: $[0.0, 1.0]$ 범위의 실수
- 표준 라이브러리만을 사용하여 순수 파이썬으로 구현해야 함
