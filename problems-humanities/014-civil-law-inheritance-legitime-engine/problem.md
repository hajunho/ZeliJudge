# [법학/민법/상속법] 한국 민법 유류분(Legitime / Forced Heirship) 반환 청구와 상속분·특별수익·기여분 계산 엔진

## 문제 설명

상속과 유류분(遺留分, Legitime / Forced Share)은 대법원 민사 재판과 패밀리 오피스, 자산관리 핀테크(WealthTech), 리걸테크(LegalTech)에서 가장 치열하게 다투어지는 수리 법학(Legal Computing)의 정점입니다.

대한민국 민법(제1000조~제1118조)에 따르면, 피상속인은 유언의 자유를 통해 자신의 재산을 자유롭게 처분할 수 있으나, 유족의 최소한의 생존권과 공평성을 보장하기 위해 법정상속분의 일정 비율(직계비속·배우자 1/2, 직계존속 1/3)을 반드시 유류분으로 보장하도록 규정하고 있습니다.
그러나 실제 상속 재산 분할과 유류분 청구는 단순하지 않습니다:
1. **법정상속분율(Statutory Share Ratio)**: 피상속인의 배우자는 자녀나 직계존속의 상속분에 **50%를 가산(1.5 : 1.0)**받습니다.
2. **기여분(Contributory Share)**: 피상속인을 특별히 간병·부양했거나 재산 증식에 특별히 기여한 상속인의 몫은 상속재산에서 **최우선 공제**됩니다.
3. **특별수익(Special Benefits / Hotchpot)**: 일부 자녀가 결혼 자금, 주택 구입 등으로 피상속인 생전에 미리 증여받았거나 유증받은 재산은 **상속분의 선급(先給)**으로 보아 간주상속재산에 전액 산입(Hotchpot)되어 구체적 상속분에서 공제됩니다. 생전 증여가 자신의 상속분을 초과하는 **초과특별수익자(Excess Heir)**가 발생할 경우, 나머지 상속인들 간에 재분배가 이루어집니다.
4. **유류분 산정 기초재산(Base Property for Legitime)**: 상속개시 당시 적극재산에 산입 대상 생전증여액을 더하고 상속채무를 공제하여 산정합니다.
5. **유류분 부족액(Shortfall) 및 감쇄 순서(Abatement Order)**: 자신의 유류분액보다 실제 취득한 순상속액과 특별수익의 합이 적은 상속인은 **유류분 부족액(Shortfall)**을 반환 청구할 수 있으며, 법률 규정에 따라 **유증(Bequest)을 먼저 반환받고, 부족하면 생전 증여(Lifetime Gift)를 순차 감쇄**합니다.

대한민국 법원 사법정보화추진단 및 리걸테크 연구팀의 일원이 되어, 복잡한 상속인 구성과 생전증여, 유증, 상속채무, 기여분이 얽힌 분쟁 사안에서 각 상속인의 구체적 분할 상속액과 유류분 부족액을 1원 단위까지 정밀 산출하고, 반환 의무자별 감쇄 계획을 자동 수립하는 **한국 민법 상속·유류분 전산 심판관 엔진**을 구현하십시오.

---

## 법률 공리 및 계산 규격 (민법 제1000조 ~ 제1118조)

### 1. 상속 순위 및 법정상속분율 (Statutory Share Ratios)
- **제1순위**: 직계비속(자녀) 및 배우자.
- **제2순위**: 직계비속이 없는 경우 직계존속(부모) 및 배우자.
- **제3순위**: 비속·존속이 모두 없는 경우 배우자 단독 상속.
- **가중치**: 배우자는 $1.5$, 직계비속 및 직계존속은 각 $1.0$.
  $$\text{statutory\_share\_ratio}_i = \frac{w_i}{\sum_{j} w_j}$$

### 2. 기여분(Contributory Share) 및 구체적 상속분 (Concrete Share)
- $\text{distributable\_estate} = \max(0, \text{estate\_at\_death} - \text{total\_bequests})$
- 분할 대상 순재산: $\text{net\_divisible} = \max(0, \text{distributable\_estate} - \sum \text{contributory\_share})$
- 간주상속재산: $\text{deemed\_estate} = \text{net\_divisible} + \sum_{i \in \text{Heirs}} \text{special\_benefit}_i$
- 1차 구체적 상속분:
  $$\text{cs}_i = \text{deemed\_estate} \times \text{statutory\_share\_ratio}_i - \text{special\_benefit}_i$$
