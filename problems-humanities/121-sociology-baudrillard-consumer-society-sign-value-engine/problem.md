# 장 보드리야르: 소비의 사회(La société de consommation) — 기호가치(Sign-Value), 차별화의 코드(Le Code) 및 상징적 교환 포틀래치 엔진

## 문제 설명

프랑스의 대표적 사회학자이자 철학자 **장 보드리야르(Jean Baudrillard, 1929~2007)**는 1970년 『소비의 사회(La société de consommation)』와 1972년 『기호정치경제학 비판(Pour une critique de l'économie politique du signe)』을 통해, 고전 경제학과 정통 마르크스주의의 한계를 통렬하게 해체했습니다.

칼 마르크스는 상품을 **사용가치(Use-Value / Gebrauchswert)**와 **교환가치(Exchange-Value / Tauschwert)**의 2중성으로 파악했으나, 보드리야르는 현대 후기 자본주의에서 인간이 사물 자체의 물리적 유용성을 소비하는 것이 아니라, 사회적 서열과 구별짓기를 지시하는 **기호가치(Sign-Value / Valeur d'échange-signe)**를 소비한다고 논증했습니다:

```
          [ 마르크스의 전통적 2대 가치 ]
          1. 사용가치 (Use-Value, UV): 실용적 도구성, 물리적 효용
          2. 교환가치 (Exchange-Value, EV): 화폐 가격, 등가 교환성
                               |
                               v
          [ 보드리야르의 기호정치경제학 4대 가치 ]
     +----------------------------------------------------+
     | 3. 기호가치 (Sign-Value, SV): 사회적 위세, 차별화 코드 |
     | 4. 상징적 교환 (Symbolic Exchange, SE): 증여, 포틀래치 |
     +----------------------------------------------------+
                               |
                               v
       [ 소비 사회의 순환 메커니즘 (The Machine of Consumption) ]
  1. 기호 소비: 사물이 아니라 다른 계급과의 '차이(Difference)'를 구매!
  2. 욕망의 인위적 재생산: 생산 시스템이 결핍(Synthetic Lack)을 선제 조작.
  3. 만족의 영구적 유예: 기호 체계에는 완전 충족이 없으므로 시지프스의 쳇바퀴.
  4. 상징적 교환(Potlatch): 비상품화된 순수 증여와 희생을 통한 코드의 탈구.
```

### 핵심 사회학적 메커니즘

1. **기호 상품 소비 (`CONSUME_SIGN_COMMODITY`)**:
   - 상품은 사용가치($UV$), 교환가치($EV$), 기호가치($SV$)를 갖습니다.
   - 자본 예산($W$)에서 $EV$만큼 차감되며, $W < EV$이면 구매가 거절됩니다(`REJECTED_CAPITAL_INSUFFICIENT`).
   - 사회적 위세 증가:
     $$\Delta S = 	ext{round}(SV 	imes (1.0 + 0.1 	imes \ln(1.0 + UV)), 2)$$
   - 인위적 결핍($L$)의 돌연한 재자극:
     기호는 소비될수록 더 높은 차별화를 요구하므로, 결핍이 해소되지 않고 오히려 갱신됩니다:
     $$L_{	ext{new}} = \min\left(1.0, 	ext{round}\left(L 	imes 0.5 + 0.3 	imes rac{SV}{10.0 + SV}, 4ight)ight)$$
   - 소외 지수($A$) 상승:
     $$\Delta A = 	ext{round}\left(0.05 	imes rac{SV}{10.0 + UV}, 4ight)$$

2. **인위적 결핍 유도 (`SIMULATE_LACK_INDUCTION`)**:
   - 광고 및 마케팅 캠페인은 소비자에게 사회적 뒤처짐의 공포와 유행의 코드 압박($P_c$)을 가합니다:
     $$\Delta L = 	ext{round}(P_c 	imes (1.0 - L) 	imes 0.6, 4)$$
     $$A_{	ext{new}} = \min(1.0, 	ext{round}(A + P_c 	imes 0.1, 4))$$

3. **상징적 교환과 포틀래치 (`SYMBOLIC_EXCHANGE_POTLATCH`)**:
   - 보드리야르와 마르셀 모스(Marcel Mauss)의 인류학적 증여론에 기반하여, 교환가치를 초월한 순수한 증여·희생($G$)을 통해 기호의 코드를 교란합니다.
   - 자본 $W \ge G$인 경우 자본을 소모하여 소외($A$)와 결핍($L$)을 근본적으로 감쇄시킵니다:
     $$\Delta A = 	ext{round}\left(0.25 	imes rac{G}{100.0 + G}, 4ight), \quad \Delta L = 	ext{round}\left(0.30 	imes rac{G}{100.0 + G}, 4ight)$$

4. **사회학적 최종 판정 (Sociological Verdict)**:
   - $A \ge 0.70$ 및 $L \ge 0.50$: `HYPER_CONSUMER_SISYPHUS` (기호의 쳇바퀴에 완전히 포섭된 과잉 소비자).
   - $A \le 0.20$ 및 $L \le 0.20$: `SYMBOLIC_POTLATCH_RESISTANT` (상징적 증여를 통해 기호 코드에서 해방된 저항자).
   - $S \ge 80.0$: `HIGH_PRESTIGE_CODE_SIGNIFIER` (코드 내 최고위 위세를 축적한 상류 기표자).
   - 그 외: `ALIENATED_EVERYDAY_CONSUMER` (일상적 기호 소비의 굴레에 순응하는 대중).

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다.

```json
{
  "consumer_id": "PARIS_BOURGEOIS",
  "capital_budget": 5000.0,
  "social_prestige": 20.0,
  "synthetic_lack": 0.3,
  "alienation_index": 0.25,
  "operations": [
    {"op": "CONSUME_SIGN_COMMODITY", "item_name": "DESIGNER_WATCH", "use_value": 2.0, "exchange_value": 800.0, "sign_value": 50.0},
    {"op": "SIMULATE_LACK_INDUCTION", "campaign_name": "VOGUE_SPRING_ISSUE", "code_pressure": 0.7},
    {"op": "SYMBOLIC_EXCHANGE_POTLATCH", "gift_sacrifice_value": 500.0}
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 다음 스키마의 단일 JSON 객체를 공백 없이 출력합니다:

```json
{
  "consumer_id": "PARIS_BOURGEOIS",
  "initial_state": {
    "capital_budget": 5000.0,
    "social_prestige": 20.0,
    "synthetic_lack": 0.3,
    "alienation_index": 0.25
  },
  "final_state": {
    "capital_budget": 3700.0,
    "social_prestige": 75.49,
    "synthetic_lack": 0.402,
    "alienation_index": 0.32,
    "sociological_verdict": "ALIENATED_EVERYDAY_CONSUMER"
  },
  "stats": {
    "commodities_purchased": 1,
    "failed_purchases": 0,
    "marketing_exposures": 1,
    "symbolic_potlatches": 1,
    "total_exchange_value_spent": 800.0,
    "total_sign_value_acquired": 50.0
  },
  "op_log": [
    {
      "op": "CONSUME_SIGN_COMMODITY",
      "item_name": "DESIGNER_WATCH",
      "status": "SIGN_CONSUMED_CODE_REINFORCED",
      "remaining_capital": 4200.0,
      "prestige_gained": 55.49,
      "new_synthetic_lack": 0.4,
      "new_alienation": 0.4583
    }
  ]
}
```
