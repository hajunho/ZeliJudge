# -*- coding: utf-8 -*-
"""
ZeliJudge Humanities Track Problem #045: Cultural Anthropology Kinship Algebra & Murdock Classification
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

def derive_kinship_relations(individuals, parent_child, ego_id):
    indiv_map = {ind["id"]: ind for ind in individuals}
    
    parents_of = {ind["id"]: [] for ind in individuals}
    children_of = {ind["id"]: [] for ind in individuals}
    for p, c in parent_child:
        if p in parents_of and c in parents_of:
            parents_of[c].append(p)
            children_of[p].append(c)

    ego = indiv_map.get(ego_id)
    if not ego:
        return {}

    relations = {}

    # Parents of Ego
    f_id = None
    m_id = None
    for p_id in parents_of.get(ego_id, []):
        if indiv_map[p_id]["gender"] == "M":
            f_id = p_id
            relations[p_id] = "F"
        else:
            m_id = p_id
            relations[p_id] = "M"

    # Siblings of Ego
    ego_parents = set(parents_of.get(ego_id, []))
    for p_id in ego_parents:
        for sib_id in children_of.get(p_id, []):
            if sib_id != ego_id and sib_id not in relations:
                g = indiv_map[sib_id]["gender"]
                relations[sib_id] = "B" if g == "M" else "Z"

    # Paternal Uncles/Aunts
    if f_id:
        f_parents = set(parents_of.get(f_id, []))
        for gp_id in f_parents:
            for sib_id in children_of.get(gp_id, []):
                if sib_id != f_id and sib_id not in relations:
                    g = indiv_map[sib_id]["gender"]
                    relations[sib_id] = "FB" if g == "M" else "FZ"

    # Maternal Uncles/Aunts
    if m_id:
        m_parents = set(parents_of.get(m_id, []))
        for gp_id in m_parents:
            for sib_id in children_of.get(gp_id, []):
                if sib_id != m_id and sib_id not in relations:
                    g = indiv_map[sib_id]["gender"]
                    relations[sib_id] = "MB" if g == "M" else "MZ"

    # Cousins
    for target_id, rel in list(relations.items()):
        if rel in ["FB", "FZ", "MB", "MZ"]:
            for cousin_id in children_of.get(target_id, []):
                if cousin_id not in relations:
                    g = indiv_map[cousin_id]["gender"]
                    suffix = "S" if g == "M" else "D"
                    relations[cousin_id] = f"{rel}{suffix}"

    # Children of Ego
    for ch_id in children_of.get(ego_id, []):
        if ch_id not in relations:
            g = indiv_map[ch_id]["gender"]
            relations[ch_id] = "S" if g == "M" else "D"

    # Children of Siblings
    for sib_id, rel in list(relations.items()):
        if rel in ["B", "Z"]:
            for nib_id in children_of.get(sib_id, []):
                if nib_id not in relations:
                    g = indiv_map[nib_id]["gender"]
                    suffix = "S" if g == "M" else "D"
                    relations[nib_id] = f"{rel}{suffix}"

    return relations

def get_canonical_term(system, relation):
    if system == "HAWAIIAN":
        if relation in ["F", "FB", "MB"]:
            return "FATHER"
        elif relation in ["M", "MZ", "FZ"]:
            return "MOTHER"
        elif relation in ["B", "FBS", "MZS", "MBS", "FZS"]:
            return "BROTHER"
        elif relation in ["Z", "FBD", "MZD", "MBD", "FZD"]:
            return "SISTER"
        elif relation in ["S", "BS", "ZS", "FBSS", "MBDS"]:
            return "SON"
        elif relation in ["D", "BD", "ZD", "FBSD", "MBDD"]:
            return "DAUGHTER"

    elif system == "ESKIMO":
        if relation == "F":
            return "FATHER"
        elif relation == "M":
            return "MOTHER"
        elif relation in ["FB", "MB"]:
            return "UNCLE"
        elif relation in ["FZ", "MZ"]:
            return "AUNT"
        elif relation == "B":
            return "BROTHER"
        elif relation == "Z":
            return "SISTER"
        elif relation in ["FBS", "FBD", "MZS", "MZD", "MBS", "MBD", "FZS", "FZD"]:
            return "COUSIN"
        elif relation == "S":
            return "SON"
        elif relation == "D":
            return "DAUGHTER"
        elif relation in ["BS", "ZS"]:
            return "NEPHEW"
        elif relation in ["BD", "ZD"]:
            return "NIECE"

    elif system == "IROQUOIS":
        if relation in ["F", "FB"]:
            return "FATHER"
        elif relation in ["M", "MZ"]:
            return "MOTHER"
        elif relation == "MB":
            return "MATERNAL_UNCLE"
        elif relation == "FZ":
            return "PATERNAL_AUNT"
        elif relation in ["B", "FBS", "MZS"]:
            return "BROTHER"
        elif relation in ["Z", "FBD", "MZD"]:
            return "SISTER"
        elif relation in ["MBS", "FZS"]:
            return "MALE_CROSS_COUSIN"
        elif relation in ["MBD", "FZD"]:
            return "FEMALE_CROSS_COUSIN"

    elif system == "CROW":
        if relation in ["F", "FB"]:
            return "FATHER"
        elif relation in ["M", "MZ"]:
            return "MOTHER"
        elif relation == "MB":
            return "MATERNAL_UNCLE"
        elif relation == "FZ":
            return "PATERNAL_AUNT"
        elif relation in ["B", "FBS", "MZS"]:
            return "BROTHER"
        elif relation in ["Z", "FBD", "MZD"]:
            return "SISTER"
        elif relation == "FZS":
            return "FATHER"
        elif relation == "FZD":
            return "PATERNAL_AUNT"
        elif relation == "MBS":
            return "SON"
        elif relation == "MBD":
            return "DAUGHTER"

    elif system == "OMAHA":
        if relation in ["F", "FB"]:
            return "FATHER"
        elif relation in ["M", "MZ"]:
            return "MOTHER"
        elif relation == "MB":
            return "MATERNAL_UNCLE"
        elif relation == "FZ":
            return "PATERNAL_AUNT"
        elif relation in ["B", "FBS", "MZS"]:
            return "BROTHER"
        elif relation in ["Z", "FBD", "MZD"]:
            return "SISTER"
        elif relation == "MBS":
            return "MATERNAL_UNCLE"
        elif relation == "MBD":
            return "MOTHER"
        elif relation == "FZS":
            return "NEPHEW"
        elif relation == "FZD":
            return "NIECE"

    elif system == "SUDANESE":
        desc_map = {
            "F": "FATHER", "M": "MOTHER",
            "FB": "FATHER_BROTHER", "FZ": "FATHER_SISTER",
            "MB": "MOTHER_BROTHER", "MZ": "MOTHER_SISTER",
            "B": "BROTHER", "Z": "SISTER",
            "FBS": "FATHER_BROTHER_SON", "FBD": "FATHER_BROTHER_DAUGHTER",
            "FZS": "FATHER_SISTER_SON", "FZD": "FATHER_SISTER_DAUGHTER",
            "MBS": "MOTHER_BROTHER_SON", "MBD": "MOTHER_BROTHER_DAUGHTER",
            "MZS": "MOTHER_SISTER_SON", "MZD": "MOTHER_SISTER_DAUGHTER",
            "S": "SON", "D": "DAUGHTER"
        }
        return desc_map.get(relation, relation)

    return relation

def classify_murdock_system(term_dict):
    f = term_dict.get("F")
    fb = term_dict.get("FB")
    mb = term_dict.get("MB")
    m = term_dict.get("M")
    mz = term_dict.get("MZ")
    fz = term_dict.get("FZ")

    b = term_dict.get("B")
    fbs = term_dict.get("FBS")
    mbs = term_dict.get("MBS")
    fzs = term_dict.get("FZS")
    mbd = term_dict.get("MBD")

    terms_g1 = {f, fb, mb, m, mz, fz}
    terms_cousins = {term_dict.get(k) for k in ["FBS", "FBD", "FZS", "FZD", "MBS", "MBD", "MZS", "MZD"]}
    if len(terms_g1) == 6 and len(terms_cousins) == 8:
        return "SUDANESE"

    if f == fb == mb and m == mz == fz and b == fbs == mbs:
        return "HAWAIIAN"

    if f != fb and fb == mb and b != fbs and fbs == mbs:
        return "ESKIMO"

    if f == fb and f != mb and b == fbs and b != mbs:
        if fzs == f or term_dict.get("FZD") == fz:
            return "CROW"
        if mbs == mb or mbd == m:
            return "OMAHA"
        return "IROQUOIS"

    return "DESCRIPTIVE_OR_MIXED"

def evaluate_marriage(system, relation, alliance_rule):
    term = get_canonical_term(system, relation)
    if term in ["FATHER", "MOTHER", "BROTHER", "SISTER", "SON", "DAUGHTER"]:
        return {
            "eligible": False,
            "status": "INCEST_TABOO",
            "reason": f"Classified as primary kin / sibling category ({term})"
        }

    if system == "HAWAIIAN":
        return {
            "eligible": False,
            "status": "INCEST_TABOO",
            "reason": "Hawaiian system merges all cousins as siblings"
        }

    if system == "ESKIMO":
        return {
            "eligible": False,
            "status": "CULTURE_RESTRICTED",
            "reason": "Bilateral nuclear system restricts first cousin marriages"
        }

    if system in ["IROQUOIS", "CROW", "OMAHA"]:
        if relation in ["MBD", "MBS", "FZD", "FZS"]:
            if alliance_rule == "MATRILATERAL_ONLY" and relation not in ["MBD", "MBS"]:
                return {
                    "eligible": False,
                    "status": "ALLIANCE_RESTRICTION",
                    "reason": "Asymmetric generalized exchange allows only matrilateral cross-cousins (MBD)"
                }
            elif alliance_rule == "PATRILATERAL_ONLY" and relation not in ["FZD", "FZS"]:
                return {
                    "eligible": False,
                    "status": "ALLIANCE_RESTRICTION",
                    "reason": "Delayed direct exchange allows only patrilateral cross-cousins (FZD)"
                }
            return {
                "eligible": True,
                "status": "PREFERRED_CROSS_COUSIN",
                "reason": f"Cross-cousin alliance eligible under {system} kinship"
            }

    return {
        "eligible": True,
        "status": "PERMITTED_NON_SIBLING",
        "reason": "Permitted non-incestuous lineage"
    }

def solve_kinship(data):
    config = data.get("config", {})
    alliance_rule = config.get("alliance_rule", "BILATERAL_CROSS_COUSIN")
    system_type = config.get("system_type", "AUTO_DETECT")
    native_vocabulary = data.get("native_vocabulary", {})

    if system_type == "AUTO_DETECT":
        if native_vocabulary:
            system_type = classify_murdock_system(native_vocabulary)
        else:
            system_type = "IROQUOIS"

    individuals = data.get("individuals", [])
    parent_child = data.get("parent_child", [])
    queries = data.get("queries", [])

    results = []
    for q in queries:
        ego_id = q.get("ego")
        target_id = q.get("target")

        relation_code = q.get("relation_code")
        if not relation_code and individuals and parent_child:
            genealogy_relations = derive_kinship_relations(individuals, parent_child, ego_id)
            relation_code = genealogy_relations.get(target_id, "UNKNOWN")

        canonical_term = get_canonical_term(system_type, relation_code)
        native_term = native_vocabulary.get(relation_code, canonical_term)
        marriage_info = evaluate_marriage(system_type, relation_code, alliance_rule)

        is_parallel = relation_code in ["FBS", "FBD", "MZS", "MZD"]
        is_cross = relation_code in ["MBS", "MBD", "FZS", "FZD"]
        structural_class = "PRIMARY_KIN" if relation_code in ["F", "M", "B", "Z", "S", "D"] else (
            "PARALLEL_COUSIN" if is_parallel else ("CROSS_COUSIN" if is_cross else "COLLATERAL")
        )

        results.append({
            "ego": ego_id,
            "target": target_id,
            "relation_code": relation_code,
            "structural_class": structural_class,
            "canonical_term": canonical_term,
            "native_term": native_term,
            "marriage_evaluation": marriage_info
        })

    return {
        "classified_system": system_type,
        "alliance_rule": alliance_rule,
        "query_evaluations": results
    }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    result = solve_kinship(data)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))

if __name__ == "__main__":
    main()
