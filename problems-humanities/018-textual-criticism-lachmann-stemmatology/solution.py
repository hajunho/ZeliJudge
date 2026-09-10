import sys
import json

if sys.platform == 'win32':
    try:
        sys.stdin.reconfigure(encoding='utf-8')
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

def analyze_stemmatology(data):
    loci = data.get('loci', [])
    witnesses = data.get('witnesses', {})
    archetype_known = data.get('archetype', None)

    loc_ids = [l['id'] for l in loci]
    wit_ids = sorted(list(witnesses.keys()))
    n_wit = len(wit_ids)
    n_loc = len(loc_ids)

    # 1. Pairwise differences (Hamming distance)
    diff_matrix = {}
    for i in range(n_wit):
        for j in range(i + 1, n_wit):
            w1, w2 = wit_ids[i], wit_ids[j]
            d = sum(1 for lid in loc_ids if witnesses[w1].get(lid) != witnesses[w2].get(lid))
            diff_matrix[f'{w1}-{w2}'] = d

    # 2. Error analysis if archetype is provided
    codices_descripti = []
    conjunctive_errors = {}
    separative_errors = {}
    contaminated_witnesses = []
    wit_errors = {}

    if archetype_known:
        for w in wit_ids:
            errs = {}
            for lid in loc_ids:
                r = witnesses[w].get(lid)
                if r != archetype_known.get(lid):
                    errs[lid] = r
            wit_errors[w] = errs

        for i in range(n_wit):
            w1 = wit_ids[i]
            for j in range(n_wit):
                if i != j:
                    w2 = wit_ids[j]
                    conj = [
                        {'locus': lid, 'error_reading': wit_errors[w1][lid]}
                        for lid in wit_errors[w1]
                        if wit_errors[w2].get(lid) == wit_errors[w1][lid]
                    ]
                    sep = [
                        {'locus': lid, 'error_in_w1': wit_errors[w1][lid], 'reading_in_w2': witnesses[w2].get(lid)}
                        for lid in wit_errors[w1]
                        if witnesses[w2].get(lid) == archetype_known.get(lid)
                    ]
                    separative_errors[f'{w1}->{w2}'] = len(sep)
                    if i < j:
                        conjunctive_errors[f'{w1}-{w2}'] = conj

        # Eliminatio Codicum Descriptorum:
        for i in range(n_wit):
            for j in range(n_wit):
                if i != j:
                    p_cand = wit_ids[i]
                    c_cand = wit_ids[j]
                    p_errs = wit_errors[p_cand]
                    c_errs = wit_errors[c_cand]
                    has_all_parent_errors = all(c_errs.get(lid) == err_val for lid, err_val in p_errs.items()) if p_errs else False
                    has_additional_errors = len(c_errs) > len(p_errs)
                    if has_all_parent_errors and has_additional_errors:
                        codices_descripti.append({
                            'codex_descriptus': c_cand,
                            'copied_from': p_cand,
                            'parent_errors': len(p_errs),
                            'additional_errors': len(c_errs) - len(p_errs)
                        })

    # 3. Family Clustering via Conjunctive Errors
    families = []
    for pair_name, conj_list in conjunctive_errors.items():
        if len(conj_list) >= 2:
            w1, w2 = pair_name.split('-')
            families.append({
                'pair': pair_name,
                'members': [w1, w2],
                'shared_errors_count': len(conj_list),
                'shared_loci': [c['locus'] for c in conj_list]
            })

    # Contamination Detection:
    # A witness is contaminated if it shares >= 2 errors with w1, and >= 2 errors with w2,
    # but w1 and w2 share 0 errors with each other!
    for w in wit_ids:
        partner_families = []
        for fam in families:
            if w in fam['members']:
                other = fam['members'][0] if fam['members'][1] == w else fam['members'][1]
                partner_families.append((other, fam['shared_loci']))
        if len(partner_families) >= 2:
            for f1_idx in range(len(partner_families)):
                for f2_idx in range(f1_idx + 1, len(partner_families)):
                    o1, loci1 = partner_families[f1_idx]
                    o2, loci2 = partner_families[f2_idx]
                    o_pair = f'{min(o1, o2)}-{max(o1, o2)}'
                    if len(conjunctive_errors.get(o_pair, [])) == 0:
                        contaminated_witnesses.append({
                            'contaminated_witness': w,
                            'source_branches': [o1, o2],
                            'inherited_from_branch1': loci1,
                            'inherited_from_branch2': loci2
                        })

    # 4. Archetype Recensio (Majority Rule & Ambiguity Detection)
    reconstructed_archetype = {}
    ambiguous_loci = []
    for lid in loc_ids:
        counts = {}
        for w in wit_ids:
            r = witnesses[w].get(lid)
            counts[r] = counts.get(r, 0) + 1
        sorted_counts = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
        top_reading, top_count = sorted_counts[0]
        is_ambiguous = len(sorted_counts) > 1 and sorted_counts[1][1] == top_count
        reconstructed_archetype[lid] = {
            'reconstructed_reading': top_reading,
            'vote_distribution': counts,
            'is_ambiguous': is_ambiguous
        }
        if is_ambiguous:
            ambiguous_loci.append(lid)

    return {
        'tradition_summary': {
            'witnesses_count': n_wit,
            'loci_count': n_loc,
            'codices_descripti_count': len(codices_descripti),
            'families_detected': len(families),
            'contaminated_witnesses_count': len(contaminated_witnesses),
            'ambiguous_loci_count': len(ambiguous_loci)
        },
        'pairwise_differences': diff_matrix,
        'conjunctive_errors': conjunctive_errors,
        'separative_errors_summary': separative_errors,
        'codices_descripti': codices_descripti,
        'identified_families': families,
        'contaminated_witnesses': contaminated_witnesses,
        'reconstructed_archetype': reconstructed_archetype
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    res = analyze_stemmatology(data)
    print(json.dumps(res, ensure_ascii=False))

if __name__ == '__main__':
    main()
