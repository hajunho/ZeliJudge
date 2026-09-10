# 바뤼흐 스피노자의 에티카: 실체일원론(Deus sive Natura), 코나투스(Conatus), 3대 인식 및 신에 대한 지적 사랑(Amor Dei Intellectualis) 엔진

## 문제 설명

1677년 사후 출간된 바뤼흐 스피노자(Baruch Spinoza, 1632~1677)의 대표작 『에티카(Ethica Ordine Geometrico Demonstrata, 기하학적 방식으로 증명된 윤리학)』는 서양 근대 합리론의 최고봉이자, 유클리드 기하학의 공리·정리 형식을 철학 체계에 도입한 불멸의 명저입니다. 스피노자는 데카르트의 심신 이원론(정신 실체 vs 물질 실체)을 단호히 거부하고, 우주에는 오직 스스로 존재하는 단 하나의 절대적이고 무한한 실체만이 존재하며, 그것이 곧 **'신 또는 자연(Deus sive Natura)'**이라는 혁명적인 **실체일원론(Substance Monism)**을 선언했습니다.

스피노자 철학의 핵심 기둥은 다음과 같습니다:
1. **신 또는 자연(Deus sive Natura)과 양태(Modus)**:
   - 자연 안에는 오직 하나의 실체만이 존재하며, 인간을 포함한 모든 개별 사물은 이 무한 실체가 사유(Thought)와 연장(Extension)이라는 속성(Attribute) 아래에서 유한하게 표현된 **양태(Mode)**에 불과합니다. 정신과 신체는 서로 다른 두 실체가 아니라, 동일한 하나의 양태가 두 속성 아래에서 관조된 병행적 표현입니다(*신체적 질서와 사유의 질서는 동일하다*).
2. **코나투스(Conatus in suo esse perseverandi)**:
   - "모든 사물은 그 자신에 속하는 한, 자신의 존재 안에 존속하고자 끊임없이 노력한다(Part III, Prop 6)."
   - 이 자기보존의 내재적 동역학이 바로 사물의 현실적 본질인 **코나투스(Conatus)**입니다.
   - 정신에만 관련된 코나투스는 **의지(Voluntas)**이며, 정신과 신체 모두에 관련된 것은 **욕구(Appetitus)**이고, 자기의식적 욕구를 **욕망(Cupiditas)**이라 부릅니다.
3. **활동역량(Potentia Agendi)과 정념(Affectus)**:
   - 사물과의 마주침을 통해 신체와 정신의 활동역량($P$)은 증감합니다.
   - **기쁨(Laetitia)**: 정신과 신체의 활동역량이 증대되는 전이 상태 ($\Delta P > 0$).
   - **슬픔(Tristitia)**: 활동역량이 감소되는 전이 상태 ($\Delta P < 0$).
   - **사랑(Amor)**: 외적 원인의 관념을 동반하는 기쁨.
   - **미움(Odium)**: 외적 원인의 관념을 동반하는 슬픔.
   - **희망(Spes)**과 **공포(Metus)**: 결과가 불확실한 미래/과거 사물의 관념에서 생겨나는 불안정한 기쁨과 슬픔.
4. **3대 인식 체계와 인간의 자유**:
   - **제1종 인식 (상상·의견, Imaginatio / Opinio)**: 외적 감각에 의한 불완전하고 혼란된 관념. 인간은 수동적 정념(Passio)에 휘둘려 **예속 상태(De Servitute)**에 처합니다.
   - **제2종 인식 (이성, Ratio)**: 사물들의 공통 성질에 대한 적합한 관념(Notio Communis). 사물을 자연의 필연성 아래 파악함으로써 슬픔을 이해의 힘으로 극복하고 능동적 기쁨으로 전환합니다.
   - **제3종 인식 (직관지, Scientia Intuitiva)**: 신의 속성에 대한 적합한 관념으로부터 사물의 본질에 도달하는 최고 인식. 만물을 **영원의 상 아래(Sub Specie Aeternitatis)**에서 직관하며, 최고의 정신적 평정인 **신에 대한 지적 사랑(Amor Dei Intellectualis)**과 궁극의 자유·지복(Beatitudo)에 도달합니다.

