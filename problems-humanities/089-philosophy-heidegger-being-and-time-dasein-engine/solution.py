# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #089: Martin Heidegger Being and Time Dasein Existential Engine.
"""
import sys
import json

sys.stdout.reconfigure(encoding="utf-8")

class HeideggerDaseinEngine:
    def __init__(self):
        pass

    def evaluate(self, state):
        tools = state.get("equipment_nexus", [])
        total_tools = len(tools)
        functional_count = 0
        conspicuous = []
        obtrusive = []
        obstinate = []
        
        for t in tools:
            name = t["name"]
            status = t.get("status", "FUNCTIONAL")
            deps = t.get("dependencies", [])
            
            has_dep_failure = False
            for d in deps:
                for other in tools:
                    if other["name"] == d and other.get("status") in ("DAMAGED", "MISSING"):
                        has_dep_failure = True
                        break
            
            if status == "DAMAGED":
                conspicuous.append(name)
            elif status == "MISSING" or has_dep_failure:
                obtrusive.append(name)
            elif status == "OBSTRUCTING":
                obstinate.append(name)
            else:
                functional_count += 1
                
        transparency = functional_count / total_tools if total_tools > 0 else 1.0
        world_revealed = 1.0 - transparency
        
        das_man = state.get("das_man", {})
        g = float(das_man.get("gerede_idle_talk", 0.0))
        n = float(das_man.get("neugier_curiosity", 0.0))
        z = float(das_man.get("zweideutigkeit_ambiguity", 0.0))
        falling_index = (g + n + z) / 3.0
        
        affect = state.get("affective_state", {})
        threat_type = affect.get("threat_type", "NONE")
        intensity = float(affect.get("intensity", 0.0))
        
        is_angst = (threat_type == "NOTHINGNESS_IN_THE_WORLD")
        angst_score = intensity if is_angst else 0.0
        fear_score = intensity if (threat_type == "SPECIFIC_OBJECT") else 0.0
        
        falling_eff = falling_index * (1.0 - angst_score)
        
        mortality = float(state.get("mortality_awareness", 0.0))
        anticipation = mortality * angst_score
        
        raw_auth = anticipation * (1.0 - falling_eff) + 0.5 * world_revealed
        authenticity = max(0.0, min(1.0, raw_auth))
        
        if authenticity >= 0.65 and anticipation >= 0.35:
            regime = "AUTHENTIC_RESOLVE"
        elif angst_score >= 0.50 and authenticity >= 0.35:
            regime = "EXISTENTIAL_ANXIETY"
        elif world_revealed >= 0.50:
            regime = "THEMATIC_BREAKDOWN"
        else:
            regime = "FALLEN_EVERYDAYNESS"
            
        return {
            "equipment_analysis": {
                "total_tools": total_tools,
                "functional_count": functional_count,
                "transparency_index": round(transparency, 4),
                "world_revealed_index": round(world_revealed, 4),
                "breakdown_modes": {
                    "conspicuous_damaged": conspicuous,
                    "obtrusive_missing": obtrusive,
                    "obstinate_obstructing": obstinate
                },
                "ontological_mode": "ZUHANDENHEIT" if world_revealed < 0.50 else "VORHANDENHEIT"
            },
            "existential_metrics": {
                "das_man_falling_index": round(falling_index, 4),
                "effective_falling_index": round(falling_eff, 4),
                "angst_score": round(angst_score, 4),
                "fear_score": round(fear_score, 4),
                "death_anticipation": round(anticipation, 4),
                "authenticity_index": round(authenticity, 4)
            },
            "existential_regime": regime
        }

def solve():
    raw_data = sys.stdin.read().strip()
    if not raw_data:
        return
    state = json.loads(raw_data)
    engine = HeideggerDaseinEngine()
    result = engine.evaluate(state)
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    solve()
