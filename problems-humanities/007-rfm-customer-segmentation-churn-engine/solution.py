import sys
import json
from datetime import datetime

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

def parse_date(d_str):
    return datetime.strptime(d_str, "%Y-%m-%d")

def get_rfm_scores(recency_days, frequency, monetary):
    # Recency score
    if recency_days <= 14:
        r_score = 5
    elif recency_days <= 30:
        r_score = 4
    elif recency_days <= 60:
        r_score = 3
    elif recency_days <= 90:
        r_score = 2
    else:
        r_score = 1

    # Frequency score
    if frequency >= 10:
        f_score = 5
    elif frequency >= 6:
        f_score = 4
    elif frequency >= 3:
        f_score = 3
    elif frequency == 2:
        f_score = 2
    else:
        f_score = 1

    # Monetary score
    if monetary >= 1000000:
        m_score = 5
    elif monetary >= 500000:
        m_score = 4
    elif monetary >= 200000:
        m_score = 3
    elif monetary >= 50000:
        m_score = 2
    else:
        m_score = 1

    return r_score, f_score, m_score

def classify_segment(r, f, m):
    if r >= 4 and f >= 4 and m >= 4:
        return "CHAMPIONS", "전담 매니저 배정, 신제품 VIP 선공개 초대장 및 감사 리워드 발송"
    elif r >= 3 and f >= 3:
        return "LOYAL_CUSTOMERS", "업셀링 및 크로스셀링 추천, 멤버십 승급 혜택 안내"
    elif r >= 4 and f in (2, 3):
        return "POTENTIAL_LOYALISTS", "재구매 유도 마일리지 적립 이벤트 및 리뷰 작성 혜택 제공"
    elif r >= 4 and f == 1:
        return "NEW_CUSTOMERS", "온보딩 웰컴 쿠폰북 및 인기 카테고리 큐레이션 안내"
    elif r <= 2 and f >= 3 and m >= 3:
        return "AT_RISK_HIGH_VALUE", "[긴급] 컴백 감사 30% 특별 할인 쿠폰 및 개인화 안부 메시지 발송"
    elif r in (2, 3) and f <= 2:
        return "ABOUT_TO_SLEEP", "기간 한정 무료배송 쿠폰 및 장바구니 리마인드 알림톡 발송"
    elif r == 1 and f <= 2:
        return "HIBERNATING_LOST", "휴면 계정 전환 예고 알림 및 시즌 파격 세일 카탈로그 발송"
    else:
        return "PROMISCUOUS_BARGAIN_HUNTERS", "초특가 반짝 할인 알림 및 가성비 번들 상품 추천"

def analyze_rfm_cohorts(input_data):
    analysis_date_str = input_data.get("analysis_date", "2026-10-31")
    analysis_date = parse_date(analysis_date_str)
    company_name = input_data.get("company_name", "ZeliShop Global")
    churn_threshold = int(input_data.get("churn_threshold_days", 90))
    customers = input_data.get("customers", [])

    customer_results = []
    segment_counts = {}
    total_revenue = 0

    for cust in customers:
        c_id = cust.get("customer_id")
        c_name = cust.get("customer_name")
        orders = cust.get("orders", [])

        valid_orders = []
        for ord_info in orders:
            amt = ord_info.get("amount", 0)
            d_str = ord_info.get("order_date")
            if amt > 0 and d_str:
                d_val = parse_date(d_str)
                if d_val <= analysis_date:
                    valid_orders.append((d_val, amt))

        if not valid_orders:
            segment = "INACTIVE_LEAD"
            action = "신규 가입 환영 첫 구매 10,000원 쿠폰 발송"
            churn_risk = 1.0
            r_score, f_score, m_score = 1, 0, 0
            recency_days = 999
            frequency = 0
            monetary = 0
        else:
            valid_orders.sort(key=lambda x: x[0])
            latest_date = valid_orders[-1][0]
            recency_days = (analysis_date - latest_date).days
            frequency = len(valid_orders)
            monetary = sum(x[1] for x in valid_orders)

            r_score, f_score, m_score = get_rfm_scores(recency_days, frequency, monetary)
            segment, action = classify_segment(r_score, f_score, m_score)
            churn_risk = round(min(1.0, recency_days / churn_threshold), 2)

        total_revenue += monetary
        segment_counts[segment] = segment_counts.get(segment, 0) + 1

        customer_results.append({
            "customer_id": c_id,
            "customer_name": c_name,
            "metrics": {
                "recency_days": recency_days,
                "frequency": frequency,
                "monetary": monetary
            },
            "rfm_scores": {
                "r_score": r_score,
                "f_score": f_score,
                "m_score": m_score,
                "rfm_code": f"{r_score}{f_score}{m_score}"
            },
            "segment": segment,
            "churn_risk": churn_risk,
            "marketing_action": action
        })

    customer_results.sort(key=lambda x: x["metrics"]["monetary"], reverse=True)

    vip_ratio = round((segment_counts.get("CHAMPIONS", 0) + segment_counts.get("LOYAL_CUSTOMERS", 0)) / len(customers) * 100, 1) if customers else 0.0
    at_risk_ratio = round((segment_counts.get("AT_RISK_HIGH_VALUE", 0) + segment_counts.get("ABOUT_TO_SLEEP", 0)) / len(customers) * 100, 1) if customers else 0.0

    diagnostics = [
        f"분석 기준일({analysis_date_str}) 총 {len(customers)}명 고객의 누적 매출은 {total_revenue:,}원입니다.",
        f"핵심 VIP/충성 고객 비중 {vip_ratio}%, 이탈 위험군 비중 {at_risk_ratio}%.",
        f"이탈 위기 고가치 고객(AT_RISK_HIGH_VALUE) {segment_counts.get('AT_RISK_HIGH_VALUE', 0)}명에 대한 긴급 윈백(Win-Back) 캠페인이 권장됩니다."
    ]

    return {
        "analysis_date": analysis_date_str,
        "company_name": company_name,
        "total_customers": len(customers),
        "total_revenue": total_revenue,
        "segment_distribution": segment_counts,
        "diagnostics": diagnostics,
        "customer_segments": customer_results
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    result = analyze_rfm_cohorts(data)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
