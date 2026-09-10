import sys
import re
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

def normalize_text(text):
    # Remove special characters except alphanumeric and Korean
    cleaned = re.sub(r"[^\w\s가-힣]", " ", text)
    cleaned = " ".join(cleaned.split())
    return cleaned.strip()

def custom_hash(s):
    # Deterministic polynomial rolling hash mod 10^9 + 7
    h = 0
    mod = 1000000007
    for c in s:
        h = (h * 31 + ord(c)) % mod
    return h

def get_winnowing_fingerprints(text, k=5, w=4):
    if len(text) < k:
        return []

    hashes = []
    for i in range(len(text) - k + 1):
        gram = text[i:i+k]
        h = custom_hash(gram)
        hashes.append((h, i))

    if not hashes:
        return []

    if len(hashes) < w:
        min_item = min(hashes, key=lambda x: (x[0], -x[1]))
        return [min_item]

    fingerprints = []
    last_selected_pos = None

    for i in range(len(hashes) - w + 1):
        window = hashes[i:i+w]
        min_val = min(window, key=lambda x: (x[0], -x[1]))
        if last_selected_pos != min_val[1]:
            fingerprints.append(min_val)
            last_selected_pos = min_val[1]

    return fingerprints

def analyze_plagiarism(input_data):
    doc_id = input_data.get("document_id", "DOC-UNKNOWN")
    doc_title = input_data.get("document_title", "Untitled Document")
    query_text = input_data.get("query_text", "")
    reference_corpus = input_data.get("reference_corpus", [])
    config = input_data.get("config", {})

    k = config.get("k_gram", 5)
    w = config.get("window_size", 4)
    threshold = config.get("similarity_threshold", 0.20)

    norm_query = normalize_text(query_text)
    if len(norm_query) < (k + w - 1):
        return {
            "status": "INSUFFICIENT_TEXT_LENGTH",
            "document_id": doc_id,
            "document_title": doc_title,
            "text_length": len(norm_query),
            "plagiarism_ratio": 0.0,
            "matched_fingerprints_count": 0,
            "total_fingerprints_count": 0,
            "reference_matches": [],
            "diagnostics": [
                f"정규화된 문서 길이({len(norm_query)}자)가 최소 분석 기준({k+w-1}자)에 미달합니다."
            ],
            "recommendation": "최소 분석 기준 이상의 온전한 텍스트를 제출하십시오."
        }

    q_fps = get_winnowing_fingerprints(norm_query, k=k, w=w)
    total_q_fps = len(q_fps)
    q_hash_set = set(h for h, pos in q_fps)

    global_matched_hashes = set()
    ref_matches = []

    for ref in reference_corpus:
        r_id = ref.get("doc_id")
        r_title = ref.get("doc_title")
        r_text = ref.get("text", "")

        norm_ref = normalize_text(r_text)
        r_fps = get_winnowing_fingerprints(norm_ref, k=k, w=w)
        r_hash_set = set(h for h, pos in r_fps)

        intersect = q_hash_set & r_hash_set
        union = q_hash_set | r_hash_set

        jaccard = round(len(intersect) / len(union), 4) if union else 0.0
        containment = round(len(intersect) / len(q_hash_set), 4) if q_hash_set else 0.0

        if len(intersect) > 0:
            global_matched_hashes.update(intersect)
            ref_matches.append({
                "doc_id": r_id,
                "doc_title": r_title,
                "jaccard_similarity": jaccard,
                "containment_ratio": containment,
                "matched_fingerprints": len(intersect)
            })

    ref_matches.sort(key=lambda x: x["containment_ratio"], reverse=True)

    matched_count = len(global_matched_hashes)
    plag_ratio = round(matched_count / total_q_fps, 4) if total_q_fps > 0 else 0.0

    diagnostics = []
    if plag_ratio >= 0.50:
        status = "CRITICAL_PLAGIARISM_DETECTED"
        diagnostics.append(f"전체 핑거프린트의 {round(plag_ratio*100, 1)}%가 기존 코퍼스와 일치합니다. 심각한 저작권 침해 및 복사-붙여넣기(Copy-Paste) 표절 의심.")
        recommendation = "학위 논문 심사 보류 또는 학술지 게재 철회 권고. 연구윤리위원회 징계 회부 대상."
    elif plag_ratio >= threshold:
        status = "SUSPICIOUS_HIGH_SIMILARITY"
        diagnostics.append(f"전체 핑거프린트의 {round(plag_ratio*100, 1)}%가 참고문헌과 중복됩니다. 출처 미표기 및 부적절한 인용 가능성 존재.")
        recommendation = "인용 표기(Citation) 누락 여부 확인 및 소명 자료 제출 요구."
    else:
        status = "ACADEMIC_INTEGRITY_CLEAR"
        diagnostics.append(f"표절 유사도 {round(plag_ratio*100, 1)}% (기준선 {round(threshold*100, 1)}% 미만). 독창적 저작물로 판정.")
        recommendation = "연구윤리 기준 통과(Clearance Granted)."

    return {
        "status": status,
        "document_id": doc_id,
        "document_title": doc_title,
        "text_length": len(norm_query),
        "plagiarism_ratio": plag_ratio,
        "matched_fingerprints_count": matched_count,
        "total_fingerprints_count": total_q_fps,
        "reference_matches": ref_matches,
        "diagnostics": diagnostics,
        "recommendation": recommendation
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    result = analyze_plagiarism(data)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
