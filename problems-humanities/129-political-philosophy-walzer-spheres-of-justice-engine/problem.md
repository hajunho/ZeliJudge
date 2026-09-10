# #129 - 마이클 왈처의 정의와 다원적 평등: 복합 평등(Complex Equality), 정의의 영역(Spheres of Justice), 독점과 지배(Dominance) 차단 엔진

## 📖 문제 배경과 역사적 맥락

> *"정의는 인간 사회의 구성물이며, 단 하나의 보편적인 분배 기준이란 존재하지 않는다. 모든 사회적 재화(Social Goods)는 고유한 사회적 의미를 지니며, 그 의미에 합당한 고유한 분배 영역(Spheres of Justice)에 속해 있다. 정의의 핵심은 특정 영역의 재화(예: 돈)를 소유했다는 이유만으로 다른 영역의 재화(권력, 입학, 의료, 명예)를 지배하거나 매수하지 못하도록 각 영역의 자율성(Autonomy of Spheres)을 지키는 '복합 평등(Complex Equality)'에 있다."*  
> — **마이클 왈처 (Michael Walzer, 1935– ), 『정의의 영역들』(Spheres of Justice: A Defense of Pluralism and Equality, 1983)**

20세기 정치철학에서 존 롤스의 자유주의적 분배론과 로버트 노직의 자유지상주의가 "소득과 부를 어떻게 나눌 것인가"라는 단일한 경제적 축을 두고 대립할 때, 공동체주의적 다원주의 철학자 **마이클 왈처(Michael Walzer)**는 근본적으로 다른 차원의 혁명적 저작 **『정의의 영역들(Spheres of Justice, 1983)』**을 발표했습니다.

왈처는 사회의 모든 재화를 단 하나의 척도(돈이나 기본적 재화)로 환원하여 똑같이 나누려는 **"단순 평등(Simple Equality)"**의 환상을 단호히 거부했습니다. 단순 평등 사회에서는 누군가 시장에서 더 많은 부를 획득하는 순간, 그 부를 이용해 권력을 사고 좋은 대학에 입학하며 최고의 의료를 독점하는 새로운 전제군주로 군림하게 되기 때문입니다.

```
       ┌────────────────────────────────────────────────────────┐
       │             마키아벨리/롤스 너머의 『복합 평등』 구조          │
       └────────────────────────────────────────────────────────┘
                                    │
    ┌───────────────────────────────┼───────────────────────────────┐
    ▼                               ▼                               ▼
[ 1. 시장 영역 (Market) ]   [ 2. 정치 영역 (Politics) ]     [ 3. 의료/복지 (Welfare) ]
  - 고유 가치: 돈/부          - 고유 가치: 공직/투표권        - 고유 가치: 생명/치료
  - 분배 기준: 자유 교환      - 분배 기준: 민주적 토론        - 분배 기준: 의학적 필요(Need)
    │                               │                               │
    └───────────────────────┬───────┴───────────────────────────────┘
                            │
              ═════════════════════════════════════
              🚫 영역 간 방화벽 (Spheres Firewall) 🚫
                 - 지배(Dominance)와 전환(Conversion) 차단
                 - "돈으로 공직을 사거나(매관매직),
                    돈으로 새치기 진료를 받지 못하게 하라!"
              ═════════════════════════════════════
                            │
                            ▼
           ┌──────────────────────────────────┐
           │        복합 평등 (Complex Equality)│
           │  - 시장에서 부의 불평등은 용인되나│
           │  - 어떤 개인도 전 영역을 독점하는 │
           │    '폭군(Tyrant)'이 될 수 없는 사회│
           └──────────────────────────────────┘
```

### 왈처 복합 평등론의 3대 핵심 원리
1. **독점(Monopoly)과 지배(Dominance)의 엄격한 구별**:
   - **독점**: 한 영역 내부에서 특정 재화를 많이 가지는 것 (예: 훌륭한 사업가가 시장 영역에서 막대한 부를 누리는 것). 왈처는 그 부가 시장 내부에 머무는 한 이를 정의롭지 않다고 보지 않습니다.
   - **지배(Dominance)**: 한 영역의 재화가 다른 영역의 재화를 강제로 획득하는 환전소(Currency of Currencies) 역할을 하는 것 (예: 부자가 돈으로 의원직을 사고, 법원 판결을 매수하며, 대학 입학을 거래하는 것).
2. **영역의 자율성(Autonomy of Spheres)**:
   - "어떤 사회적 재화 $X$를 소유하고 있다는 이유만으로, 다른 재화 $Y$의 고유한 의미를 무시한 채 $Y$를 차지해서는 안 된다."
3. **복합 평등(Complex Equality)의 정의**:
   - 복합 평등은 모든 사람의 재산이 같은 사회가 아닙니다. 어떤 사람은 명예가 높고, 어떤 사람은 부유하며, 어떤 사람은 지식이 깊지만, **어느 누구도 한 영역의 우위를 빌미로 다른 영역의 시민들을 지배할 수 없는 다원적 분립 사회**입니다.

본 과제에서는 왈처의 5대 정의 영역(시장, 정치, 교육, 의료, 명예)과 영역 간 방화벽(Firewall) 상태 머신을 구축하여 지배 침범 여부와 복합 평등도를 판정하는 시뮬레이션 엔진을 구현합니다.

---

## 📥 입력 형식 (Input Specification)

입력은 표준 입력(Standard Input)으로 단일 JSON 객체가 주어집니다:

