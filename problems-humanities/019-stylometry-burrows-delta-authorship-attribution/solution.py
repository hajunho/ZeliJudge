import sys
import json
import re
import math

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

def tokenize(text):
    return re.findall(r"\w+", text.lower())

def solve(data):
    config = data.get("config", {})
    mfw_count = config.get("mfw_count", 50)
    rolling_cfg = config.get("rolling_window")
    
    ref_corpus = data.get("reference_corpus", [])
    target_texts = data.get("target_texts", [])

    author_tokens = {}
    corpus_word_counts = {}

    for entry in ref_corpus:
        author = entry["author"]
        all_toks = []
        for t in entry.get("texts", []):
            toks = tokenize(t)
            all_toks.extend(toks)
        author_tokens[author] = all_toks

        for w in all_toks:
            corpus_word_counts[w] = corpus_word_counts.get(w, 0) + 1

    authors = sorted(author_tokens.keys())
    k = len(authors)

    sorted_words = sorted(corpus_word_counts.keys(), key=lambda w: (-corpus_word_counts[w], w))

    author_rf = {}
    for a in authors:
        toks = author_tokens[a]
        tot = len(toks) if len(toks) > 0 else 1
        cnts = {}
        for w in toks:
            cnts[w] = cnts.get(w, 0) + 1
        author_rf[a] = {w: cnts.get(w, 0) / tot for w in sorted_words}

    valid_mfws = []
    means = {}
    stds = {}
    for w in sorted_words:
        vals = [author_rf[a][w] for a in authors]
        m = sum(vals) / k if k > 0 else 0.0
        var = sum((v - m) ** 2 for v in vals) / k if k > 0 else 0.0
        s = math.sqrt(var)
        if s > 1e-7:
            valid_mfws.append(w)
            means[w] = m
            stds[w] = s
            if len(valid_mfws) == mfw_count:
                break

    mfw_list = valid_mfws
    n_mfw = len(mfw_list)

    author_z = {}
    for a in authors:
        author_z[a] = [(author_rf[a][w] - means[w]) / stds[w] for w in mfw_list]

    def calc_z(doc_tokens):
        tot = len(doc_tokens) if len(doc_tokens) > 0 else 1
        cnts = {}
        for w in doc_tokens:
            cnts[w] = cnts.get(w, 0) + 1
        return [((cnts.get(w, 0) / tot) - means[w]) / stds[w] for w in mfw_list]

    def calc_burrows_delta(z_doc, z_auth):
        if n_mfw == 0:
            return 0.0
        diff_sum = sum(abs(z_doc[i] - z_auth[i]) for i in range(n_mfw))
        return diff_sum / n_mfw

    def calc_cosine_delta(z_doc, z_auth):
        if n_mfw == 0:
            return 0.0
        dot = sum(z_doc[i] * z_auth[i] for i in range(n_mfw))
        norm_d = math.sqrt(sum(z_doc[i] ** 2 for i in range(n_mfw)))
        norm_a = math.sqrt(sum(z_auth[i] ** 2 for i in range(n_mfw)))
        if norm_d < 1e-9 or norm_a < 1e-9:
            return 1.0
        sim = dot / (norm_d * norm_a)
        sim = max(-1.0, min(1.0, sim))
        return 1.0 - sim

    attributions = []
    for tgt in target_texts:
        tgt_id = tgt["id"]
        tgt_tokens = tokenize(tgt["text"])
        z_tgt = calc_z(tgt_tokens)

        b_scores = []
        c_scores = []
        for a in authors:
            b_dist = round(calc_burrows_delta(z_tgt, author_z[a]), 4)
            c_dist = round(calc_cosine_delta(z_tgt, author_z[a]), 4)
            b_scores.append({"author": a, "delta": b_dist})
            c_scores.append({"author": a, "delta": c_dist})

        b_scores.sort(key=lambda x: (x["delta"], x["author"]))
        c_scores.sort(key=lambda x: (x["delta"], x["author"]))

        primary_b_author = b_scores[0]["author"]
        b_margin = round(b_scores[1]["delta"] - b_scores[0]["delta"], 4) if len(b_scores) > 1 else 0.0

        primary_c_author = c_scores[0]["author"]
        c_margin = round(c_scores[1]["delta"] - c_scores[0]["delta"], 4) if len(c_scores) > 1 else 0.0

        rolling_results = None
        if rolling_cfg and rolling_cfg.get("window_size", 0) > 0:
            w_size = rolling_cfg["window_size"]
            if len(tgt_tokens) >= w_size:
                s_size = rolling_cfg.get("step_size", w_size // 2 or 1)
                windows = []
                transitions = []
                prev_winner = None

                total_tgt_words = len(tgt_tokens)
                w_idx = 0
                start = 0
                while start + w_size <= total_tgt_words:
                    w_toks = tgt_tokens[start:start + w_size]
                    z_w = calc_z(w_toks)
                    
                    win_scores = []
                    for a in authors:
                        d = round(calc_burrows_delta(z_w, author_z[a]), 4)
                        win_scores.append((d, a))
                    win_scores.sort(key=lambda x: (x[0], x[1]))
                    curr_winner = win_scores[0][1]

                    windows.append({
                        "window_index": w_idx,
                        "word_offset": start,
                        "predicted_author": curr_winner,
                        "delta": win_scores[0][0]
                    })

                    if prev_winner is not None and curr_winner != prev_winner:
                        transitions.append({
                            "window_index": w_idx,
                            "word_offset": start,
                            "from_author": prev_winner,
                            "to_author": curr_winner
                        })

                    prev_winner = curr_winner
                    start += s_size
                    w_idx += 1

                rolling_results = {
                    "total_windows": len(windows),
                    "windows": windows,
                    "transitions": transitions
                }

        attributions.append({
            "id": tgt_id,
            "word_count": len(tgt_tokens),
            "burrows_delta": {
                "predicted_author": primary_b_author,
                "confidence_margin": b_margin,
                "ranking": b_scores
            },
            "cosine_delta": {
                "predicted_author": primary_c_author,
                "confidence_margin": c_margin,
                "ranking": c_scores
            },
            "rolling_analysis": rolling_results
        })

    return {
        "corpus_metadata": {
            "candidate_authors": authors,
            "total_mfw_selected": n_mfw,
            "top_mfw": mfw_list[:15]
        },
        "attributions": attributions
    }

def main():
    try:
        raw_data = sys.stdin.read().strip()
        if not raw_data:
            return
        data = json.loads(raw_data)
        res = solve(data)
        print(json.dumps(res, ensure_ascii=False))
    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
