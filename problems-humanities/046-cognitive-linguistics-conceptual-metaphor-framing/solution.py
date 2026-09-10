# -*- coding: utf-8 -*-
"""
ZeliJudge Humanities Track Problem #046: Cognitive Linguistics Conceptual Metaphor Theory & Political Framing
https://github.com/hajunho/ZeliJudge
"""

import sys
import json
import re

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

def tokenize(text):
    return re.findall(r'[a-zA-Z\-]+', text.lower())

def analyze_metaphor_and_framing(data):
    config = data.get("config", {})
    frame_diff_threshold = config.get("frame_classification_threshold", 0.15)

    source_lexicon = data.get("source_domain_lexicon", {})
    clean_lexicon = {k: set(w.lower() for w in v) for k, v in source_lexicon.items()}

    metaphor_schemata = data.get("metaphor_schemata", [])
    documents = data.get("documents", [])

    results = []

    for doc in documents:
        doc_id = doc.get("doc_id")
        text = doc.get("text", "")
        tokens = tokenize(text)
        token_count = max(1, len(tokens))

        domain_counts = {}
        for domain, word_set in clean_lexicon.items():
            matched_words = [w for w in tokens if w in word_set]
            domain_counts[domain] = {
                "count": len(matched_words),
                "frequency_pct": round((len(matched_words) / token_count) * 100.0, 2),
                "matched_words": sorted(list(set(matched_words)))
            }

        active_metaphors = []
        for schema in metaphor_schemata:
            m_id = schema.get("id")
            src = schema.get("source")
            target_kw = set(w.lower() for w in schema.get("context_keywords", []))

            target_matches = [w for w in tokens if w in target_kw]
            src_info = domain_counts.get(src, {"count": 0, "frequency_pct": 0.0, "matched_words": []})

            if len(target_matches) > 0 and src_info["count"] > 0:
                active_metaphors.append({
                    "metaphor_id": m_id,
                    "target_cues": sorted(list(set(target_matches))),
                    "source_cues": src_info["matched_words"],
                    "metaphor_strength": round((src_info["count"] + len(target_matches)) / token_count * 100.0, 2)
                })

        strict_info = domain_counts.get("STRICT_FATHER", {"count": 0, "matched_words": []})
        nurturant_info = domain_counts.get("NURTURANT_PARENT", {"count": 0, "matched_words": []})

        c_strict = strict_info["count"]
        c_nurturant = nurturant_info["count"]
        total_frame = c_strict + c_nurturant

        if total_frame == 0:
            frame_label = "NEUTRAL_UNFRAMED"
            frame_bias = 0.0
        else:
            frame_bias = round((c_strict - c_nurturant) / total_frame, 2)
            if frame_bias > frame_diff_threshold:
                frame_label = "STRICT_FATHER_FRAME"
            elif frame_bias < -frame_diff_threshold:
                frame_label = "NURTURANT_PARENT_FRAME"
            else:
                frame_label = "BICONCEPTUAL_CONTESTED_FRAME"

        results.append({
            "doc_id": doc_id,
            "word_count": len(tokens),
            "activated_metaphors": active_metaphors,
            "framing_analysis": {
                "detected_frame": frame_label,
                "frame_bias_index": frame_bias,
                "strict_father_cues": strict_info["matched_words"],
                "nurturant_parent_cues": nurturant_info["matched_words"]
            }
        })

    return {
        "analyzed_documents_count": len(documents),
        "document_results": results
    }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    result = analyze_metaphor_and_framing(data)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))

if __name__ == "__main__":
    main()
