import sys
import json

def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)
    
    concept = input_data.get("concept", "BEING")
    initial_sphere = input_data.get("sphere", "BEING")
    initial_quality = input_data.get("quality", "INDETERMINATE_IMMEDIACY")
    initial_quantity = float(input_data.get("quantity", 0.0))
    measure_nodes = input_data.get("measure_nodes", [])
    operations = input_data.get("operations", [])
    
    current_sphere = initial_sphere
    current_quality = initial_quality
    current_quantity = initial_quantity
    reflection_stage = "IDENTITY"
    notion_moments = {"universal": False, "particular": False, "individual": False}
    negation_count = 0
    
    stats = {
        "quantitative_increments": 0,
        "nodal_leaps": 0,
        "contradictions_surmounted": 0,
        "aufhebung_syntheses": 0
    }
    
    op_log = []
    
    for op in operations:
        op_type = op.get("op")
        
        if op_type == "DIALECTICAL_BECOMING":
            negation_count += 1
            current_sphere = "BEING"
            current_quality = "DETERMINATE_BEING_DASEIN"
            status = "BECOMING_UNIFIED_AS_DASEIN"
            op_log.append({
                "op": "DIALECTICAL_BECOMING",
                "sphere": current_sphere,
                "quality": current_quality,
                "status": status,
                "negation_count": negation_count
            })
            
        elif op_type == "QUANTITATIVE_SHIFT":
            stats["quantitative_increments"] += 1
            delta = float(op.get("delta", 0.0))
            old_qty = current_quantity
            current_quantity = round(current_quantity + delta, 4)
            
            leaped = False
            for node in measure_nodes:
                thresh = float(node["threshold"])
                if (old_qty < thresh <= current_quantity) or (old_qty > thresh >= current_quantity):
                    stats["nodal_leaps"] += 1
                    stats["aufhebung_syntheses"] += 1
                    current_quality = node.get("leap_quality", current_quality)
                    if "leap_sphere" in node:
                        current_sphere = node["leap_sphere"]
                    leaped = True
                    negation_count += 1
                    op_log.append({
                        "op": "QUANTITATIVE_SHIFT",
                        "old_quantity": old_qty,
                        "new_quantity": current_quantity,
                        "status": "QUALITATIVE_NODAL_LEAP",
                        "new_quality": current_quality,
                        "new_sphere": current_sphere
                    })
                    break
            if not leaped:
                op_log.append({
                    "op": "QUANTITATIVE_SHIFT",
                    "old_quantity": old_qty,
                    "new_quantity": current_quantity,
                    "status": "GRADUAL_ACCUMULATION_NO_LEAP",
                    "quality": current_quality
                })
                
        elif op_type == "REFLECTIVE_CONTRADICTION":
            stage_progression = {
                "IDENTITY": "DIFFERENCE",
                "DIFFERENCE": "OPPOSITION",
                "OPPOSITION": "CONTRADICTION",
                "CONTRADICTION": "GROUND"
            }
            old_stage = reflection_stage
            reflection_stage = stage_progression.get(reflection_stage, "GROUND")
            current_sphere = "ESSENCE"
            
            if reflection_stage == "CONTRADICTION":
                status = "CONTRADICTION_UNVEILED_ROOT_OF_MOVEMENT"
                negation_count += 1
            elif reflection_stage == "GROUND":
                stats["contradictions_surmounted"] += 1
                stats["aufhebung_syntheses"] += 1
                negation_count += 1
                current_quality = "ACTUALITY_WIRKLICHKEIT"
                status = "CONTRADICTION_GROUNDED_IN_ACTUALITY"
            else:
                status = f"REFLECTION_ADVANCED_TO_{reflection_stage}"
                
            op_log.append({
                "op": "REFLECTIVE_CONTRADICTION",
                "previous_stage": old_stage,
                "current_reflection_stage": reflection_stage,
                "status": status,
                "sphere": current_sphere
            })
            
        elif op_type == "NOTION_MOMENT":
            moment = op.get("moment", "UNIVERSAL").lower()
            if moment in notion_moments:
                notion_moments[moment] = True
                
            current_sphere = "CONCEPT"
            if all(notion_moments.values()):
                stats["aufhebung_syntheses"] += 1
                current_sphere = "ABSOLUTE_IDEA"
                current_quality = "ABSOLUTE_IDEA_SELF_COMPREHENDING_METHOD"
                status = "TRIPARTITE_NOTION_SYNTHESIZED_AS_ABSOLUTE_IDEA"
            else:
                status = f"NOTION_MOMENT_INTEGRATED_{moment.upper()}"
                
            op_log.append({
                "op": "NOTION_MOMENT",
                "moment": moment.upper(),
                "notion_moments": dict(notion_moments),
                "status": status,
                "sphere": current_sphere
            })

    if current_sphere == "ABSOLUTE_IDEA":
        verdict = "ABSOLUTE_SPECULATIVE_TRUTH"
    elif current_sphere == "CONCEPT":
        verdict = "CONCRETE_NOTIONAL_DEVELOPMENT"
    elif current_sphere == "ESSENCE":
        verdict = "REFLECTIVE_ESSENTIAL_DYNAMICS"
    else:
        verdict = "IMMEDIATE_BEING_DETERMINATION"

    res = {
        "concept": concept,
        "initial_state": {
            "sphere": initial_sphere,
            "quality": initial_quality,
            "quantity": initial_quantity
        },
        "final_state": {
            "sphere": current_sphere,
            "quality": current_quality,
            "quantity": current_quantity,
            "reflection_stage": reflection_stage,
            "notion_moments": notion_moments,
            "negation_count": negation_count,
            "verdict": verdict
        },
        "stats": stats,
        "op_log": op_log
    }
    
    sys.stdout.write(json.dumps(res, separators=(',', ':'), ensure_ascii=False))

if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    solve()
