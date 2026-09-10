# -*- coding: utf-8 -*-
"""
ZeliJudge Humanities Track Problem #061
Pierre Bourdieu: Distinction, Habitus, Field & Capital Reproduction Engine
(피에르 부르디외의 구별짓기: 4대 자본, 장 및 아비투스 계급 재생산 엔진)

Operationalizes Pierre Bourdieu's 'La Distinction' (1979) and Field Theory:
1. 4 Forms of Capital: Economic, Cultural, Social, Symbolic.
2. Field-Specific Capital Weighting and Power Position (Nomos of the Field).
3. Capital Composition Ratio (Cultural vs Economic) & Class Fraction Classification.
4. Symbolic Violence, Hegemony & Misrecognition (Méconnaissance).
5. Capital Conversion (Economic -> Cultural/Symbolic) and Social Reproduction.
"""

import sys
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return

    data = json.loads(raw_input)

    config = data.get("config", {})
    hegemony_ratio = float(config.get("hegemony_dominance_ratio", 1.40))
    conv_rate = float(config.get("symbolic_conversion_rate", 0.20))

    fields = {f["field_id"]: f for f in data.get("fields", [])}
    agents = {a["agent_id"]: {
        "agent_id": a["agent_id"],
        "name": a.get("name", ""),
        "capitals": {k: float(v) for k, v in a.get("capitals", {}).items()},
        "habitus_type": a.get("habitus_type", "petite_bourgeoisie")
    } for a in data.get("agents", [])}

    interactions = data.get("interactions", [])
    interaction_logs = []

    for idx, act in enumerate(interactions, start=1):
        f_id = act.get("field_id")
        act_type = act.get("type", "FIELD_EVALUATION")
        f_info = fields.get(f_id, {})
        weights = f_info.get("capital_weights", {
            "economic": 0.25,
            "cultural": 0.25,
            "social": 0.25,
            "symbolic": 0.25
        })

        participants = act.get("participants", list(agents.keys()))
        log_entry = {
            "interaction_index": idx,
            "field_id": f_id,
            "type": act_type,
            "details": {}
        }

        # Calculate field powers for participants
        powers = {}
        for p_id in participants:
            if p_id in agents:
                caps = agents[p_id]["capitals"]
                p = sum(caps.get(k, 0.0) * float(w) for k, w in weights.items())
                powers[p_id] = round(p, 4)

        if act_type == "CAPITAL_CONVERSION":
            agent_id = act.get("agent_id", participants[0] if participants else None)
            from_c = act.get("from_capital", "economic")
            to_c = act.get("to_capital", "cultural")
            amount = float(act.get("amount", 0.0))

            if agent_id in agents:
                ag = agents[agent_id]
                cur_from = ag["capitals"].get(from_c, 0.0)
                actual_spent = min(cur_from, amount)
                ag["capitals"][from_c] = round(cur_from - actual_spent, 4)

                gained = round(actual_spent * conv_rate, 4)
                ag["capitals"][to_c] = round(ag["capitals"].get(to_c, 0.0) + gained, 4)

                log_entry["details"] = {
                    "agent_id": agent_id,
                    "from_capital": from_c,
                    "to_capital": to_c,
                    "amount_converted": actual_spent,
                    "capital_gained": gained
                }

        elif act_type == "SYMBOLIC_VIOLENCE_CONTEST":
            p1, p2 = participants[0], participants[1]
            pwr1, pwr2 = powers.get(p1, 0.0), powers.get(p2, 0.0)

            if pwr1 >= pwr2:
                dom_id, sub_id = p1, p2
                dom_pwr, sub_pwr = pwr1, pwr2
            else:
                dom_id, sub_id = p2, p1
                dom_pwr, sub_pwr = pwr2, pwr1

            is_hegemonic = (dom_pwr >= sub_pwr * hegemony_ratio)
            if is_hegemonic:
                transfer = round(min(agents[sub_id]["capitals"].get("symbolic", 0.0), 10.0), 4)
                agents[sub_id]["capitals"]["symbolic"] = round(agents[sub_id]["capitals"].get("symbolic", 0.0) - transfer, 4)
                agents[dom_id]["capitals"]["symbolic"] = round(agents[dom_id]["capitals"].get("symbolic", 0.0) + transfer, 4)
                result_outcome = "MECONNAISSANCE_REINFORCED"
            else:
                transfer = 0.0
                result_outcome = "CONTESTED_RESISTANCE"

            log_entry["details"] = {
                "dominant_agent": dom_id,
                "subordinate_agent": sub_id,
                "power_ratio": round(dom_pwr / sub_pwr, 4) if sub_pwr > 0 else 999.0,
                "hegemony_achieved": is_hegemonic,
                "symbolic_capital_transferred": transfer,
                "outcome": result_outcome
            }

        elif act_type == "FIELD_EVALUATION":
            ranked = sorted(powers.items(), key=lambda x: -x[1])
            log_entry["details"] = {
                "field_standings": [{"agent_id": aid, "field_power": pwr} for aid, pwr in ranked]
            }

        interaction_logs.append(log_entry)

    primary_field_id = list(fields.keys())[0] if fields else "DEFAULT"
    prim_weights = fields.get(primary_field_id, {}).get("capital_weights", {
        "economic": 0.25,
        "cultural": 0.25,
        "social": 0.25,
        "symbolic": 0.25
    })

    final_agent_reports = []
    agent_power_list = []

    for a_id in sorted(agents.keys()):
        ag = agents[a_id]
        caps = ag["capitals"]
        f_pwr = sum(caps.get(k, 0.0) * float(w) for k, w in prim_weights.items())
        f_pwr = round(f_pwr, 4)
        agent_power_list.append((a_id, f_pwr))

        k_cult = caps.get("cultural", 0.0)
        k_econ = caps.get("economic", 0.0)
        ratio = round(k_cult / (k_econ + 1e-6), 4)

        if ratio >= 1.25:
            fraction = "INTELLECTUAL_FRACTION"
        elif ratio <= 0.80:
            fraction = "BOURGEOIS_FRACTION"
        else:
            fraction = "BALANCED_FRACTION"

        final_agent_reports.append({
            "agent_id": a_id,
            "name": ag["name"],
            "final_capitals": {k: round(v, 4) for k, v in caps.items()},
            "primary_field_power": f_pwr,
            "capital_composition_ratio": ratio,
            "class_fraction": fraction
        })

    sorted_by_pwr = sorted(agent_power_list, key=lambda x: -x[1])
    n_agents = len(sorted_by_pwr)
    class_positions = {}

    for rank, (a_id, pwr) in enumerate(sorted_by_pwr):
        pct = (rank + 1) / n_agents if n_agents > 0 else 1.0
        if rank == 0 or pct <= 0.34:
            pos = "DOMINANT_CLASS"
        elif pct <= 0.67:
            pos = "PETITE_BOURGEOISIE"
        else:
            pos = "WORKING_CLASS"
        class_positions[a_id] = pos

    for r in final_agent_reports:
        r["field_class_position"] = class_positions[r["agent_id"]]

    dominant_cnt = sum(1 for r in final_agent_reports if r["field_class_position"] == "DOMINANT_CLASS")

    output = {
        "summary": {
            "primary_field_id": primary_field_id,
            "total_agents": len(agents),
            "dominant_class_count": dominant_cnt,
            "total_interactions_processed": len(interactions)
        },
        "interaction_history": interaction_logs,
        "agent_analysis": final_agent_reports
    }

    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    solve()
