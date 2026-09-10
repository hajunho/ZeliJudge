# 장 자크 루소의 사회계약론: 일반의지(Volonté Générale), 전체의지, 완전한 양도 및 인민주권 엔진

## 1. 개요 및 배경

> *"인간은 자유롭게 태어났지만, 어디서나 쇠사슬에 묶여 있다. 자기가 다른 사람들의 주인이라고 믿는 자도 그들보다 더한 노예이다."*  
> — 장 자크 루소(Jean-Jacques Rousseau), 『사회계약론(Du contrat social)』 (1762) 제1편 1장

근대 계몽주의 사상가 장 자크 루소는 토머스 홉스(절대주권자에게의 복종)와 존 로크(소유권 보호를 위한 제한 정부 신탁)의 계약론을 근본적으로 비판하며, 인민 자신이 주권자가 되는 **직접 민주주의적 공화국(Direct Republicanism)**의 수학적·정치철학적 기초를 정초했습니다.

루소가 해결하고자 한 사회계약의 근본 과제는 명확합니다:
> *"각 구성원의 신체와 재산을 공동의 힘으로 지키고 보호하며, 각자가 전체와 결합하면서도 자기 자신에게만 복종하여 이전과 다름없이 자유로운 결합의 형태를 찾는 것."* (제1편 6장)