본 과제에서는 스피노자 『에티카』의 5개 부(신에 대하여, 정신의 본성과 기원, 정서의 기원과 본성, 인간의 예속, 지성의 역량 및 인간의 자유)를 수리적으로 정밀 모델링하여, 외적 마주침에 따른 활동역량 전이, 코나투스 보존력, 그리고 예속 대 지복의 해방 과정을 시뮬레이션하는 **Spinoza Ethics & Conatus Engine**을 구현합니다.

---

## 3대 인식 및 정서 전이 규칙

### 1. 제1종 인식 (Imaginatio / Opinio)
- 마음이 외적 원인에 휘둘리는 수동적 상태(`cognition_state = "PASSIVE_BONDAGE"`).
- `is_active = false`, `passive_affects_count` 1 증가.
- 활동역량 변화: $\Delta P = \text{valence} \times 0.8$.
- 정서 판정:
  - $\text{valence} > 0$: 1차 정서 `LAETITIA` (기쁨). `is_doubtful = true`이면 2차 정서 `SPES` (희망), 아니면 `AMOR` (사랑). 누적 기쁨에 $|\Delta P|$ 가산.
  - $\text{valence} < 0$: 1차 정서 `TRISTITIA` (슬픔). `is_doubtful = true`이면 2차 정서 `METUS` (공포), 아니면 `ODIUM` (미움). 누적 슬픔에 $|\Delta P|$ 가산.
  - $\text{valence} == 0$: 1차 `AFFECTUS_NEUTER`, 2차 `INDIFFERENTIA`.

### 2. 제2종 인식 (Ratio / Notiones Communes)
- 사물의 공통 성질과 자연의 필연성을 이해하는 능동적 상태(`cognition_state = "ACTIVE_REASON"`).
- `is_active = true`, `active_affects_count` 1 증가.
- 정서 판정:
  - $\text{valence} < 0$: 자연의 불가피한 필연성을 지적으로 이해함으로써 슬픔이 극복되어 미세한 역량 향상으로 전환됩니다: $\Delta P = |\text{valence}| \times 0.2$. 1차 정서 `ANIMI_ACQUIESCENTIA` (자기만족/이해의 평정), 2차 정서 `FORTITUDO_ANIMOSITAS` (용기/견고함). 누적 기쁨에 $\Delta P$ 가산.
  - $\text{valence} \ge 0$: $\Delta P = \text{valence} \times 1.0 \times \text{conatus\_factor}$. 1차 정서 `LAETITIA_ACTIVA` (능동적 기쁨), 2차 정서 `GENEROSITAS` (관대함/고결함). 누적 기쁨에 $\Delta P$ 가산.

### 3. 제3종 인식 (Scientia Intuitiva)
- 신 또는 자연의 속성으로부터 개별 사물의 영원한 본질을 직관하는 최고 인식(`cognition_state = "BEATITUDO_INTUITIVE"`).
- `is_active = true`, `active_affects_count` 1 증가, `amor_dei_count` 1 증가.
- $\Delta P = \max(15.0, |\text{valence}| \times 1.2) \times \text{conatus\_factor}$.
- 1차 정서: `AMOR_DEI_INTELLECTUALIS` (신에 대한 지적 사랑).
- 2차 정서: `BEATITUDO` (지복 / 최고의 자유).
- 누적 기쁨에 $\Delta P$ 가산.

### 4. 코나투스 역량 클램핑 및 자유 지수
- 매 마주침 후 활동역량 $P$는 $0.0 \le P \le 100.0$ 범위로 클램핑됩니다:
  $$P_{t+1} = \text{round}(\max(0.0, \min(100.0, P_t + \Delta P)), 2)$$
- 능동성 비율: $\text{active\_ratio} = \text{round}(\frac{\text{active\_affects\_count}}{\text{total\_encounters}}, 2)$ (마주침이 0건이면 1.0).
- 자유/지복 지수 ($0.0 \le \text{freedom\_score} \le 100.0$):
  $$\text{freedom\_score} = \text{round}(\max(0.0, \min(100.0, P_{\text{final}} \times 0.5 + \text{active\_ratio} \times 30.0 + \min(20.0, \text{amor\_dei\_count} \times 10.0))), 2)$$
