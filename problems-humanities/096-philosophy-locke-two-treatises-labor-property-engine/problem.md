# 존 로크의 통치론: 노동 가치설, 소유권 2대 단서, 신탁(Trust) 및 저항권(하늘에의 호소) 엔진

## 문제 설명

1689년 영국의 계몽주의 철학자 **존 로크(John Locke, 1632–1704)**는 명예혁명(1688)을 정당화하고 근대 자유주의 민주주의와 헌정주의의 기초를 정초한 대작 『통치론(Two Treatises of Government, 제2권)』을 발표했습니다.

로크는 홉스와 달리, 공통 권력이 없는 **자연상태(State of Nature)**도 이성의 법인 **자연법(Law of Nature)**이 지배하는 평화롭고 자유로운 상태라고 보았습니다:
> *"인간은 신체와 생명에 대해 타고난 소유권을 가지며, 누구도 타인의 생명, 건강, 자유, 또는 소유물을 침해해서는 안 된다."*

로크 철학의 핵심 축은 다음 세 가지로 구성됩니다:

### 1. 노동 가치설과 사유 재산권의 기원
- 본래 신이 인류에게 공유물(Commons)로 하사한 대지에서, 인간이 자신의 신체적 노동(Labor)을 섞을 때 그 결과물은 배타적인 **사유 재산(Private Property)**이 됩니다.
- 그러나 무제한의 소유권 획득은 다음 **2대 로크 단서(Lockean Provisos)**에 의해 제한됩니다:
  1. **충분성 단서(Sufficiency Proviso)**: *"타인들을 위해서도 충분하고 동일한 품질의 몫이 남아있는 경우(enough, and as good, left in common for others)"*에만 정당함.
  2. **부패 금지 단서(Spoilage Proviso)**: 자신이 소비하기 전에 썩어서 버릴 정도로 과도하게 취해서는 안 됨.
- 부패하지 않는 **화폐(금·은)**의 발명은 부패 단서를 우회하여 합법적인 불평등 축적의 길을 열었습니다.

### 2. 신탁(Fiduciary Trust)으로서의 정부
- 자연상태에서 각 개인이 자연법 집행자로서 겪는 자의적 편향을 극복하기 위해, 만인은 합의(Consent)를 통해 자신의 자연법 집행권을 포기하고 시민 정부(입법부와 집행부)를 세웁니다.
- 국가 권력은 지배자의 소유물이 아니라 오직 시민의 재산권(생명·자유·자산)을 보호하기 위해 맡겨진 **신탁(Fiduciary Trust)**에 불과합니다.

### 3. 저항권과 하늘에의 호소 (Appeal to Heaven)
- 만약 군주나 입법부가 국민의 동의 없이 세금을 부과하거나(대표 없는 과세), 자의적으로 시민의 재산을 강탈하여 신탁을 배반하면, 정부는 스스로 정당성을 상실하고 해체됩니다.
- 지상에 더 이상 공정한 재판관이 존재하지 않을 때, 시민들은 **"하늘에의 호소(Appeal to Heaven)"**, 즉 정당한 무력에 의한 **저항권(Right of Revolution)**을 발동하여 폭정을 타도하고 새로운 정부를 수립할 천부적 권리를 갖습니다.

```
                           +-------------------------------------+
                           |    인류 공동의 공유 자연자원 (Commons) |
                           +-------------------------------------+
                                              |
                                              v  (노동의 혼합)
         +-------------------------------------------------------------------------+
         |                        사유 재산권(Property) 창출                       |
         |         1. 충분성 단서 검사: 타인을 위한 몫 >= 최소 생존 잔여             |
         |         2. 부패 금지 단서 검사: 한도 초과 시 잉여분 손실(Spoilage)        |
         |         3. 화폐 교환: 금·은 태환을 통한 부패 한계 초과 합법 축적          |
         +-------------------------------------------------------------------------+
                                              |
                                              v  (시민 동의 기반)
         +-------------------------------------------------------------------------+
         |                   시민 정부와 신탁(Fiduciary Trust) 설립                 |
         +-------------------------------------------------------------------------+
                                              |
                         +--------------------+--------------------+
                         |                                         |
                 [신탁 준수: 공정한 법치]                  [신탁 위반: 대표 없는 과세/수탈]
                 폭정 지수 < 임계치(0.65)                  폭정 지수 >= 임계치(0.65)
                         |                                         |
                         v                                         v
              "정당한 법치주의 커먼웰스"                 "하늘에의 호소 (Appeal to Heaven)"
              (시민 재산권 보장)                        (정부 해체 및 혁명권 발동 정당화)
```

본 문제에서는 로크의 노동 가치설, 2대 단서, 화폐 태환, 신탁 정부 설립, 그리고 폭정에 맞선 하늘에의 호소 저항권 평가를 정밀하게 모사하는 **존 로크 통치론 및 재산권 시뮬레이션 엔진**을 구현해야 합니다.

---

## 핵심 메커니즘 및 명세

