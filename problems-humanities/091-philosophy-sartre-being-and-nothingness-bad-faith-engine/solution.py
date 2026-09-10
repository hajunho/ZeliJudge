# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #091: Jean-Paul Sartre Being and Nothingness Existential Engine.
"""
import sys
import json

sys.stdout.reconfigure(encoding="utf-8")

class SartreBeingAndNothingnessEngine:
    def __init__(self):
        pass

    def evaluate(self, state):
        facticity_list = state.get("facticity", [])
        f_total = sum(f["weight"] for f in facticity_list) / len(facticity_list) if facticity_list else 0.0
        
        trans_cfg = state.get("transcendence", {})
        proj = float(trans_cfg.get("freedom_projection", 0.0))
        nihilation = float(trans_cfg.get("nihilation_capacity", 0.0))
        t_total = min(1.0, proj * (1.0 + 0.5 * nihilation))
        
        role_rigidity = float(state.get("role_rigidity", 0.0))
        commitment_denial = float(state.get("commitment_denial", 0.0))
        
        bf_a = max(0.0, f_total - t_total) * role_rigidity
        bf_b = max(0.0, t_total - f_total) * commitment_denial
        bad_faith = min(1.0, bf_a + bf_b)
        
        gaze = state.get("the_look", {})
        other_present = gaze.get("other_present", False)
        g_intensity = float(gaze.get("gaze_intensity", 0.0)) if other_present else 0.0
        defensiveness = float(gaze.get("defensiveness", 0.0))
        
        world_hemorrhage = g_intensity * (1.0 - defensiveness)
        objectification = g_intensity * f_total
        shame = objectification * (1.0 - 0.5 * bad_faith)
        
        anguish = t_total * (1.0 - bad_faith)
        
        if bad_faith >= 0.50:
            regime = "MAUVAISE_FOI"
        elif g_intensity >= 0.60 and objectification >= 0.45:
            regime = "LE_REGARD_OBJECTIFIED"
        elif anguish >= 0.50 and bad_faith < 0.35:
            regime = "AUTHENTIC_FREEDOM"
        else:
            regime = "EN_SOI_POUR_SOI_TENSION"

        return {
            "ontological_structure": {
                "facticity_score": round(f_total, 4),
                "transcendence_score": round(t_total, 4),
                "bad_faith_index": round(bad_faith, 4),
                "bad_faith_components": {
                    "role_thingification": round(bf_a, 4),
                    "facticity_disavowal": round(bf_b, 4)
                }
            },
            "intersubjective_gaze_metrics": {
                "other_present": other_present,
                "gaze_intensity": round(g_intensity, 4),
                "world_hemorrhage": round(world_hemorrhage, 4),
                "objectification_index": round(objectification, 4),
                "shame_index": round(shame, 4)
            },
            "existential_freedom": {
                "anguish_score": round(anguish, 4),
                "authentic_choice_capacity": round(max(0.0, 1.0 - bad_faith), 4)
            },
            "existential_regime": regime
        }

def solve():
    raw_data = sys.stdin.read().strip()
    if not raw_data:
        return
    state = json.loads(raw_data)
    engine = SartreBeingAndNothingnessEngine()
    result = engine.evaluate(state)
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    solve()
