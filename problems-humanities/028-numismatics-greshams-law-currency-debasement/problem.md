# 문제 #028: 악화(Bad Money)가 양화(Good Money)를 어떻게 시장에서 완전히 몰아낼까요?!: 화폐사(Monetary History)와 화폐학(Numismatics): 니콜 오렘·코페르니쿠스·그레셤의 법칙(Gresham's Law), 헨리 8세 대개악(Great Debasement), 금은 복본위제(Bimetallism) 차익 거래 및 화폐 유통·퇴장(Hoarding) 시뮬레이터

## 1. 개요 (Story & Context)
> **"악화가 양화를 구축(驅逐)한다 (Bad money drives out good)."**  
> — 토머스 그레셤(Sir Thomas Gresham, 1558), 엘리자베스 1세 여왕에게 보낸 서한

화폐 경제학 역사상 가장 유명한 격언 중 하나인 **‘그레셤의 법칙(Gresham's Law)’**은 사실 그레셤 이전 14세기 프랑스의 철학자 니콜 오렘(Nicole Oresme, 1355)과 16세기 폴란드의 천문학자 니콜라우스 코페르니쿠스(Nicolaus Copernicus, 1526 《화폐 주조론(Monetae cudendae ratio)》)가 먼저 정교하게 규명한 인간 경제 행동의 기본 법칙입니다.

중세와 근대 유럽의 군주들은 재정 적자와 전쟁 비용을 메우기 위해 끊임없이 화폐를 개악(Debasement)했습니다.
가장 대표적인 사건이 바로 잉글랜드 튜더 왕조 헨리 8세의 **‘화폐 대개악(Great Debasement, 1544–1551)’**입니다. 헨리 8세는 프랑스·스코틀랜드와의 전쟁 자금을 마련하기 위해 기존 순도 92.5%의 스털링 은화(Groat, 4펜스)를 은 함유율 33% 이하의 조악한 구리 합금 은화로 대량 변조 주조했습니다. 얼마 지나지 않아 동전 표면의 얇은 은 도금이 벗겨지면서 헨리 8세의 코 부분이 붉은 구리색으로 드러나 백성들로부터 **"구리코 영감(Old Coppernose)"**이라는 조롱을 받았습니다.

이때 놀라운 시장 현상이 발생했습니다:
정부가 정한 법정 액면가(Nominal Face Value)는 신화나 구화나 똑같이 4펜스였지만, 백성들과 상인들은 실제 귀금속 내재가치(Intrinsic Bullion Value)를 꿰뚫어보고 있었습니다. 사람들은 순은이 듬뿍 들어있는 예전 양화(Good Money)는 장롱 깊숙이 숨겨두거나(Hoarding) 녹여서 해외로 밀수출했고, 시장에서 물건을 살 때는 오직 구리가 잔뜩 섞인 헨리 8세의 악화(Bad Money)만을 꺼내 지불했습니다! 그 결과, 런던 시장에서는 좋은 은화가 자취를 완전히 감추고 불량 주화만 넘쳐나 극심한 인플레이션이 초래되었습니다.

또한, 금과 은을 동시에 화폐로 사용하는 **금은 복본위제(Bimetallism)** 환경에서는 조폐국의 법정 교환 비율(Mint Legal Ratio)과 국제 귀금속 시장의 실질 시세(Market Commercial Ratio)가 조금만 어긋나도, 대규모 금-은 삼각 차익 거래(Triangular Arbitrage)가 발생하여 국가 전체의 귀금속이 국외로 유출되기도 했습니다.

여러분은 경제사 및 화폐학(Numismatics) 전산 연구원으로서, 주화의 내재가치 평가 및 양화·악화 판별, 금은 복본위제 차익 거래 계산, 그리고 다회차 결제 시 악화 우선 지출 및 양화 퇴장(Hoarding) 과정을 완벽하게 모형화하는 **그레셤의 법칙 경제사 시뮬레이션 엔진**을 구축해야 합니다!

---

## 2. 연산 규칙 및 입출력 규격

### 2.1 주화 내재가치(Intrinsic Bullion Value) 평가 (`mode: "evaluate_coins"`)
- 주화 $i$의 순 귀금속 중량(Fine Weight):
  $$\text{fine\_weight\_grams} = \text{round}(\text{gross\_weight\_grams} \times \text{fineness}, 4)$$
- 주화 $i$의 내재 귀금속 가치(Intrinsic Bullion Value):
  $$\text{intrinsic\_value} = \text{round}(\text{fine\_weight\_grams} \times \text{price\_per\_gram}, 4)$$
- 액면가 대비 괴리율(Disparity Ratio):
  $$\text{disparity\_ratio} = \text{round}\left(\frac{\text{intrinsic\_value}}{\text{nominal\_face\_value}}, 4\right)$$
- 분류 및 권고 조치:
  - $\text{disparity\_ratio} > 1.0001$: `"UNDERVALUED_GOOD_MONEY"` / `"HOARD_OR_MELT"` (법정 화폐 가치보다 금속 가치가 높아 퇴장 또는 용해 수출)
  - $\text{disparity\_ratio} < 0.9999$: `"OVERVALUED_BAD_MONEY"` / `"SPEND_IN_TRANSACTION"` (법정 화폐 가치가 금속 가치보다 과대평가되어 시장 결제에 집중 유통)
  - 그 외: `"PAR_VALUE"` / `"CIRCULATE_AT_PAR"`

### 2.2 금은 복본위제 차익 거래 (`mode: "bimetallic_arbitrage"`)
- 조폐국 법정 비율: $1 \text{ 금} = R_{\text{mint}} \text{ 은}$
- 국제 시장 상업 비율: $1 \text{ 금} = R_{\text{market}} \text{ 은}$
- 거래 수수료 및 주조세(Seigniorage) 비율: $\text{cost\_pct}$
- **차익 거래 전략**:
  1. $R_{\text{market}} > R_{\text{mint}}$ 인 경우:
     - 금이 조폐국에서는 저평가, 시장에서는 고평가되어 있습니다.
     - 전략: `"BRING_SILVER_TO_MINT_EXPORT_GOLD_TO_MARKET"` (은을 조폐국에 가져가 금으로 주조한 뒤, 금을 시장에 팔아 은을 획득).
     - 수익 승수: $\text{multiplier} = (R_{\text{market}} / R_{\text{mint}}) \times (1 - \text{cost\_pct})$
  2. $R_{\text{market}} < R_{\text{mint}}$ 인 경우:
     - 은이 시장에서 고평가, 조폐국에서 저평가되어 있습니다.
     - 전략: `"BRING_GOLD_TO_MINT_EXPORT_SILVER_TO_MARKET"` (금을 조폐국에 가져가 은으로 바꾼 뒤, 은을 시장에 팔아 금을 획득).
     - 수익 승수: $\text{multiplier} = (R_{\text{mint}} / R_{\text{market}}) \times (1 - \text{cost\_pct})$
  3. $\text{profit\_pct} = \text{round}((\text{multiplier} - 1.0) \times 100, 4)$
  4. $\text{profit\_pct} > 0$ 이면 $\text{is\_arbitrage\_profitable} = \text{True}$, 아니면 $\text{False}$ (전략은 `"UNPROFITABLE_DUE_TO_FRICTION"` 또는 `"NO_ARBITRAGE"`).

### 2.3 그레셤 유통·퇴장 시뮬레이션 (`mode: "simulate_greshams_circulation"`)
- 지갑에 보유한 개별 주화 목록(`initial_wallet`)과 결제 요청 목록(`transactions`)이 주어집니다.
- 매 결제(`amount_due`) 시:
  - 구매자는 합계 액면가($\sum \text{face\_value}$)가 정확히 `amount_due`와 일치하는 부분집합 중, **소모되는 총 내재가치($\sum \text{intrinsic\_value}$)가 최소가 되는 조합**을 우선 선택하여 지불합니다 (Gresham's Law: 최악의 돈을 먼저 지불).
  - 지불에 사용된 주화는 지갑에서 제거됩니다.
  - 결제 불가능 시 `status: "FAILED_INSUFFICIENT_FUNDS"`.
- 모든 결제가 끝난 후 지갑에 남은 주화(`retained_hoard`)의 구성, 잔여 액면가, 잔여 내재가치 및 보존된 주화의 품질 비율(`hoard_quality_ratio = total_intrinsic / total_face`)을 산출합니다.
