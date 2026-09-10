# #007 [마케터의 마법 지갑: 이커머스 RFM(Recency, Frequency, Monetary) 고객 가치 세분화와 이탈 위험도(Churn Risk) 스코어링 엔진 (Marketing Science: E-commerce RFM Customer Segmentation & Churn Risk Scoring Engine)]

## 1. 장애 및 실무 시나리오

국내 대형 패션·라이프스타일 이커머스 플랫폼의 그로스 마케팅(Growth Marketing) 및 CRM 부서는 매월 수천만 원의 광고비와 마케팅 예산을 쏟아부어 카카오톡 알림톡 및 앱 푸시 메시지를 발송하고 있습니다.

그러나 모든 고객에게 동일한 전면 10% 할인 쿠폰을 무차별 살포(Batch & Blast)하는 주먹구구식 마케팅으로 인해 다음과 같은 심각한 비즈니스 비효율이 발생했습니다:
1. **VIP 단골의 이탈 방치**: 과거 수백만 원어치를 정기적으로 구매하던 최우수 고객이 3달째 방문하지 않고 있음에도, 시스템이 이를 조기에 감지하지 못해 경쟁 플랫폼으로 완전히 이탈해 버림(Silent Churn).
2. **신규 회원의 리텐션 실패**: 어제 첫 구매를 마친 신규 고객에게 적절한 온보딩 큐레이션 대신 무의미한 일반 광고를 보내 재구매 골든타임을 놓침.
3. **체리피커(Cherry Picker) 예산 낭비**: 할인 쿠폰이 있을 때만 초저가 상품을 1번 사고 마는 고객들에게 마케팅 예산이 과도하게 낭비됨.

마케팅 총괄 임원(CMO)은 고객의 구매 이력을 기반으로 고객의 생애 가치(LTV, Customer Lifetime Value)를 과학적으로 측정하고 개인화된 CRM 액션을 즉각 제안하는 **RFM(Recency, Frequency, Monetary) 고객 세분화 및 이탈 위험도(Churn Risk) 스코어링 엔진**을 구축할 것을 지시했습니다.

---

## 2. 경영학·마케팅 과학 및 데이터 분석 이론

### 2.1 RFM 모형의 기본 원리 (Arthur Hughes, 1994)
RFM 분석은 데이터베이스 마케팅에서 고객의 행동 이력을 3가지 핵심 차원으로 정량화하는 고전적이면서도 가장 강력한 프레임워크입니다:
1. **Recency ($R$, 최근성)**: 가장 최근에 구매한 시점부터 분석 기준일까지 경과된 일수(Days). 최근에 구매한 고객일수록 다시 방문할 확률이 가장 높습니다.
2. **Frequency ($F$, 구매 빈도)**: 분석 기간 동안 유효 구매 횟수(Count). 구매 횟수가 많을수록 브랜드에 대한 신뢰와 충성도가 높습니다.
3. **Monetary ($M$, 구매 금액)**: 고객이 지출한 총 누적 결제 금액(Revenue). 플랫폼 수익 창출 기여도를 나타냅니다.

```
+-------------------------------------------------------------------------+
|                         RFM 5등급 스코어링 기준표                         |
+-------+---------------------+--------------------+----------------------+
| 점수   | Recency (최근성)    | Frequency (빈도)    | Monetary (누적금액)  |
+-------+---------------------+--------------------+----------------------+
|   5   | 14일 이내 (초밀착)   | 10회 이상 (단골)    | 1,000,000원 이상     |
|   4   | 15일 ~ 30일 이내    | 6회 ~ 9회          | 500,000원 ~ 999,999원|
|   3   | 31일 ~ 60일 이내    | 3회 ~ 5회          | 200,000원 ~ 499,999원|
|   2   | 61일 ~ 90일 이내    | 2회               | 50,000원 ~ 199,999원 |
|   1   | 90일 초과 (이탈위험)| 1회 (단발성)        | 50,000원 미만        |
+-------+---------------------+--------------------+----------------------+
```

