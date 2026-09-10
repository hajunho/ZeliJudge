# -*- coding: utf-8 -*-
"""
ZeliJudge Humanities Track Problem #044: Archaeological Seriation & Brainerd-Robinson Matrix Reordering
https://github.com/hajunho/ZeliJudge
"""

import sys
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

def compute_br_similarity(pcts_a, pcts_b, artifact_types):
    diff_sum = sum(abs(pcts_a.get(a, 0.0) - pcts_b.get(a, 0.0)) for a in artifact_types)
    return round(200.0 - diff_sum, 2)

def is_unimodal(seq):
    if len(seq) <= 2:
        return True
    peak_found = False
    for i in range(1, len(seq)):
        diff = seq[i] - seq[i-1]
        if diff > 0.001:
            if peak_found:
                return False
        elif diff < -0.001:
            peak_found = True
    return True

def count_robinson_violations(matrix, order_indices):
    n = len(order_indices)
    violations = 0
    for i in range(n):
        orig_i = order_indices[i]
        # Elements to the right
        for j in range(i + 1, n):
            for k in range(j + 1, n):
                orig_j = order_indices[j]
                orig_k = order_indices[k]
                if matrix[orig_i][orig_j] < matrix[orig_i][orig_k]:
                    violations += 1
        # Elements to the left
        for j in range(i - 1, -1, -1):
            for k in range(j - 1, -1, -1):
                orig_j = order_indices[j]
                orig_k = order_indices[k]
                if matrix[orig_i][orig_j] < matrix[orig_i][orig_k]:
                    violations += 1
    return violations

def solve_seriation(data):
    assemblages = data.get("assemblages", [])
    config = data.get("config", {})
    anchor_site = config.get("anchor_site", None)

    artifact_types = sorted(list({a for s in assemblages for a in s.get("artifacts", {}).keys()}))
    site_names = [s["site_id"] for s in assemblages]
    n = len(assemblages)

    # 1. Compute percentage frequencies
    percentages = []
    for s in assemblages:
        arts = s.get("artifacts", {})
        total = sum(arts.values())
        if total == 0:
            pcts = {a: 0.0 for a in artifact_types}
        else:
            pcts = {a: round((arts.get(a, 0) / total) * 100.0, 2) for a in artifact_types}
        percentages.append(pcts)

    # 2. Compute BR similarity matrix
    br_matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j:
                br_matrix[i][j] = 200.0
            elif i < j:
                sim = compute_br_similarity(percentages[i], percentages[j], artifact_types)
                br_matrix[i][j] = sim
                br_matrix[j][i] = sim

    # 3. Bitmask DP to find max consecutive similarity path
    memo = {}
    parent = {}

    for i in range(n):
        if anchor_site is not None and site_names[i] != anchor_site:
            continue
        memo[(1 << i, i)] = 0.0

    all_masks_by_popcount = [[] for _ in range(n + 1)]
    for mask in range(1, 1 << n):
        all_masks_by_popcount[bin(mask).count('1')].append(mask)

    for k in range(1, n):
        for mask in all_masks_by_popcount[k]:
            for u in range(n):
                if not (mask & (1 << u)):
                    continue
                if (mask, u) not in memo:
                    continue
                curr_score = memo[(mask, u)]
                for v in range(n):
                    if not (mask & (1 << v)):
                        nxt_mask = mask | (1 << v)
                        cand_score = curr_score + br_matrix[u][v]
                        key = (nxt_mask, v)
                        if key not in memo or cand_score > memo[key] + 1e-6:
                            memo[key] = cand_score
                            parent[key] = u
                        elif abs(cand_score - memo[key]) <= 1e-6 and u < parent.get(key, 9999):
                            memo[key] = cand_score
                            parent[key] = u

    full_mask = (1 << n) - 1
    best_score = -1e9
    best_last = -1

    for v in range(n):
        if (full_mask, v) in memo:
            score = memo[(full_mask, v)]
            if score > best_score + 1e-6:
                best_score = score
                best_last = v
            elif abs(score - best_score) <= 1e-6 and v < best_last:
                best_score = score
                best_last = v

    # Reconstruct path
    curr = best_last
    mask = full_mask
    path = []
    while curr is not None:
        path.append(curr)
        prev = parent.get((mask, curr), None)
        if prev is not None:
            mask = mask ^ (1 << curr)
        curr = prev
    path.reverse()

    # Canonical direction if no anchor specified
    if anchor_site is None:
        rev_path = list(reversed(path))
        if site_names[rev_path[0]] < site_names[path[0]]:
            path = rev_path

    seriated_site_names = [site_names[i] for i in path]
    violations = count_robinson_violations(br_matrix, path)

    battleship_analysis = {}
    unimodal_count = 0
    for a in artifact_types:
        freq_seq = [percentages[idx].get(a, 0.0) for idx in path]
        unimodal = is_unimodal(freq_seq)
        if unimodal:
            unimodal_count += 1
        battleship_analysis[a] = {
            "frequencies": freq_seq,
            "peak_site": seriated_site_names[freq_seq.index(max(freq_seq))],
            "is_unimodal": unimodal
        }

    unimodal_compliance_pct = round((unimodal_count / max(1, len(artifact_types))) * 100.0, 2)

    seriated_matrix = []
    for i in path:
        row = [br_matrix[i][j] for j in path]
        seriated_matrix.append(row)

    status = "CHRONOLOGICALLY_ROBUST"
    if violations == 0:
        status = "PERFECT_ROBINSON_SERIATION"
    elif violations > 4 or unimodal_compliance_pct < 60.0:
        status = "STRATIGRAPHIC_ANOMALY_OR_DISTURBED"

    return {
        "seriated_order": seriated_site_names,
        "consecutive_similarity_sum": round(best_score, 2),
        "robinson_violations_count": violations,
        "unimodal_compliance_pct": unimodal_compliance_pct,
        "status": status,
        "battleship_curves": battleship_analysis,
        "seriated_similarity_matrix": seriated_matrix
    }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    result = solve_seriation(data)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))

if __name__ == "__main__":
    main()
