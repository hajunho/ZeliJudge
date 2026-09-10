import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
        
    input_data = json.loads(raw_input)
    
    # 1. Individual Tripartite Soul Analysis
    souls = input_data.get("individual_souls", [])
    soul_evaluations = []
    
    for s in souls:
        sid = s.get("soul_id", "SOUL")
        person = s.get("name", "Citizen")
        rational = float(s.get("rational_faculty", 50.0))
        spirited = float(s.get("spirited_faculty", 30.0))
        appetitive = float(s.get("appetitive_faculty", 20.0))
        
        total = max(0.01, rational + spirited + appetitive)
        r_ratio = round(rational / total, 4)
        s_ratio = round(spirited / total, 4)
        a_ratio = round(appetitive / total, 4)
        
        has_wisdom = (rational >= 60.0 and r_ratio > s_ratio and r_ratio > a_ratio)
        has_courage = (spirited >= 50.0 and rational >= 40.0)
        has_temperance = (rational >= appetitive * 0.8)
        
        is_internally_just = (r_ratio >= 0.45 and has_temperance and has_courage)
        
        if r_ratio >= 0.50:
            metal_class = "GOLD_PHILOSOPHER_RULER"
        elif s_ratio >= 0.40:
            metal_class = "SILVER_AUXILIARY_WARRIOR"
        else:
            metal_class = "BRONZE_PRODUCER_ARTISAN"
            
        soul_evaluations.append({
            "soul_id": sid,
            "name": person,
            "proportions": {
                "rational_ratio": r_ratio,
                "spirited_ratio": s_ratio,
                "appetitive_ratio": a_ratio
            },
            "virtues": {
                "wisdom": has_wisdom,
                "courage": has_courage,
                "temperance": has_temperance
            },
            "is_just_soul": is_internally_just,
            "assigned_metal_class": metal_class
        })

    # 2. Epistemic Ascent: Allegory of the Cave & Divided Line
    seekers = input_data.get("epistemic_seekers", [])
    cave_evaluations = []
    
    for sk in seekers:
        sk_id = sk.get("seeker_id", "SEEKER")
        name = sk.get("name", "Prisoner")
        cave_depth = float(sk.get("enlightenment_score", 10.0))
        willing_to_return = sk.get("willingness_to_return_to_cave", False)
        
        if cave_depth >= 85.0:
            stage_name = "NOESIS_IDEA_OF_THE_GOOD"
            epistemic_realm = "INTELLIGIBLE_SUN_REALM"
            description = "Direct intuition of the Forms and the Idea of the Good (Sun)"
        elif cave_depth >= 60.0:
            stage_name = "DIANOIA_MATHEMATICAL_HYPOTHESIS"
            epistemic_realm = "INTELLIGIBLE_STARS_REALM"
            description = "Discursive scientific reasoning, geometry and mathematical forms"
        elif cave_depth >= 30.0:
            stage_name = "PISTIS_SENSIBLE_OBJECTS"
            epistemic_realm = "VISIBLE_FIRE_PUPPET_REALM"
            description = "Belief in physical statues and firelight reflections in the cave"
        else:
            stage_name = "EIKASIA_SHADOWS_ILLUSION"
            epistemic_realm = "VISIBLE_SHADOW_REALM"
            description = "Chained prisoners mistaking projected shadows on the wall for reality"
            
        qualified_as_philosopher_king = (stage_name == "NOESIS_IDEA_OF_THE_GOOD" and willing_to_return)
        
        cave_evaluations.append({
            "seeker_id": sk_id,
            "name": name,
            "enlightenment_score": cave_depth,
            "divided_line_stage": stage_name,
            "epistemic_realm": epistemic_realm,
            "willing_to_return_katabasis": willing_to_return,
            "qualified_philosopher_king": qualified_as_philosopher_king,
            "description": description
        })

    # 3. Kallipolis Governance & Regime Health
    rulers_count = sum(1 for s in soul_evaluations if s["assigned_metal_class"] == "GOLD_PHILOSOPHER_RULER")
    guardians_count = sum(1 for s in soul_evaluations if s["assigned_metal_class"] == "SILVER_AUXILIARY_WARRIOR")
    producers_count = sum(1 for s in soul_evaluations if s["assigned_metal_class"] == "BRONZE_PRODUCER_ARTISAN")
    just_souls_count = sum(1 for s in soul_evaluations if s["is_just_soul"])
    total_population = max(1, len(soul_evaluations))
    
    justice_index = round((just_souls_count / total_population) * 100.0, 2)
    has_qualified_pk = any(c["qualified_philosopher_king"] for c in cave_evaluations)
    
    if has_qualified_pk and rulers_count >= 1 and guardians_count >= 1 and producers_count >= 1 and justice_index >= 30.0:
        regime_type = "ARISTOCRACY_KALLIPOLIS_JUST_STATE"
    elif guardians_count > rulers_count and guardians_count >= producers_count:
        regime_type = "TIMOCRACY_HONOR_WARRIOR_RULE"
    elif producers_count >= total_population * 0.6:
        regime_type = "OLIGARCHY_PLUTOCRATIC_DECLINE"
    else:
        regime_type = "DEMOCRATIC_ANARCHY_OR_TYRANNY_DECAY"

    result = {
        "kallipolis_state_metrics": {
            "total_citizens": total_population,
            "class_distribution": {
                "gold_rulers": rulers_count,
                "silver_guardians": guardians_count,
                "bronze_producers": producers_count
            },
            "just_souls_count": just_souls_count,
            "societal_justice_index_pct": justice_index,
            "philosopher_king_installed": has_qualified_pk,
            "regime_type": regime_type
        },
        "soul_evaluations": soul_evaluations,
        "cave_epistemic_evaluations": cave_evaluations
    }
    
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    solve()