```json
{
  "initial_state": {
    "citizens": {
      "Plutocrat": {"wealth": 90.0, "political_power": 30.0, "education": 40.0, "healthcare": 50.0, "honor": 20.0},
      "Scholar": {"wealth": 20.0, "political_power": 30.0, "education": 90.0, "healthcare": 50.0, "honor": 80.0},
      "Worker": {"wealth": 30.0, "political_power": 30.0, "education": 30.0, "healthcare": 40.0, "honor": 40.0}
    },
    "firewall_enabled": false
  },
  "events": [
    {
      "type": "CROSS_SPHERE_CONVERSION",
      "params": {
        "agent": "Plutocrat",
        "src_sphere": "wealth",
        "dst_sphere": "political_power",
        "cost": 20.0,
        "gain": 55.0
      }
    },
    {
      "type": "TOGGLE_SPHERE_FIREWALL",
      "params": {
        "enabled": true
      }
    },
    {
      "type": "CROSS_SPHERE_CONVERSION",
      "params": {
        "agent": "Plutocrat",
        "src_sphere": "wealth",
        "dst_sphere": "healthcare",
        "cost": 20.0,
        "gain": 40.0
      }
    },
    {
      "type": "NEED_BASED_HEALTHCARE_DISTRIBUTION",
      "params": {
        "recipient": "Worker",
        "care_units": 45.0
      }
    }
  ]
}
```

### 제약조건 및 파라미터 규칙:
1. `initial_state`:
   - `citizens`: 시민 사전. 각 시민은 `wealth`, `political_power`, `education`, `healthcare`, `honor` 5대 영역 점수($[0, 100]$)를 보유합니다.
   - `firewall_enabled`: 영역 간 자율성 방화벽 활성화 플래그 (불리언, 기본값 `true`).
2. `events`: 다음 5가지 사건이 순서대로 발생합니다:
   - `MARKET_EXCHANGE`:
     - 파라미터: `buyer`, `seller`, `amount`.
     - 동작: 시장 영역 내부의 정당한 거래. 구매자 `wealth` 차감, 판매자 `wealth` 증가. 상태: `MARKET_EXCHANGE_SUCCESS`.
   - `CROSS_SPHERE_CONVERSION`:
     - 파라미터: `agent`, `src_sphere`, `dst_sphere`, `cost`, `gain`.
     - 동작:
       1. `firewall_enabled == true`인 경우: 방화벽이 불법 지배 전환을 차단, `total_blocked_violations += 1`, 상태: `DOMINANCE_BLOCKED_BY_FIREWALL`.
       2. `firewall_enabled == false`인 경우: 부당 전환 발생! `src_sphere` 차감, `dst_sphere += gain`, `total_dominance_violations += 1`, 상태: `ILLICIT_DOMINANCE_CONVERTED`.
   - `NEED_BASED_HEALTHCARE_DISTRIBUTION`:
     - 파라미터: `recipient`, `care_units`.
     - 동작: 의학적 필요에 따른 의료 자원 배분. `healthcare = min(100.0, healthcare + care_units)`. 상태: `HEALTHCARE_ALLOCATED_BY_NEED`.
   - `DEMOCRATIC_OFFICE_ALLOCATION`:
     - 파라미터: `candidate`, `votes_share`.
     - 동작: 민주적 선거에 의한 공직 배분. `political_power = min(100.0, political_power + votes_share)`. 상태: `OFFICE_ALLOCATED_DEMOCRATICALLY`.
   - `TOGGLE_SPHERE_FIREWALL`:
     - 파라미터: `enabled` (불리언).
     - 동작: 방화벽 활성화 상태 변경. 상태: `FIREWALL_STATE_CHANGED`.

### 3. 복합 평등 판정 로직:
- **다중 영역 독점 폭군(`dominant_tyrants`)**: 5대 영역 중 3개 이상의 영역에서 점수 $\ge 80.0$인 시민 목록.
- **복합 평등(`is_complex_equal`)**: `total_dominance_violations == 0`이고 `len(dominant_tyrants) == 0`인 경우에만 `true`.

---

## 📤 출력 형식 (Output Specification)

시뮬레이션 완료 후 최종 사회 상태를 압축 JSON 문자열(`separators=(',', ':')`, `ensure_ascii=False`)로 표준 출력에 인쇄합니다:

```json
{
  "final_is_complex_equal": false,
  "total_dominance_violations": 1,
  "total_blocked_violations": 1,
  "dominant_tyrants": [],
  "citizens": {
    "Plutocrat": {
      "wealth": 70.0,
      "political_power": 85.0,
      "education": 40.0,
      "healthcare": 50.0,
      "honor": 20.0
    }
  },
  "history": [
    {
      "epoch": 1,
      "event": "CROSS_SPHERE_CONVERSION",
      "status": "ILLICIT_DOMINANCE_CONVERTED",
      "is_complex_equal": false,
      "total_dominance_violations": 1,
      "dominant_tyrants": [],
      "detail": "Sphere autonomy breached: Plutocrat converted 20.0 wealth to 55.0 political_power."
    }
  ]
}
```

*참고*: 모든 부동소수점 수치는 `round(val, 2)`를 적용합니다.

---

## 🎯 채점 기준 및 제약 조건

1. 정확성 100%: 8개 모든 테스트케이스의 수치 및 지배 침범 차단, 복합 평등 플래그가 완벽히 일치해야 합니다.
2. 왈처의 영역별 고유 분배 기준(자유 교환, 의학적 필요, 민주적 선거)과 방화벽 상태 전이를 정확히 수행해야 합니다.
3. Windows 환경에서의 UTF-8 입출력을 준수해야 합니다.
