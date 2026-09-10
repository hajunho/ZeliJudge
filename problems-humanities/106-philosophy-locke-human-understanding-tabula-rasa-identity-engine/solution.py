import sys
import json

# Windows UTF-8 Output Reconfiguration
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PRIMARY_QUALITIES = {"SOLIDITY", "EXTENSION", "FIGURE", "SHAPE", "MOTION", "REST", "NUMBER", "BULK"}
SECONDARY_QUALITIES = {"COLOR", "SOUND", "TASTE", "SMELL", "HEAT", "COLD"}

def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)
    
    agent_id = input_data.get("agent_id", "Lockean_Tabula_Rasa")
    
    # 1. White Paper / Tabula Rasa: Simple Ideas Store
    simple_ideas_store = {}
    complex_ideas_store = {}
    
    experiences = input_data.get("experiences", [])
    sensation_count = 0
    reflection_count = 0
    
    for exp in experiences:
        source = exp.get("source", "SENSATION")
        if source == "SENSATION":
            sensation_count += 1
        elif source == "REFLECTION":
            reflection_count += 1
            
        ideas = exp.get("ideas", [])
        for idea in ideas:
            idea_id = idea.get("id")
            quality_name = idea.get("quality", "").upper()
            
            # Classify Primary vs Secondary Quality
            if quality_name in PRIMARY_QUALITIES:
                q_type = "PRIMARY"
                resembles_reality = True
            elif quality_name in SECONDARY_QUALITIES:
                q_type = "SECONDARY"
                resembles_reality = False
            else:
                q_type = "OPERATIONAL_OR_COMPOSITE"
                resembles_reality = False
                
            simple_ideas_store[idea_id] = {
                "id": idea_id,
                "name": idea.get("name"),
                "source": source,
                "quality": quality_name,
                "quality_type": q_type,
                "resembles_reality": resembles_reality
            }

    # 2. Mind's Active Operations (Combine, Compare, Abstract)
    operations = input_data.get("operations", [])
    operation_results = []
    
    for op in operations:
        op_type = op.get("type")
        
        if op_type == "COMBINE":
            cid = op.get("complex_id")
            cname = op.get("name")
            category = op.get("category", "SUBSTANCE")
            constituent_ids = op.get("simple_idea_ids", [])
            
            valid_constituents = [simple_ideas_store[sid] for sid in constituent_ids if sid in simple_ideas_store]
            
            complex_ideas_store[cid] = {
                "id": cid,
                "name": cname,
                "category": category,
                "constituents_count": len(valid_constituents),
                "has_primary": any(c["quality_type"] == "PRIMARY" for c in valid_constituents),
                "has_secondary": any(c["quality_type"] == "SECONDARY" for c in valid_constituents)
            }
            operation_results.append({
                "op_id": op.get("id"),
                "type": "COMBINE",
                "result_id": cid,
                "status": "COMPLEX_IDEA_FORMED",
                "category": category
            })
            
        elif op_type == "COMPARE":
            id_a = op.get("idea_a")
            id_b = op.get("idea_b")
            relation_name = op.get("relation_name", "EQUAL")
            operation_results.append({
                "op_id": op.get("id"),
                "type": "COMPARE",
                "relation": relation_name,
                "status": "RELATION_FORMED"
            })
            
        elif op_type == "ABSTRACT":
            general_name = op.get("general_concept") or op.get("general_name", "Universal")
            base_id = op.get("base_idea_id")
            operation_results.append({
                "op_id": op.get("id"),
                "type": "ABSTRACT",
                "general_concept": general_name,
                "status": "ABSTRACT_IDEA_CREATED"
            })

    # 3. Personal Identity & Consciousness Memory Chain
    identity_chains = []
    chains_input = input_data.get("identity_chains", [])
    
    for chain in chains_input:
        chain_id = chain.get("chain_id")
        events = chain.get("chronological_events", [])
        
        continuous = True
        break_point = None
        conscious_memory_depth = 0
        
        prev_event = None
        for ev in events:
            t = ev.get("t")
            mem_prev = ev.get("memory_of_prev", True)
            if prev_event is not None and not mem_prev:
                continuous = False
                break_point = t
                break
            conscious_memory_depth += 1
            prev_event = ev
            
        forensic_status = "FULLY_ACCOUNTABLE_PERSON" if continuous else f"CONSCIOUSNESS_SEVERED_AT_T{break_point}"
        same_person = continuous
        
        identity_chains.append({
            "chain_id": chain_id,
            "is_same_person": same_person,
            "conscious_events_count": conscious_memory_depth,
            "forensic_status": forensic_status
        })

    # Summary Metrics
    primary_count = sum(1 for d in simple_ideas_store.values() if d["quality_type"] == "PRIMARY")
    secondary_count = sum(1 for d in simple_ideas_store.values() if d["quality_type"] == "SECONDARY")
    
    base_score = min(40.0, len(simple_ideas_store) * 4.0) + min(30.0, len(complex_ideas_store) * 10.0)
    if not identity_chains:
        identity_bonus = 0.0
    elif any(c["is_same_person"] for c in identity_chains):
        identity_bonus = 30.0
    else:
        identity_bonus = 10.0
    epistemic_score = round(min(100.0, base_score + identity_bonus), 2)
    
    if epistemic_score >= 80.0:
        verdict = "MATURE_EMPIRICAL_UNDERSTANDING"
    elif epistemic_score >= 50.0:
        verdict = "DEVELOPING_COMPLEX_COGNITION"
    else:
        verdict = "EARLY_TABULA_RASA_IMPRESSION"

    output = {
        "agent_id": agent_id,
        "metrics": {
            "sensation_events": sensation_count,
            "reflection_events": reflection_count,
            "simple_ideas_count": len(simple_ideas_store),
            "primary_qualities_count": primary_count,
            "secondary_qualities_count": secondary_count,
            "complex_ideas_count": len(complex_ideas_store),
            "operations_executed": len(operations),
            "epistemic_maturity_score": epistemic_score
        },
        "verdict": verdict,
        "complex_ideas": complex_ideas_store,
        "operation_results": operation_results,
        "identity_chains": identity_chains
    }
    
    print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))

if __name__ == "__main__":
    solve()
