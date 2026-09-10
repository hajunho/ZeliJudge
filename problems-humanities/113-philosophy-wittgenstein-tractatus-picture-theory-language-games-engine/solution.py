import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def solve():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    
    agent_id = data.get("agent_id", "Ludwig_Wittgenstein_Analyst")
    paradigm = data.get("initial_paradigm", "TRACTATUS").upper()
    operations = data.get("operations", [])
    
    world_facts = set(data.get("world_facts", []))
    known_objects = set(data.get("known_objects", []))
    
    analyzed_propositions = []
    language_games_played = []
    family_resemblance_results = []
    private_language_evaluations = []
    
    silence_invoked_count = 0
    nonsense_detected_count = 0
    
    action_log = []
    
    for op in operations:
        op_type = op.get("op")
        params = op.get("params", {})
        
        if op_type == "ANALYZE_PROPOSITION_TRACTATUS":
            text = params.get("text", "")
            prop_type = params.get("category", "EMPIRICAL")
            terms = params.get("terms", [])
            
            if prop_type == "EMPIRICAL":
                all_mapped = all(t in known_objects for t in terms)
                fact_match = (text in world_facts) or all_mapped
                status = "HAS_SENSE_TRUE" if fact_match else "HAS_SENSE_FALSE"
                classification = "SINN"
            elif prop_type == "TAUTOLOGY":
                status = "LOGICAL_TAUTOLOGY"
                classification = "SINNLOS"
            elif prop_type in ("ETHICAL", "METAPHYSICAL", "MYSTICAL"):
                status = "TRANSCENDS_LANGUAGE_MUST_BE_SILENT"
                classification = "UNSINN"
                silence_invoked_count += 1
                nonsense_detected_count += 1
            else:
                status = "UNCLASSIFIED"
                classification = "UNSINN"
                
            entry = {
                "text": text,
                "prop_type": prop_type,
                "classification": classification,
                "status": status,
                "proposition_7_applied": (classification == "UNSINN")
            }
            analyzed_propositions.append(entry)
            action_log.append({
                "op": "ANALYZE_PROPOSITION_TRACTATUS",
                "text": text,
                "classification": classification,
                "status": status
            })
            
        elif op_type == "PLAY_LANGUAGE_GAME":
            form_of_life = params.get("form_of_life", "BUILDER_SITE")
            token = params.get("token", "SLAB")
            action_context = params.get("action_context", "REQUEST_BUILDING_STONE")
            
            meaning_resolved = f"USE_AS_{action_context}_IN_{form_of_life}"
            
            entry = {
                "token": token,
                "form_of_life": form_of_life,
                "action_context": action_context,
                "meaning_as_use": meaning_resolved,
                "status": "MEANING_CONSTITUTED_BY_PRACTICE"
            }
            language_games_played.append(entry)
            action_log.append({
                "op": "PLAY_LANGUAGE_GAME",
                "token": token,
                "form_of_life": form_of_life,
                "meaning_as_use": meaning_resolved
            })
            
        elif op_type == "CHECK_FAMILY_RESEMBLANCE":
            concept = params.get("concept", "GAME")
            instances = params.get("instances", [])
            
            all_features = set()
            for inst in instances:
                all_features.update(inst.get("features", []))
                
            universal_essence = []
            for feat in all_features:
                if all(feat in inst.get("features", []) for inst in instances):
                    universal_essence.append(feat)
                    
            has_single_essence = (len(universal_essence) > 0)
            network_overlap = not has_single_essence and (len(instances) >= 2)
            
            res = {
                "concept": concept,
                "instance_count": len(instances),
                "universal_essence_found": has_single_essence,
                "universal_features": universal_essence,
                "family_resemblance_valid": network_overlap or has_single_essence,
                "status": "CRISS_CROSSING_SIMILARITIES" if network_overlap else "ESSENTIAL_MATCH"
            }
            family_resemblance_results.append(res)
            action_log.append({
                "op": "CHECK_FAMILY_RESEMBLANCE",
                "concept": concept,
                "universal_essence_found": has_single_essence,
                "status": res["status"]
            })
            
        elif op_type == "TEST_PRIVATE_LANGUAGE":
            sensation_name = params.get("sensation_name", "S")
            has_public_criterion = params.get("has_public_criterion", False)
            
            if has_public_criterion:
                status = "RULE_FOLLOWING_LEGITIMATE"
                valid = True
            else:
                status = "PRIVATE_LANGUAGE_FALLACY_BEETLE_DROPPED"
                valid = False
                
            eval_entry = {
                "sensation_name": sensation_name,
                "has_public_criterion": has_public_criterion,
                "valid_rule_following": valid,
                "status": status
            }
            private_language_evaluations.append(eval_entry)
            action_log.append({
                "op": "TEST_PRIVATE_LANGUAGE",
                "sensation": sensation_name,
                "status": status
            })

    if language_games_played or family_resemblance_results or private_language_evaluations:
        verdict = "ORDINARY_LANGUAGE_THERAPIST"
    elif silence_invoked_count >= 1 and analyzed_propositions:
        verdict = "TRACTARIAN_LOGICAL_ATOMIST"
    else:
        verdict = "METAPHYSICAL_DOGMATIST"
        
    result = {
        "agent_id": agent_id,
        "paradigm": paradigm,
        "metrics": {
            "propositions_analyzed": len(analyzed_propositions),
            "silence_invoked_count": silence_invoked_count,
            "nonsense_detected_count": nonsense_detected_count,
            "language_games_count": len(language_games_played),
            "family_resemblance_cases": len(family_resemblance_results),
            "private_language_tests": len(private_language_evaluations)
        },
        "verdict": verdict,
        "tractatus_analysis": analyzed_propositions,
        "language_games": language_games_played,
        "family_resemblances": family_resemblance_results,
        "private_language_evaluations": private_language_evaluations,
        "action_log": action_log
    }
    
    print(json.dumps(result, separators=(",", ":"), ensure_ascii=False))

if __name__ == "__main__":
    solve()
