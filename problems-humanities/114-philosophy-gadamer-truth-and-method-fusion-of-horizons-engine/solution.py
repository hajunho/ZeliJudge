import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def solve():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    
    agent_id = data.get("agent_id", "Hermeneutic_Interpreter")
    initial_prejudices = data.get("prejudices", [])
    operations = data.get("operations", [])
    
    productive_prejudices = []
    dogmatic_prejudices = []
    
    hermeneutic_iterations = 0
    coherence_score = 30.0
    effective_history_acknowledged = False
    fusion_achieved = False
    fusion_degree = 0.0
    
    text_horizon_concepts = set()
    interpreter_horizon_concepts = set()
    fused_insights = []
    
    action_log = []
    
    for p in initial_prejudices:
        p_name = p.get("name")
        p_type = p.get("type", "PRODUCTIVE")
        if p_type == "PRODUCTIVE":
            productive_prejudices.append(p_name)
        else:
            dogmatic_prejudices.append(p_name)
            
    for op in operations:
        op_type = op.get("op")
        params = op.get("params", {})
        
        if op_type == "HERMENEUTIC_CIRCLE_CYCLE":
            steps = params.get("steps", 1)
            hermeneutic_iterations += steps
            penalty = len(dogmatic_prejudices) * 5.0
            boost = steps * 15.0
            coherence_score = min(100.0, max(0.0, coherence_score + boost - penalty))
            action_log.append({
                "op": "HERMENEUTIC_CIRCLE_CYCLE",
                "iterations_completed": hermeneutic_iterations,
                "coherence_score": round(coherence_score, 2),
                "status": "PART_WHOLE_SYNTHESIS_REFINED"
            })
            
        elif op_type == "ACKNOWLEDGE_EFFECTIVE_HISTORY":
            temporal_distance = params.get("temporal_distance_years", 100)
            awareness = params.get("historically_effected_awareness", True)
            if awareness:
                effective_history_acknowledged = True
                coherence_score = min(100.0, coherence_score + 10.0)
                status = "EFFECTIVE_HISTORICAL_CONSCIOUSNESS_AWAKENED"
            else:
                effective_history_acknowledged = False
                status = "HISTORICIST_OBJECTIVISM_ASSUMED"
            action_log.append({
                "op": "ACKNOWLEDGE_EFFECTIVE_HISTORY",
                "temporal_distance_years": temporal_distance,
                "acknowledged": effective_history_acknowledged,
                "status": status
            })
            
        elif op_type == "FUSE_HORIZONS":
            t_concepts = set(params.get("text_horizon", []))
            i_concepts = set(params.get("interpreter_horizon", []))
            
            text_horizon_concepts.update(t_concepts)
            interpreter_horizon_concepts.update(i_concepts)
            
            overlap = t_concepts.intersection(i_concepts)
            total_unique = t_concepts.union(i_concepts)
            
            if total_unique:
                jaccard = len(overlap) / len(total_unique)
            else:
                jaccard = 0.0
                
            openness = params.get("dialogue_openness", 0.5)
            computed_fusion = (jaccard * 60.0) + (openness * 40.0)
            
            if not effective_history_acknowledged:
                computed_fusion *= 0.5
                
            fusion_degree = round(min(100.0, max(0.0, computed_fusion)), 2)
            fusion_achieved = (fusion_degree >= 50.0)
            
            if fusion_achieved:
                insight = f"FUSED_INSIGHT_ON_{'_AND_'.join(sorted(list(overlap)) if overlap else ['SYNTHESIS'])}"
                fused_insights.append(insight)
                status = "HORIZONTVERSCHMELZUNG_ACHIEVED"
            else:
                status = "HORIZONS_REMAIN_DISCONNECTED"
                
            action_log.append({
                "op": "FUSE_HORIZONS",
                "fusion_degree": fusion_degree,
                "fusion_achieved": fusion_achieved,
                "status": status
            })
            
        elif op_type == "REVISE_PREJUDICE":
            p_to_remove = params.get("remove_dogma")
            if p_to_remove in dogmatic_prejudices:
                dogmatic_prejudices.remove(p_to_remove)
                productive_prejudices.append(p_to_remove + "_CRITICALLY_TRANSFORMED")
                coherence_score = min(100.0, coherence_score + 15.0)
                status = "DOGMATIC_PREJUDICE_OVERCOME"
            else:
                status = "PREJUDICE_NOT_FOUND"
            action_log.append({
                "op": "REVISE_PREJUDICE",
                "target": p_to_remove,
                "status": status
            })

    if fusion_achieved and effective_history_acknowledged and coherence_score >= 70.0:
        verdict = "AUTHENTIC_HERMENEUTIC_UNDERSTANDING"
    elif not effective_history_acknowledged and fusion_degree < 40.0:
        verdict = "OBJECTIVIST_HISTORICISM"
    elif len(dogmatic_prejudices) > len(productive_prejudices):
        verdict = "ANACHRONISTIC_DOGMATISM"
    else:
        verdict = "PRE_HERMENEUTIC_EXPLORER"
        
    result = {
        "agent_id": agent_id,
        "metrics": {
            "coherence_score": round(coherence_score, 2),
            "hermeneutic_iterations": hermeneutic_iterations,
            "effective_history_acknowledged": effective_history_acknowledged,
            "fusion_degree": fusion_degree,
            "fusion_achieved": fusion_achieved,
            "productive_prejudices_count": len(productive_prejudices),
            "dogmatic_prejudices_count": len(dogmatic_prejudices)
        },
        "verdict": verdict,
        "fused_insights": fused_insights,
        "action_log": action_log
    }
    
    print(json.dumps(result, separators=(",", ":"), ensure_ascii=False))

if __name__ == "__main__":
    solve()
