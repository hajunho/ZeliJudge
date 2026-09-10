import sys
import json

# Ensure UTF-8 IO
sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

def reconstruct_stemma(req):
    witnesses = req["witnesses"]
    loci = req["loci"]
    
    error_matrix = {w: set() for w in witnesses}
    total_errors = {w: 0 for w in witnesses}
    
    for loc in loci:
        orig = loc["original_reading"]
        var_map = loc["variants"]
        for w in witnesses:
            reading = var_map.get(w)
            if reading is not None and reading != orig:
                error_matrix[w].add((loc["locus_id"], reading))
                total_errors[w] += 1
                
    eliminated = []
    independent_witnesses = set(witnesses)
    
    for w_sub in witnesses:
        for w_parent in witnesses:
            if w_sub != w_parent:
                p_err = error_matrix[w_parent]
                s_err = error_matrix[w_sub]
                if p_err.issubset(s_err) and len(s_err) > len(p_err) and len(p_err) > 0:
                    eliminated.append({
                        "codex_descriptus": w_sub,
                        "copied_from": w_parent,
                        "inherited_errors_count": len(p_err),
                        "additional_errors_count": len(s_err) - len(p_err)
                    })
                    independent_witnesses.discard(w_sub)
                    break
                    
    pair_shared = []
    for i in range(len(witnesses)):
        for j in range(i + 1, len(witnesses)):
            w1 = witnesses[i]
            w2 = witnesses[j]
            shared = error_matrix[w1].intersection(error_matrix[w2])
            pair_shared.append({
                "pair": f"{w1}-{w2}",
                "shared_errors_count": len(shared),
                "shared_loci": sorted([loc_id for loc_id, _ in shared])
            })
            
    families = []
    visited = set()
    indep_list = sorted(list(independent_witnesses))
    
    for i in range(len(indep_list)):
        w1 = indep_list[i]
        if w1 in visited:
            continue
        group = [w1]
        for j in range(i + 1, len(indep_list)):
            w2 = indep_list[j]
            shared = error_matrix[w1].intersection(error_matrix[w2])
            if len(shared) > 0:
                group.append(w2)
                visited.add(w2)
        if len(group) > 1:
            shared_all = error_matrix[group[0]]
            for member in group[1:]:
                shared_all = shared_all.intersection(error_matrix[member])
            families.append({
                "hyparchetype": f"family_{chr(97 + len(families))}",
                "members": sorted(group),
                "conjunctive_errors_count": len(shared_all),
                "shared_loci": sorted([loc_id for loc_id, _ in shared_all])
            })
            for m in group:
                visited.add(m)
        else:
            families.append({
                "hyparchetype": f"family_{chr(97 + len(families))}",
                "members": [w1],
                "conjunctive_errors_count": 0,
                "shared_loci": []
            })
            visited.add(w1)
            
    apparatus = []
    for loc in loci:
        lid = loc["locus_id"]
        var_map = loc["variants"]
        counts = {}
        for w in witnesses:
            r = var_map.get(w)
            if r is not None:
                counts[r] = counts.get(r, 0) + 1
        sorted_c = sorted(counts.items(), key=lambda x: -x[1])
        top_reading = sorted_c[0][0]
        
        groups_by_reading = {}
        for w, r in var_map.items():
            groups_by_reading.setdefault(r, []).append(w)
        
        fmt_parts = []
        for r, w_list in sorted(groups_by_reading.items(), key=lambda x: -len(x[1])):
            fmt_parts.append(f"{r} {' '.join(sorted(w_list))}")
        apparatus_str = " : ".join(fmt_parts)
        
        apparatus.append({
            "locus_id": lid,
            "passage": loc.get("passage", f"Locus {lid}"),
            "reconstructed_reading": top_reading,
            "apparatus_entry": apparatus_str,
            "matches_original_archetype": (top_reading == loc["original_reading"])
        })

    return {
        "mode": "reconstruct_stemma",
        "total_witnesses": len(witnesses),
        "independent_witnesses": sorted(list(independent_witnesses)),
        "eliminated_descripti": eliminated,
        "hyparchetypes": families,
        "pairwise_shared_errors": pair_shared,
        "critical_apparatus": apparatus
    }

def evaluate_genealogy(req):
    witness_a = req["witness_a"]
    witness_b = req["witness_b"]
    loci = req["loci"]
    
    a_errors = set()
    b_errors = set()
    for loc in loci:
        orig = loc["original_reading"]
        if loc["variants"].get(witness_a) != orig:
            a_errors.add((loc["locus_id"], loc["variants"].get(witness_a)))
        if loc["variants"].get(witness_b) != orig:
            b_errors.add((loc["locus_id"], loc["variants"].get(witness_b)))
            
    shared = a_errors.intersection(b_errors)
    a_only = a_errors - b_errors
    b_only = b_errors - a_errors
    
    if len(a_only) == 0 and len(b_only) > 0 and len(a_errors) > 0:
        rel = "A_IS_ANCESTOR_OF_B"
    elif len(b_only) == 0 and len(a_only) > 0 and len(b_errors) > 0:
        rel = "B_IS_ANCESTOR_OF_A"
    elif len(shared) > 0 and len(a_only) > 0 and len(b_only) > 0:
        rel = "COLLATERAL_COUSINS_SHARE_HYPARCHETYPE"
    elif len(shared) == 0 and (len(a_errors) > 0 or len(b_errors) > 0):
        rel = "INDEPENDENT_BRANCHES"
    else:
        rel = "IDENTICAL_OR_PERFECT_WITNESSES"
        
    return {
        "mode": "evaluate_genealogy",
        "witness_a": witness_a,
        "witness_b": witness_b,
        "shared_errors_count": len(shared),
        "a_separating_errors_count": len(a_only),
        "b_separating_errors_count": len(b_only),
        "genealogical_relationship": rel
    }

def solve():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    req = json.loads(raw)
    mode = req.get("mode")
    if mode == "reconstruct_stemma":
        res = reconstruct_stemma(req)
    elif mode == "evaluate_genealogy":
        res = evaluate_genealogy(req)
    else:
        res = {"error": f"Unknown mode: {mode}"}
    print(json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    solve()