### 1. 전역 설정 및 상태
- `common_resources`: 공유 자연자원 잔여량.
- `min_subsistence_per_capita`: 1인당 최소 보장 생존 자원 임계값 (충분성 단서 기준).
- `spoilage_threshold`: 부패하지 않고 보관 가능한 부패성 재화 최대 한도.
- `tyranny_threshold`: 신탁 위반 및 저항권 발동 폭정 임계값 (기본값: `0.65`).
- `tyranny_score`: 정부의 폭정 누적 지수 ($0.0 \sim 1.0$, 초기값 0.0).
- `government_established`: 시민 정부 수립 여부.

### 2. 연산 명세
1. `ADD_AGENT`: 신규 시민 등록 (`perishable = 0`, `durable_money = 0`, `estate_land = 0`, `trust = 1.0`).
2. `APPROPRIATE_BY_LABOR`:
   - 입력: `id`, `labor_units`, `yield_per_labor` (기본 2.0)
   - 획득 요구량: $\Delta R = 	ext{labor\_units} 	imes 	ext{yield\_per\_labor}$.
   - **충분성 단서(Sufficiency Proviso) 검사**:
     - 차감 후 1인당 잔여 공유자원:
       $$Q_{	ext{capita}} = rac{	ext{common\_resources} - \Delta R}{N_{	ext{agents}}}$$
     - $Q_{	ext{capita}} < 	ext{min\_subsistence\_per\_capita}$이면 단서 위반으로 기각:
       `{"status": "PROVISO_VIOLATION_NOT_ENOUGH_LEFT", "id": ..., "requested": ..., "per_capita_left": ..., "required_min": ...}`
   - 자원 차감 및 노동 투입 반영:
     - `common_resources -= requested`, `agent.estate_land += labor_units * 0.5`.
   - **부패 금지 단서(Spoilage Proviso) 검사**:
     - $	ext{total} = 	ext{agent.perishable} + \Delta R$.
     - $	ext{total} > 	ext{spoilage\_threshold}$이면:
       - 잉여분 $	ext{spoiled} = 	ext{total} - 	ext{spoilage\_threshold}$는 부패 손실.
       - `agent.perishable = spoilage_threshold`.
       - `{"status": "SPOILAGE_LOSS", "id": ..., "appropriated": ..., "spoiled_units": ..., ...}`
     - 그렇지 않으면 정상 적재: `{"status": "APPROPRIATION_SUCCESS", ...}`
3. `TRADE_MONEY`:
   - 부패성 재화를 내구적 화폐(금)로 환전하여 부패 단서를 극복.
   - `agent.perishable -= amount`, `agent.durable_money += amount * gold_per_unit`.
   - 반환: `{"status": "TRADE_SUCCESS", ...}`
4. `ESTABLISH_COMMONWEALTH`:
   - 정부를 수립하고 `government_established = true`, `tyranny_score = 0.0`으로 설정.
   - 반환: `{"status": "COMMONWEALTH_ESTABLISHED", "signers_count": ..., "fiduciary_trust": "ACTIVE"}`
5. `GOVERNMENT_ACTION`:
   - `action`: `"PROTECT_PROPERTY"` 또는 `"ARBITRARY_TAX_WITHOUT_CONSENT"` / `"CONFISCATE_ESTATE"`.
   - `"PROTECT_PROPERTY"`: `tyranny_score = max(0.0, tyranny_score - 0.1)`, 신뢰도 상승.
   - 침해 행위: `tyranny_score = min(1.0, tyranny_score + severity)`, 시민 신뢰도 하락.
   - 반환: `{"action": ..., "tyranny_score": ..., "verdict": ...}`
6. `EVALUATE_REVOLUTION`:
   - 정부 미수립 시: `state = "STATE_OF_NATURE"`.
   - 정부 수립 후:
     - `tyranny_score >= tyranny_threshold`이면:
       - `state = "APPEAL_TO_HEAVEN"`
       - `verdict = "신탁 위반에 따른 정부 해체 및 하늘에의 호소(저항권/혁명권 발동)"`
       - `justified_revolution = true`
     - 그렇지 않으면:
       - `state = "LEGITIMATE_COMMONWEALTH"`
       - `justified_revolution = false`

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 전달됩니다:
```json
{
  "config": {
    "common_resources": 500.0,
    "spoilage_threshold": 50.0,
    "min_subsistence_per_capita": 10.0,
    "tyranny_threshold": 0.65
  },
  "operations": [
    { "op": "ADD_AGENT", "id": "pioneer_alice" },
    { "op": "APPROPRIATE_BY_LABOR", "id": "pioneer_alice", "labor_units": 15, "yield_per_labor": 2.0 },
    { "op": "ESTABLISH_COMMONWEALTH" },
    { "op": "EVALUATE_REVOLUTION" }
  ]
}
```

## 출력 형식

표준 출력(stdout)으로 각 연산의 수행 결과를 담은 JSON 배열을 공백 없이(compact) 출력합니다.

---

## 제약 사항

- $0.0 \le 	ext{common\_resources} \le 10^7$
- $0.0 \le 	ext{tyranny\_threshold} \le 1.0$
- 연산 수 $N \le 5000$
- 시간 복잡도: 각 연산 $O(1)$ ~ $O(M)$, 전체 $O(N)$ 이내.
