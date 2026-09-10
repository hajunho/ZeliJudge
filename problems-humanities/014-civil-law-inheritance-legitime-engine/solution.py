import sys
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

def solve_inheritance_and_legitime(input_data: dict) -> dict:
    estate_at_death = input_data.get("estate_at_death", 0)
    debts = input_data.get("debts", 0)
    heirs_input = input_data["heirs"]
    gifts = input_data.get("lifetime_gifts", [])
    bequests = input_data.get("testamentary_bequests", [])

    has_children = any(h["relation"] == "CHILD" for h in heirs_input)
    has_parents = any(h["relation"] == "PARENT" for h in heirs_input)
    has_spouse = any(h["relation"] == "SPOUSE" for h in heirs_input)

    if has_children:
        active_heirs = [h for h in heirs_input if h["relation"] in ("CHILD", "SPOUSE")]
    elif has_parents:
        active_heirs = [h for h in heirs_input if h["relation"] in ("PARENT", "SPOUSE")]
    elif has_spouse:
        active_heirs = [h for h in heirs_input if h["relation"] == "SPOUSE"]
    else:
        active_heirs = [h for h in heirs_input if h["relation"] == "SIBLING"]

    total_statutory_weight = sum(1.5 if h["relation"] == "SPOUSE" else 1.0 for h in active_heirs)
    for h in active_heirs:
        w = 1.5 if h["relation"] == "SPOUSE" else 1.0
        h["statutory_share_ratio"] = w / total_statutory_weight

    total_contributory = sum(h.get("contributory_share", 0) for h in active_heirs)
    total_bequests = sum(b["amount"] for b in bequests)
    distributable_estate = max(0, estate_at_death - total_bequests)

    heir_ids = {h["id"] for h in active_heirs}
    special_benefits = {h["id"]: 0 for h in active_heirs}

    for g in gifts:
        rec = g["recipient"]
        if rec in heir_ids:
            special_benefits[rec] += g["amount"]
    for b in bequests:
        rec = b["recipient"]
        if rec in heir_ids:
            special_benefits[rec] += b["amount"]

    total_special_benefits = sum(special_benefits.values())
    net_divisible = max(0, distributable_estate - total_contributory)
    deemed_estate_for_division = net_divisible + total_special_benefits

    temp_shares = {}
    excess_heirs = set()
    for h in active_heirs:
        hid = h["id"]
        cs = deemed_estate_for_division * h["statutory_share_ratio"] - special_benefits[hid]
        if cs < 0:
            temp_shares[hid] = 0
            excess_heirs.add(hid)
        else:
            temp_shares[hid] = cs

    if excess_heirs and len(excess_heirs) < len(active_heirs):
        non_excess = [h for h in active_heirs if h["id"] not in excess_heirs]
        realloc_weight = sum(1.5 if h["relation"] == "SPOUSE" else 1.0 for h in non_excess)
        realloc_deemed = net_divisible + sum(special_benefits[h["id"]] for h in non_excess)
        for h in non_excess:
            hid = h["id"]
            w = 1.5 if h["relation"] == "SPOUSE" else 1.0
            r = w / realloc_weight
            cs = realloc_deemed * r - special_benefits[hid]
            temp_shares[hid] = max(0, cs)

    total_temp = sum(temp_shares.values())
    concrete_estate_allocated = {}
    for h in active_heirs:
        hid = h["id"]
        if total_temp > 0:
            share_from_estate = net_divisible * (temp_shares[hid] / total_temp)
        else:
            share_from_estate = 0
        actual_received = share_from_estate + h.get("contributory_share", 0)
        concrete_estate_allocated[hid] = actual_received
        h["actual_estate_share"] = round(actual_received, 1)

    includable_gifts = sum(g["amount"] for g in gifts if g.get("includable_in_legitime", True))
    legitime_base_property = estate_at_death + includable_gifts - debts

    legitime_results = []
    total_shortfall = 0.0

    for h in active_heirs:
        hid = h["id"]
        rel = h["relation"]
        stat_ratio = h["statutory_share_ratio"]

        if rel in ("CHILD", "SPOUSE"):
            legitime_ratio = stat_ratio * 0.5
        elif rel == "PARENT":
            legitime_ratio = stat_ratio * (1.0 / 3.0)
        else:
            legitime_ratio = 0.0

        legitime_quota = max(0.0, legitime_base_property * legitime_ratio)
        inherited_debt = debts * stat_ratio
        net_inheritance = concrete_estate_allocated[hid] - inherited_debt
        heir_gift_in_base = sum(g["amount"] for g in gifts if g["recipient"] == hid and g.get("includable_in_legitime", True))
        heir_bequest = sum(b["amount"] for b in bequests if b["recipient"] == hid)

        total_heir_acquired = net_inheritance + heir_bequest + heir_gift_in_base
        shortfall = max(0.0, legitime_quota - total_heir_acquired)

        if shortfall > 0:
            total_shortfall += shortfall

        legitime_results.append({
            "id": hid,
            "relation": rel,
            "statutory_share_ratio": round(stat_ratio, 4),
            "legitime_quota": round(legitime_quota, 1),
            "net_inheritance": round(net_inheritance, 1),
            "special_benefit": round(heir_gift_in_base + heir_bequest, 1),
            "shortfall": round(shortfall, 1),
            "has_claim": shortfall > 0
        })

    abatement_plans = []
    if total_shortfall > 0:
        remaining_shortfall = total_shortfall
        if total_bequests > 0:
            bequest_abatement_total = min(remaining_shortfall, total_bequests)
            for b in bequests:
                amt = b["amount"]
                share_to_return = bequest_abatement_total * (amt / total_bequests)
                abatement_plans.append({
                    "target_type": "BEQUEST",
                    "recipient": b["recipient"],
                    "original_amount": amt,
                    "abated_return_amount": round(share_to_return, 1)
                })
            remaining_shortfall -= bequest_abatement_total

        if remaining_shortfall > 0 and includable_gifts > 0:
            gift_abatement_total = min(remaining_shortfall, includable_gifts)
            for g in gifts:
                if not g.get("includable_in_legitime", True):
                    continue
                amt = g["amount"]
                share_to_return = gift_abatement_total * (amt / includable_gifts)
                abatement_plans.append({
                    "target_type": "LIFETIME_GIFT",
                    "recipient": g["recipient"],
                    "original_amount": amt,
                    "abated_return_amount": round(share_to_return, 1)
                })

    return {
        "estate_summary": {
            "estate_at_death": estate_at_death,
            "debts": debts,
            "total_bequests": total_bequests,
            "includable_gifts": includable_gifts,
            "legitime_base_property": round(legitime_base_property, 1)
        },
        "heir_inheritance": [
            {
                "id": h["id"],
                "relation": h["relation"],
                "statutory_share_ratio": round(h["statutory_share_ratio"], 4),
                "actual_estate_share": round(concrete_estate_allocated[h["id"]], 1),
                "contributory_share": h.get("contributory_share", 0)
            }
            for h in active_heirs
        ],
        "legitime_evaluation": {
            "total_shortfall": round(total_shortfall, 1),
            "claims": legitime_results
        },
        "abatement_resolution": abatement_plans
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)
    result = solve_inheritance_and_legitime(input_data)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
