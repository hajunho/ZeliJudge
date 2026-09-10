# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #092: Friedrich Nietzsche Genealogy of Morals Ressentiment Engine.
"""
import sys
import json

sys.stdout.reconfigure(encoding="utf-8")

class NietzscheMoralGenealogyEngine:
    def __init__(self):
        pass

    def evaluate(self, state):
        noble = state.get("nobles", {})
        v_noble = float(noble.get("vital_potency", 0.0))
        a_noble = float(noble.get("self_affirmation", 0.0))
        p_act_noble = float(noble.get("action_primacy", 0.0))
        
        slave = state.get("slaves", {})
        w_slave = float(slave.get("powerlessness", 0.0))
        s_slave = float(slave.get("suffering", 0.0))
        h_slave = float(slave.get("reactive_hostility", 0.0))
        p_act_slave = float(slave.get("action_primacy", 0.0))
        
        ressentiment = min(1.0, h_slave * w_slave * (1.0 - p_act_slave) * (1.0 + 0.5 * s_slave))
        
        master_good = a_noble * v_noble
        master_bad = max(0.0, 1.0 - v_noble) * 0.5
        
        slave_evil = min(1.0, ressentiment * v_noble)
        slave_good = w_slave * (1.0 - 0.5 * h_slave)
        
        guilt_cfg = state.get("guilt_mechanics", {})
        debt = float(guilt_cfg.get("contractual_debt", 0.0))
        internalized_cruelty = float(guilt_cfg.get("internalized_cruelty", 0.0))
        ascetic_priest = float(guilt_cfg.get("ascetic_priest_influence", 0.0))
        
        bad_conscience = min(1.0, internalized_cruelty * debt * (1.0 + ascetic_priest))
        
        if ressentiment >= 0.55 and bad_conscience >= 0.45:
            regime = "SLAVE_MORALITY_TRIUMPH"
        elif ressentiment >= 0.45:
            regime = "RESSENTIMENT_FERMENTATION"
        elif a_noble >= 0.60 and ressentiment < 0.35:
            regime = "MASTER_NOBLE_AFFIRMATION"
        else:
            regime = "NIHILISTIC_TRANSITION"

        return {
            "ressentiment_metrics": {
                "ressentiment_score": round(ressentiment, 4),
                "slave_revolt_triggered": ressentiment >= 0.45,
                "reactive_hostility": round(h_slave, 4),
                "powerlessness": round(w_slave, 4)
            },
            "valuation_systems": {
                "master_morality": {
                    "mode": "GOOD_VS_BAD",
                    "primary_good_affirmation": round(master_good, 4),
                    "derivative_bad": round(master_bad, 4)
                },
                "slave_morality": {
                    "mode": "EVIL_VS_GOOD",
                    "primary_evil_imputation": round(slave_evil, 4),
                    "derivative_good_sanctification": round(slave_good, 4)
                }
            },
            "guilt_and_conscience": {
                "contractual_debt": round(debt, 4),
                "bad_conscience_index": round(bad_conscience, 4),
                "ascetic_priest_influence": round(ascetic_priest, 4)
            },
            "genealogical_regime": regime
        }

def solve():
    raw_data = sys.stdin.read().strip()
    if not raw_data:
        return
    state = json.loads(raw_data)
    engine = NietzscheMoralGenealogyEngine()
    result = engine.evaluate(state)
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    solve()