이를 달성하기 위해 루소는 다음 세 가지 혁명적 개념을 제시합니다:
1. **완전한 양도(L'aliénation totale)**: 모든 개별 구성원은 자신의 인격과 모든 권리를 공동체 전체에 조건 없이 양도합니다. 모든 사람의 조건이 평등하므로, 누구도 타인에게 불리한 조건을 만들 유인이 사라집니다.
2. **전체의지(Volonté de tous) 대 일반의지(Volonté générale)**:
   - **전체의지**: 단순한 사적 이익들의 산술적 합계($\sum \text{사적 의지}$)로, 파벌(Faction)의 담합과 이익집단의 로비로 인해 공공선을 파괴합니다.
   - **일반의지**: 공동체 전체의 공공선(Le bien commun)과 평등을 지향하는 공동의 의지입니다. 루소는 제2편 3장에서 *"사적 의지들에서 서로 상쇄되는 과잉(+)과 결핍(-)을 제거하고 나면, 그 차이들의 합으로 일반의지가 남는다"*고 수학적으로 갈파했습니다.
3. **자유롭도록 강제됨(On le forcera d'être libre)**: 만약 개인이 사적 탐욕에 눈이 멀어 일반의지(법률)를 거부한다면, 공동체 전체는 그에게 복종을 강제합니다. 이는 개인을 억압하는 것이 아니라, 맹목적인 본능과 충동의 노예 상태에서 벗어나 스스로 정한 법에 복종하는 '도덕적 자유(Moral Liberty)'를 회복시키는 숭고한 해방 행위입니다.

당신은 시민들의 사적 선호, 파벌 담합, 시민적 덕성, 일반의지 기반 법률 제정, 그리고 집행부(군주)의 권력 찬탈에 따른 국가 타락을 정밀 시뮬레이션하는 **루소 사회계약 & 일반의지 거버넌스 엔진**을 구현해야 합니다.

---

## 2. 시스템 아키텍처 및 거버넌스 파이프라인

```
       [ 개별 시민 i 의 사적 선호 P_i ]   [ 파벌/이익집단 편향 F_k ]
                       │                           │
                       └─────────────┬─────────────┘
                                     ▼
                   [ 파벌 충성도 기반 유효 사적 선호 산출 ]
                                     │
                 [ 시민적 덕성(Civic Virtue, v_i) 결합 ]
                                     │
                                     ▼
                     [ 공표된 투표 벡터 w_i 형성 ]
                                     │
           ┌─────────────────────────┴─────────────────────────┐
           ▼                                                   ▼
  [ 전체의지 (Volonté de tous) ]            [ 일반의지 (Volonté générale) ]
    산술적 평균 (Σ w_i / N)                   시민적 덕성 가중 수렴치
    (파벌 담합 및 왜곡 취약)                  (상쇄 후 남는 공공선 벡터)
           │                                                   │
           └─────────────────────────┬─────────────────────────┘
                                     ▼
                      [ 공공선과의 괴리 오차 계산 ]
                                     │
                     [ 일반의지 기반 법률(Law) 제정 ]
                                     │
                                     ▼
             [ 시민 준수 평가: 자율적 복종 vs 자유롭도록 강제됨 ]
                    (Obedience vs On le forcera d'être libre)
                                     │
                                     ▼
            [ 집행부(군주)의 기업적 의지와 국가 타락 지수 평가 ]
```

---

## 3. 핵심 규칙 및 수리 모형

### 3.1 시민 투표 벡터 및 파벌 담합 산출
공동체에는 $D$개의 정책 차원(예: 국방, 복지, 생태, 정의 등)이 존재하며, 각 차원의 목표 공공선 벡터는 $\vec{C} = (c_1, c_2, \dots, c_D)$ ($c_d \in [-1.0, 1.0]$)입니다.

각 시민 $i$는 원초적 사적 선호 $\vec{P}_i$, 시민적 덕성 $v_i \in [0.0, 1.0]$, 소속 파벌 $f_i$, 파벌 충성도 $\lambda_i \in [0.0, 1.0]$를 갖습니다:
1. 파벌 소속인 경우 유효 사적 선호:
   $$p'_{i, d} = (1 - \lambda_i) \cdot P_{i, d} + \lambda_i \cdot F_{f_i, d}$$
   (독립 시민인 경우 $p'_{i, d} = P_{i, d}$)
2. 공표된 투표 벡터 $\vec{w}_i$:
   $$w_{i, d} = \text{round}\left(v_i \cdot c_d + (1 - v_i) \cdot p'_{i, d}, \ 4\right)$$

### 3.2 전체의지 vs 일반의지 추출
- **전체의지 (Volonté de tous)**: 모든 시민의 공표된 투표의 단순 산술평균:
  $$V_{\text{all}, d} = \text{round}\left(\frac{1}{N} \sum_{i=1}^N w_{i, d}, \ 4\right)$$
- **일반의지 (Volonté générale)**: 사적 충동의 상쇄를 거쳐 공공선을 지향하는 시민적 덕성 가중 합의:
  $$V_{\text{general}, d} = \text{round}\left(\frac{\sum_{i=1}^N v_i \cdot w_{i, d}}{\sum_{i=1}^N v_i}, \ 4\right)$$
  *(단, $\sum v_i = 0$인 경우 전체의지와 동일하게 설정)*

### 3.3 파벌 편극화 지수 (Factional Polarization)
등록된 파벌이 2개 이상인 경우, 각 파벌에 속한 시민들의 공표 투표 평균 벡터들 간의 모든 쌍(Pair) 유클리드 거리의 RMS(Root Mean Square)를 계산하여 소수점 4자리로 반올림합니다. 파벌이 1개 이하이거나 쌍이 없는 경우 0.0입니다.

### 3.4 법률 제정 및 "자유롭도록 강제됨(On le forcera d'être libre)"
제안된 법안 $L$은 정책 가중치 벡터 $\vec{L}$과 통과 기준치 $\tau$를 가집니다:
- **법률 가결 조건**: $\sum_{d} V_{\text{general}, d} \cdot L_d \ge \tau$ 이면 가결되어 `enacted_laws`에 추가됩니다.
- **시민 준수 및 강제 평가**: 가결된 법률에 대해 각 시민 $i$의 원초적 사적 선호 $\vec{P}_i$와의 내적 $\sum_{d} P_{i, d} \cdot L_d$를 평가합니다:
  - 내적 $\ge 0$: 자신의 양심과 법률이 일치하므로 자율적 복종(`"OBEYS_AUTONOMOUSLY"`, `moral_liberty_restored: false`).
  - 내적 $< 0$: 사적 이기심이 공공선과 충돌하므로 주권 공동체의 강제 집행 적용(`"FORCED_TO_BE_FREE"`, `moral_liberty_restored: true`).

### 3.5 집행부(군주) 권력 찬탈 및 국가 타락 지수 (Degeneration Index)
루소는 『사회계약론』 제3편 10장에서 집행부(행정부)의 독자적 단체 의지(Volonté de corps)가 인민의 주권(입법권)을 잠식하는 타락 과정을 경고했습니다.
$$\text{degeneration\_index} = \text{round}\left(\frac{\text{exec\_power} \times \text{corporate\_will\_bias}}{\max(0.01, \text{civic\_oversight})}, \ 4\right)$$
- $\text{degeneration\_index} \ge \text{dissolution\_threshold}$:
  - `republic_status: "STATE_DISSOLVED_USURPATION"`
  - `sovereignty_verdict: "ANARCHY_OR_TYRANNY"`
- $1.0 \le \text{degeneration\_index} < \text{dissolution\_threshold}$:
  - `republic_status: "DEGENERATING_ARISTOCRACY"`
  - `sovereignty_verdict: "SOVEREIGNTY_THREATENED"`
- $\text{degeneration\_index} < 1.0$:
  - `republic_status: "HEALTHY_LEGITIMATE_REPUBLIC"`
  - `sovereignty_verdict: "POPULAR_SOVEREIGNTY_INTACT"`

---

## 4. 입출력 형식 및 제약 조건

### 입력 형식 (JSON)
```json
{
  "common_good": { "defense": 0.8, "welfare": 0.7, "ecology": 0.9 },
  "citizens": [
    {
      "citizen_id": "c1",
      "civic_virtue": 0.9,
      "private_preferences": { "defense": 0.7, "welfare": 0.6, "ecology": 0.8 },
      "faction_id": null,
      "faction_loyalty": 0.0
    }
  ],
  "factions": {
    "oligarchs": { "defense": -0.9, "welfare": -0.9, "ecology": -0.9 }
  },
  "proposed_laws": [
    {
      "law_id": "law_eco_tax",
      "policy_vector": { "defense": 0.0, "welfare": 0.2, "ecology": 0.9 },
      "threshold": 0.5
    }
  ],
  "executive": {
    "power": 0.6,
    "corporate_will_bias": 0.4,
    "civic_oversight": 0.8,
    "dissolution_threshold": 1.5
  }
}
```

### 출력 형식 (JSON)
```json
{
  "will_of_all": { "defense": 0.0978, "welfare": 0.031, "ecology": 0.1247 },
  "general_will": { "defense": 0.5908, "welfare": 0.506, "ecology": 0.655 },
  "divergence_metrics": {
    "will_of_all_error": 1.2417,
    "general_will_error": 0.3761,
    "faction_polarization": 0.0
  },
  "enacted_laws": [ "law_eco_tax" ],
  "enforcement_summary": {
    "total_evaluations": 4,
    "autonomous_obediences": 2,
    "forced_to_be_free_count": 2
  },
  "executive_state": {
    "degeneration_index": 0.3,
    "republic_status": "HEALTHY_LEGITIMATE_REPUBLIC",
    "sovereignty_verdict": "POPULAR_SOVEREIGNTY_INTACT"
  },
  "detailed_enforcement": [
    {
      "law_id": "law_eco_tax",
      "citizen_id": "c1",
      "compliance": "OBEYS_AUTONOMOUSLY",
      "moral_liberty_restored": false
    }
  ]
}
```
