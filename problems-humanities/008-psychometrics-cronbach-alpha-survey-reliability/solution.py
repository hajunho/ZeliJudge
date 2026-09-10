import sys
import math
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

def sample_variance(arr):
    n = len(arr)
    if n <= 1:
        return 0.0
    mean = sum(arr) / n
    return sum((x - mean) ** 2 for x in arr) / (n - 1)

def pearson_corr(x, y):
    n = len(x)
    if n <= 1:
        return 0.0
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    num = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
    den_x = sum((x[i] - mean_x) ** 2 for i in range(n))
    den_y = sum((y[i] - mean_y) ** 2 for i in range(n))
    den = math.sqrt(den_x * den_y)
    if den == 0:
        return 0.0
    return num / den

def compute_cronbach(item_arrays):
    k = len(item_arrays)
    if k <= 1:
        return 0.0
    n = len(item_arrays[0])
    if n <= 1:
        return 0.0

    item_vars = [sample_variance(arr) for arr in item_arrays]
    sum_item_vars = sum(item_vars)

    total_scores = [sum(item_arrays[j][i] for j in range(k)) for i in range(n)]
    total_var = sample_variance(total_scores)

    if total_var == 0:
        return 0.0

    alpha = (k / (k - 1)) * (1.0 - (sum_item_vars / total_var))
    return round(alpha, 4)

def analyze_survey_reliability(input_data):
    survey_id = input_data.get("survey_id", "SURVEY-000")
    survey_title = input_data.get("survey_title", "Untitled Survey")
    scale_points = int(input_data.get("scale_points", 5))
    items = input_data.get("items", [])
    responses = input_data.get("responses", [])

    k = len(items)
    n = len(responses)

    if n < 10:
        return {
            "status": "INSUFFICIENT_SAMPLE_SIZE",
            "survey_id": survey_id,
            "survey_title": survey_title,
            "sample_size": n,
            "items_count": k,
            "cronbach_alpha": 0.0,
            "item_analysis": [],
            "diagnostics": [
                f"표본 수({n}명)가 신뢰도 분석을 위한 최소 기준(10명)에 미달합니다."
            ],
            "recommendation": "최소 10명 이상의 응답 데이터를 수집하십시오."
        }

    item_id_list = [it["item_id"] for it in items]
    reverse_map = {it["item_id"]: it.get("is_reverse_scored", False) for it in items}

    item_arrays = [[] for _ in range(k)]

    for resp in responses:
        ans_dict = resp.get("answers", {})
        for j, it_id in enumerate(item_id_list):
            raw_val = float(ans_dict.get(it_id, 3))
            if reverse_map.get(it_id, False):
                clean_val = (scale_points + 1) - raw_val
            else:
                clean_val = raw_val
            item_arrays[j].append(clean_val)

    overall_alpha = compute_cronbach(item_arrays)
    total_scores = [sum(item_arrays[j][i] for j in range(k)) for i in range(n)]

    item_analysis = []
    best_item_to_remove = None
    max_alpha_gain = 0.0

    for j in range(k):
        it_id = item_id_list[j]
        sub_item_arrays = [item_arrays[m] for m in range(k) if m != j]
        alpha_if_deleted = compute_cronbach(sub_item_arrays) if k > 2 else 0.0

        sub_totals = [total_scores[i] - item_arrays[j][i] for i in range(n)]
        it_corr = round(pearson_corr(item_arrays[j], sub_totals), 4)

        gain = round(alpha_if_deleted - overall_alpha, 4)
        if gain > max_alpha_gain:
            max_alpha_gain = gain
            best_item_to_remove = it_id

        item_mean = round(sum(item_arrays[j]) / n, 2)
        item_var = round(sample_variance(item_arrays[j]), 4)

        item_analysis.append({
            "item_id": it_id,
            "is_reverse_scored": reverse_map[it_id],
            "mean": item_mean,
            "variance": item_var,
            "corrected_item_total_correlation": it_corr,
            "alpha_if_deleted": alpha_if_deleted
        })

    diagnostics = []
    purification_cand = None

    if overall_alpha >= 0.80:
        status = "EXCELLENT_RELIABILITY"
        diagnostics.append(f"크론바흐 알파 계수 {overall_alpha}로 내적 일관성 신뢰도가 매우 우수합니다.")
        recommendation = "모든 문항이 동일한 심리적 구인을 일관되게 측정하고 있으므로 문항 수정 없이 본 분석(요인분석/회귀분석)에 활용하십시오."
    elif overall_alpha >= 0.70:
        status = "ACCEPTABLE_RELIABILITY"
        diagnostics.append(f"크론바흐 알파 계수 {overall_alpha}로 학술 논문 및 실무 연구 기준(0.70 이상)을 충족합니다.")
        if best_item_to_remove and max_alpha_gain > 0.02:
            purification_cand = best_item_to_remove
            diagnostics.append(f"문항 '{best_item_to_remove}' 제거 시 알파 계수가 {round(overall_alpha + max_alpha_gain, 4)}로 상승할 수 있습니다.")
            recommendation = f"현재 척도를 그대로 사용 가능하나, 필요 시 문항 '{best_item_to_remove}'의 정제를 검토하십시오."
        else:
            recommendation = "현재 척도 구성으로 신뢰도 기준 통과."
    else:
        status = "UNRELIABLE_POOR_CONSISTENCY"
        diagnostics.append(f"크론바흐 알파 계수 {overall_alpha}로 학술 기준(0.70)에 미달하여 문항 간 내적 일관성이 결여되어 있습니다.")
        if best_item_to_remove and max_alpha_gain > 0:
            purification_cand = best_item_to_remove
            diagnostics.append(f"불량 문항 '{best_item_to_remove}' 제거 시 알파 계수가 {round(overall_alpha + max_alpha_gain, 4)}로 대폭 상승합니다.")
            recommendation = f"문항 '{best_item_to_remove}'(역문항 표기 누락 또는 낮은 상관관계 의심)을 척도에서 삭제하거나 재작성하십시오."
        else:
            recommendation = "척도 전반의 문항 타당도를 재검토하고 파일럿 테스트를 다시 실시하십시오."

    return {
        "status": status,
        "survey_id": survey_id,
        "survey_title": survey_title,
        "sample_size": n,
        "items_count": k,
        "cronbach_alpha": overall_alpha,
        "item_analysis": item_analysis,
        "purification_candidate": purification_cand,
        "diagnostics": diagnostics,
        "recommendation": recommendation
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    result = analyze_survey_reliability(data)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