### 2.2 고객 세그먼트 분류 규칙
- **`CHAMPIONS` (최상위 VIP)**: $R \ge 4, F \ge 4, M \ge 4$ (최근에도 샀고, 자주 사고, 많이 쓰는 최고의 자산)
- **`LOYAL_CUSTOMERS` (충성 고객)**: $R \ge 3, F \ge 3$ (안정적인 재구매 충성 고객)
- **`POTENTIAL_LOYALISTS` (잠재 충성 고객)**: $R \ge 4, F \in \{2, 3\}$ (최근 연달아 구매하며 단골로 발전 중인 고객)
- **`NEW_CUSTOMERS` (신규 고객)**: $R \ge 4, F = 1$ (최근 첫 구매를 마친 유입 고객)
- **`AT_RISK_HIGH_VALUE` (이탈 위기 VIP)**: $R \le 2, F \ge 3, M \ge 3$ (과거 대형 고객이었으나 최근 발길을 뚝 끊음! 긴급 방어 필요)
- **`ABOUT_TO_SLEEP` (휴면 직전 고객)**: $R \in \{2, 3\}, F \le 2$ (구매력 낮고 슬슬 잊혀져 가는 고객)
- **`HIBERNATING_LOST` (이탈/동면 고객)**: $R = 1, F \le 2$ (오랫동안 방문하지 않은 이탈 유저)
- **`INACTIVE_LEAD` (미구매 가입자)**: 유효 구매 이력이 전혀 없는 가입자

### 2.3 이탈 위험도 (Churn Risk)
이탈 임계일수($T_{churn}$, 기본 90일) 대비 경과일수 비율:
$$	ext{Churn Risk} = \min\left(1.0, rac{R}{T_{churn}}ight)$$

---

## 3. 입력 사양 (Input Specification)

표준 입력(stdin)으로 다음 구조의 JSON 객체가 주어집니다:

```json
{
  "analysis_date": "2026-10-31",
  "company_name": "ZeliShop Korea",
  "churn_threshold_days": 90,
  "customers": [
    {
      "customer_id": "CUST-001",
      "customer_name": "강챔프",
      "orders": [
        { "order_date": "2026-10-25", "amount": 250000 },
        { "order_date": "2026-10-20", "amount": 250000 }
      ]
    }
  ]
}
```

### 데이터 정제 및 예외 처리:
1. `amount <= 0`인 취소/환불 주문이나 결제 금액 0원인 건은 집계에서 제외합니다.
2. `order_date > analysis_date`인 미래 일자 주문은 집계에서 제외합니다.
3. 유효 주문이 0건인 고객은 `INACTIVE_LEAD`로 처리하며 `churn_risk = 1.0`을 부여합니다.

---

## 4. 출력 사양 (Output Specification)

표준 출력(stdout)으로 다음 스키마의 JSON을 한 줄로 출력합니다:

```json
{
  "analysis_date": "2026-10-31",
  "company_name": "ZeliShop Korea",
  "total_customers": 5,
  "total_revenue": 3755000,
  "segment_distribution": {
    "CHAMPIONS": 1,
    "LOYAL_CUSTOMERS": 1,
    "NEW_CUSTOMERS": 1,
    "AT_RISK_HIGH_VALUE": 1,
    "HIBERNATING_LOST": 1
  },
  "diagnostics": [
    "분석 기준일(2026-10-31) 총 5명 고객의 누적 매출은 3,755,000원입니다.",
    "핵심 VIP/충성 고객 비중 40.0%, 이탈 위험군 비중 20.0%.",
    "이탈 위기 고가치 고객(AT_RISK_HIGH_VALUE) 1명에 대한 긴급 윈백(Win-Back) 캠페인이 권장됩니다."
  ],
  "customer_segments": [
    {
      "customer_id": "CUST-001",
      "customer_name": "강챔프",
      "metrics": {
        "recency_days": 10,
        "frequency": 7,
        "monetary": 1750000
      },
      "rfm_scores": {
        "r_score": 5,
        "f_score": 4,
        "m_score": 5,
        "rfm_code": "545"
      },
      "segment": "CHAMPIONS",
      "churn_risk": 0.11,
      "marketing_action": "전담 매니저 배정, 신제품 VIP 선공개 초대장 및 감사 리워드 발송"
    }
  ]
}
```