- **초과특별수익 처리**:
  - 만약 $\text{cs}_i < 0$인 상속인이 존재하면, 해당 상속인은 초과액을 반환할 의무는 없으나 상속재산 분할에서 제외($\text{cs}_i = 0$)됩니다.
  - 남은 비초과 상속인들끼리 가중치 비율로 $\text{net\_divisible}$을 재분배합니다.
- 최종 실제 취득액:
  $$\text{actual\_estate\_share}_i = \text{reallocated\_share}_i + \text{contributory\_share}_i$$

### 3. 유류분 산정 기초재산 및 유류분율 (Legitime Quota)
- $\text{legitime\_base\_property} = \text{estate\_at\_death} + \text{includable\_gifts} - \text{debts}$
- **유류분율**:
  - 직계비속, 배우자: 법정상속분율의 $\frac{1}{2}$
  - 직계존속: 법정상속분율의 $\frac{1}{3}$
  - (형제자매: 2024년 헌법재판소 위헌 판결로 유류분 없음)
- 유류분액: $\text{legitime\_quota}_i = \max(0, \text{legitime\_base\_property} \times \text{legitime\_rate}_i)$

### 4. 유류분 부족액 (Legitime Shortfall)
- 승계 채무: $\text{inherited\_debt}_i = \text{debts} \times \text{statutory\_share\_ratio}_i$
- 순상속액: $\text{net\_inheritance}_i = \text{actual\_estate\_share}_i - \text{inherited\_debt}_i$
- 총 취득 가액: $\text{total\_acquired}_i = \text{net\_inheritance}_i + \text{special\_benefit}_i$
- 유류분 부족액:
  $$\text{shortfall}_i = \max(0.0, \text{legitime\_quota}_i - \text{total\_acquired}_i)$$

### 5. 유류분 반환 감쇄 순서 (Abatement Order, 민법 제1115조, 제1116조)
- 총 유류분 부족액 $\sum \text{shortfall}_i$에 대해:
  1. **유증(Bequests) 우선 감쇄**:
     - 총 부족액이 유증 총액 이하인 경우 유증 수유자들의 유증액 비율로 안분 감쇄.
  2. **생전 증여(Lifetime Gifts) 2차 감쇄**:
     - 유증을 전액 감쇄하고도 부족액이 남는 경우, 기초재산에 산입된 생전 증여 수증자들의 증여액 비율로 안분 감쇄.

---

## 입력 형식

표준 입력(`sys.stdin`)으로 상속재산, 상속채무, 상속인 목록, 생전증여 및 유증 데이터가 포함된 JSON이 주어집니다:
```json
{
  "estate_at_death": 1000000000,
  "debts": 0,
  "heirs": [
    {"id": "Child_A", "relation": "CHILD"},
    {"id": "Child_B", "relation": "CHILD"}
  ],
  "lifetime_gifts": [],
  "testamentary_bequests": [
    {"recipient": "Child_A", "amount": 900000000}
  ]
}
```

---

## 출력 형식

표준 출력(`sys.stdout`)으로 상속 재산 요약, 상속인별 분할액, 유류분 평가 및 반환 감쇄 계획이 포함된 단일 라인 JSON을 출력합니다:
```json
{
  "estate_summary": {
    "estate_at_death": 1000000000,
    "debts": 0,
    "total_bequests": 900000000,
    "includable_gifts": 0,
    "legitime_base_property": 1000000000
  },
  "heir_inheritance": [
    {
      "id": "Child_A",
      "relation": "CHILD",
      "statutory_share_ratio": 0.5,
      "actual_estate_share": 0.0,
      "contributory_share": 0
    },
    {
      "id": "Child_B",
      "relation": "CHILD",
      "statutory_share_ratio": 0.5,
      "actual_estate_share": 100000000.0,
      "contributory_share": 0
    }
  ],
  "legitime_evaluation": {
    "total_shortfall": 150000000.0,
    "claims": [
      {
        "id": "Child_A",
        "relation": "CHILD",
        "statutory_share_ratio": 0.5,
        "legitime_quota": 250000000.0,
        "net_inheritance": 0.0,
        "special_benefit": 900000000,
        "shortfall": 0.0,
        "has_claim": false
      },
      {
        "id": "Child_B",
        "relation": "CHILD",
        "statutory_share_ratio": 0.5,
        "legitime_quota": 250000000.0,
        "net_inheritance": 100000000.0,
        "special_benefit": 0,
        "shortfall": 150000000.0,
        "has_claim": true
      }
    ]
  },
  "abatement_resolution": [
    {
      "target_type": "BEQUEST",
      "recipient": "Child_A",
      "original_amount": 900000000,
      "abated_return_amount": 150000000.0
    }
  ]
}
```
