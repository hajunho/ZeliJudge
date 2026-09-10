import sys
import re
import math
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

STOPWORDS = {
    "이", "그", "저", "것", "수", "등", "및", "에", "를", "은", "는", "과", "와", 
    "로", "으로", "에서", "에게", "의", "도", "만", "가", "을", "한", "하다", "있다", "되다"
}

CLICKBAIT_PATTERNS = [
    "충격", "경악", "알고 보니", "알고보니", "발칵", "숨겨진 진실", "결국", "눈물", 
    "이럴 수가", "이럴수가", "초비상", "경고", "대반전", "폭탄 선언", "충격 고백", "경천동지"
]

NEGATION_CUES = [
    "아니다", "기각", "사실무근", "부인", "허위", "오보", "반박", "해명", "없음", "가짜"
]

def tokenize(text):
    cleaned = re.sub(r"[^\w\s가-힣]", " ", text)
    tokens = [t.strip() for t in cleaned.split() if len(t.strip()) > 1]
    filtered = [t for t in tokens if t not in STOPWORDS]
    return filtered

def compute_cosine_similarity(tokens1, tokens2):
    if not tokens1 or not tokens2:
        return 0.0
    tf1 = {}
    for t in tokens1:
        tf1[t] = tf1.get(t, 0) + 1
    tf2 = {}
    for t in tokens2:
        tf2[t] = tf2.get(t, 0) + 1

    all_keys = set(tf1.keys()) | set(tf2.keys())
    dot = sum(tf1.get(k, 0) * tf2.get(k, 0) for k in all_keys)
    norm1 = math.sqrt(sum(v * v for v in tf1.values()))
    norm2 = math.sqrt(sum(v * v for v in tf2.values()))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return round(dot / (norm1 * norm2), 4)

def check_negation_flip(headline, body_text):
    h_tokens = tokenize(headline)
    b_words = body_text.split()

    for i, word in enumerate(b_words):
        for neg in NEGATION_CUES:
            if neg in word:
                start = max(0, i - 4)
                end = min(len(b_words), i + 5)
                context = " ".join(b_words[start:end])
                for ht in h_tokens:
                    if ht in context:
                        return True, f"헤드라인 핵심어 '{ht}'가 본문 부정 맥락('{context.strip()}')에서 발견됨"
    return False, ""

def analyze_article(input_data):
    article_id = input_data.get("article_id", "ART-000")
    headline = input_data.get("headline", "").strip()
    body = input_data.get("body", "").strip()

    b_words = body.split()
    if len(b_words) < 20:
        return {
            "status": "INSUFFICIENT_ARTICLE_BODY",
            "article_id": article_id,
            "headline": headline,
            "word_count": len(b_words),
            "clickbait_score": 0.0,
            "metrics": {},
            "diagnostics": [
                f"본문 단어 수({len(b_words)}개)가 신뢰성 분석을 위한 최소 기준(20단어)에 미달합니다."
            ],
            "recommendation": "충분한 본문 분량을 확보한 기사만 분석할 수 있습니다."
        }

    h_tokens = tokenize(headline)
    b_tokens = tokenize(body)

    cos_sim = compute_cosine_similarity(h_tokens, b_tokens)

    h_set = set(h_tokens)
    b_set = set(b_tokens)
    matched_keywords = h_set & b_set
    coverage = round(len(matched_keywords) / len(h_set), 4) if h_set else 0.0

    detected_sensational_words = []
    for pattern in CLICKBAIT_PATTERNS:
        if pattern in headline:
            detected_sensational_words.append(pattern)

    exclamations = headline.count("!")
    questions = headline.count("?")
    has_ellipsis = "..." in headline or "…" in headline
    punct_score = min(1.0, (exclamations * 0.25) + (questions * 0.25) + (0.3 if has_ellipsis else 0.0))

    has_flip, flip_reason = check_negation_flip(headline, body)

    sens_score = min(1.0, len(detected_sensational_words) * 0.35)
    cov_penalty = round((1.0 - coverage) * 0.25, 4)
    sim_penalty = round((1.0 - cos_sim) * 0.25, 4)

    clickbait_score = round(min(1.0, (sens_score * 0.30) + (punct_score * 0.20) + cov_penalty + sim_penalty), 4)

    diagnostics = []
    if has_flip:
        status = "MALICIOUS_FAKE_NEWS_MISMATCH"
        diagnostics.append(f"치명적 제목-본문 입장 불일치(Negation Flip) 감지: {flip_reason}.")
        diagnostics.append("헤드라인은 긍정/기정사실로 유도했으나 본문은 이를 명시적으로 부인/기각하고 있습니다.")
        recommendation = "허위·과장 왜곡 기사 판정. 포털 제휴평가위원회에 벌점 부과 및 기사 수정 명령 권고."
    elif clickbait_score >= 0.50:
        status = "SUSPICIOUS_CLICKBAIT_EXAGGERATION"
        if detected_sensational_words:
            diagnostics.append(f"선정적 클릭베이트 수식어 감지: {', '.join(detected_sensational_words)}.")
        if coverage < 0.60:
            diagnostics.append(f"헤드라인 키워드 본문 커버리지 저조 ({round(coverage*100, 1)}%). 미끼용 제목 의심.")
        diagnostics.append(f"종합 클릭베이트 지수 {round(clickbait_score*100, 1)}점 (위험 수위 50점 이상).")
        recommendation = "선정적 낚시성 기사 주의보 발령. 헤드라인을 본문 사실에 기반하여 객관적으로 재작성하십시오."
    else:
        status = "CREDIBLE_REPORTING"
        diagnostics.append(f"헤드라인과 본문 간 내용 일치도 우수(유사도 {cos_sim}, 커버리지 {round(coverage*100, 1)}%).")
        diagnostics.append("저널리즘 윤리 준수 및 신뢰할 수 있는 정상 보도로 판정.")
        recommendation = "정상 송고 승인(Pass)."

    return {
        "status": status,
        "article_id": article_id,
        "headline": headline,
        "word_count": len(b_words),
        "clickbait_score": clickbait_score,
        "metrics": {
            "cosine_similarity": cos_sim,
            "keyword_coverage": coverage,
            "sensational_words_count": len(detected_sensational_words),
            "detected_sensational_words": detected_sensational_words,
            "punctuation_spam_score": punct_score,
            "negation_flip_detected": has_flip
        },
        "diagnostics": diagnostics,
        "recommendation": recommendation
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    result = analyze_article(data)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
