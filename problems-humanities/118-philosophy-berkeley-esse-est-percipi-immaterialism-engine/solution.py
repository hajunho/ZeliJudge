import sys
import json

def solve():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return

    data = json.loads(raw_input)
    observers = data.get("observers", [])
    entities = data.get("candidate_entities", [])
    rules = data.get("epistemological_rules", {})

    collapse_primary = rules.get("collapse_primary_into_secondary", True)
    divine_guarantee = rules.get("divine_guarantee_enabled", True)

    active_mortal_perceivers = [o for o in observers if o.get("active", True) and o.get("role") == "MORTAL_OBSERVER"]
    divine_active = any(o.get("active", True) and o.get("role") == "OMNIPRESENT_PERCEIVER" for o in observers) and divine_guarantee

    mortal_perceived_ids = set()
    for o in active_mortal_perceivers:
        for f in o.get("focus_field", []):
            mortal_perceived_ids.add(f)

    entity_evaluations = []
    stats = {
        "total_entities": len(entities),
        "mortal_perceived_count": 0,
        "divine_sustained_count": 0,
        "non_existent_void_count": 0,
        "material_substrata_annihilated": 0
    }

    for ent in entities:
        ent_id = ent.get("id")
        has_substratum = ent.get("alleged_matter_substratum", False)

        is_mortal_seen = ent_id in mortal_perceived_ids

        if is_mortal_seen:
            stats["mortal_perceived_count"] += 1
            ontological_status = "PERCEIVED_BY_MORTAL_MIND"
            perceived_by = "MORTAL"
        elif divine_active:
            stats["divine_sustained_count"] += 1
            ontological_status = "SUSTAINED_BY_DIVINE_PERCEPTION"
            perceived_by = "DIVINE"
        else:
            stats["non_existent_void_count"] += 1
            ontological_status = "ANNIHILATED_NON_EXISTENT"
            perceived_by = "NONE"

        is_mind_dependent = True if collapse_primary else False

        substratum_status = "ANNIHILATED_FICTION" if has_substratum else "NONE"
        if has_substratum:
            stats["material_substrata_annihilated"] += 1

        entity_evaluations.append({
            "entity_id": ent_id,
            "ontological_status": ontological_status,
            "perceived_by": perceived_by,
            "all_qualities_are_ideas": is_mind_dependent,
            "material_substratum": substratum_status
        })

    if not divine_active and stats["non_existent_void_count"] > 0:
        metaphysical_verdict = "SOLIPSISTIC_COLLAPSE_WITHOUT_DIVINITY"
    elif all(e["all_qualities_are_ideas"] for e in entity_evaluations) and stats["material_substrata_annihilated"] > 0:
        metaphysical_verdict = "IMMATERIALIST_TRIUMPH_ESSE_EST_PERCIPI"
    else:
        metaphysical_verdict = "DOGMATIC_MATERIALIST_RELAPSE"

    result = {
        "metaphysical_verdict": metaphysical_verdict,
        "stats": stats,
        "entity_evaluations": entity_evaluations
    }

    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    solve()