- 자유 상태 판정 (`freedom_verdict`):
  - $\text{freedom\_score} \ge 80.0$: `LIBERTAS_BEATITUDO` (신에 대한 지적 사랑을 통한 영원한 자유와 지복)
  - $50.0 \le \text{freedom\_score} < 80.0$: `RATIONAL_LIBERATION` (이성의 공통개념을 통한 합리적 해방)
  - $30.0 \le \text{freedom\_score} < 50.0$: `FLUCTUATIO_ANIMI` (희망과 공포 사이를 끊임없이 방황하는 마음의 동요)
  - $\text{freedom\_score} < 30.0$: `SERVITUS_PASSIONES` (외적 정념에 압도당한 비참한 인간 예속 상태)

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 전달됩니다:
```json
{
  "agent_id": "Spinoza_Seeker",
  "initial_power": 50.0,
  "conatus_factor": 1.1,
  "encounters": [
    {"id": "ENC_01", "external_cause": "Sunlight", "valence": 20.0, "knowledge_kind": 1, "is_doubtful": false},
    {"id": "ENC_02", "external_cause": "Sickness", "valence": -30.0, "knowledge_kind": 1, "is_doubtful": true},
    {"id": "ENC_03", "external_cause": "Loss_of_Fortune", "valence": -40.0, "knowledge_kind": 2, "is_doubtful": false},
    {"id": "ENC_04", "external_cause": "Infinite_Nature", "valence": 30.0, "knowledge_kind": 3, "is_doubtful": false}
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 공백 없는 압축 JSON(`separators=(',', ':')`, `ensure_ascii=False`)을 출력합니다:
```json
{
  "agent_id": "Spinoza_Seeker",
  "final_power_of_acting": 89.6,
  "total_joy": 63.6,
  "total_sadness": 24.0,
  "active_ratio": 0.5,
  "amor_dei_count": 1,
  "freedom_score": 69.8,
  "freedom_verdict": "RATIONAL_LIBERATION",
  "evaluation_log": [
    {
      "encounter_id": "ENC_01",
      "external_cause": "Sunlight",
      "knowledge_kind": 1,
      "primary_affect": "LAETITIA",
      "secondary_affect": "AMOR",
      "is_active": false,
      "cognition_state": "PASSIVE_BONDAGE",
      "power_delta": 16.0,
      "updated_power": 66.0
    },
    {
      "encounter_id": "ENC_02",
      "external_cause": "Sickness",
      "knowledge_kind": 1,
      "primary_affect": "TRISTITIA",
      "secondary_affect": "METUS",
      "is_active": false,
      "cognition_state": "PASSIVE_BONDAGE",
      "power_delta": -24.0,
      "updated_power": 42.0
    },
    {
      "encounter_id": "ENC_03",
      "external_cause": "Loss_of_Fortune",
      "knowledge_kind": 2,
      "primary_affect": "ANIMI_ACQUIESCENTIA",
      "secondary_affect": "FORTITUDO_ANIMOSITAS",
      "is_active": true,
      "cognition_state": "ACTIVE_REASON",
      "power_delta": 8.0,
      "updated_power": 50.0
    },
    {
      "encounter_id": "ENC_04",
      "external_cause": "Infinite_Nature",
      "knowledge_kind": 3,
      "primary_affect": "AMOR_DEI_INTELLECTUALIS",
      "secondary_affect": "BEATITUDO",
      "is_active": true,
      "cognition_state": "BEATITUDO_INTUITIVE",
      "power_delta": 39.6,
      "updated_power": 89.6
    }
  ]
}
```

---

## 제약 사항

- $1 \le \text{len}(encounters) \le 100$
- $0.0 \le \text{initial\_power} \le 100.0$
- $0.1 \le \text{conatus\_factor} \le 3.0$
- $-50.0 \le \text{valence} \le +50.0$
- $\text{knowledge\_kind} \in \{1, 2, 3\}$
