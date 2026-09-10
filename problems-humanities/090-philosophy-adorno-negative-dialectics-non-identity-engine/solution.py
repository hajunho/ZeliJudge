# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #090: Theodor W. Adorno Negative Dialectics & Non-Identity Engine.
"""
import sys
import json

sys.stdout.reconfigure(encoding="utf-8")

class AdornoNegativeDialecticsEngine:
    def __init__(self):
        pass

    def evaluate(self, state):
        obj = state.get("object", {})
        attributes = obj.get("attributes", {})
        total_attr_count = len(attributes)
        
        concepts = state.get("concepts", [])
        synthesis_bias = float(state.get("hegelian_synthesis_bias", 0.0))
        
        primary_c = concepts[0] if concepts else {"name": "None", "expected_attributes": []}
        expected_set = set(primary_c.get("expected_attributes", []))
        actual_set = set(attributes.keys())
        
        intersect = actual_set & expected_set
        non_id_set = actual_set - expected_set
        
        subsumption = len(intersect) / len(expected_set) if expected_set else 0.0
        residual_ratio = len(non_id_set) / total_attr_count if total_attr_count > 0 else 0.0
        identitarian_violence = subsumption * residual_ratio
        
        suffering = sum(attributes[k] for k in non_id_set)
        
        subsumptions = []
        coverage = set()
        for c in concepts:
            c_exp = set(c.get("expected_attributes", []))
            c_int = actual_set & c_exp
            coverage.update(c_int)
            s_j = len(c_int) / len(c_exp) if c_exp else 0.0
            subsumptions.append(s_j)
            
        if len(concepts) >= 2:
            prod = 1.0
            for s in subsumptions:
                prod *= (1.0 - s)
            constellation_power = 1.0 - prod
        else:
            constellation_power = 0.0
        
        non_reconciled = 1.0 - synthesis_bias
        
        truth_content = constellation_power * (suffering / (1.0 + identitarian_violence))
        truth_content = max(0.0, min(1.0, truth_content))
        
        if identitarian_violence >= 0.40 and constellation_power < 0.60:
            regime = "TOTALITARIAN_IDENTITY"
        elif truth_content >= 0.40 and non_reconciled >= 0.50:
            regime = "NEGATIVE_CONSTELLATION"
        elif non_reconciled < 0.40 and subsumption >= 0.60:
            regime = "FALSE_HEGELIAN_SYNTHESIS"
        else:
            regime = "DIALECTICAL_TENSION"

        return {
            "identitarian_critique": {
                "subsumed_attributes": sorted(list(intersect)),
                "non_identical_residue": sorted(list(non_id_set)),
                "subsumption_degree": round(subsumption, 4),
                "identitarian_violence": round(identitarian_violence, 4),
                "non_identical_suffering": round(suffering, 4)
            },
            "constellation_metrics": {
                "active_concepts_count": len(concepts),
                "constellation_illumination": round(constellation_power, 4),
                "hegelian_reconciliation": round(synthesis_bias, 4),
                "non_reconciliation_index": round(non_reconciled, 4),
                "truth_content": round(truth_content, 4)
            },
            "critical_regime": regime
        }

def solve():
    raw_data = sys.stdin.read().strip()
    if not raw_data:
        return
    state = json.loads(raw_data)
    engine = AdornoNegativeDialecticsEngine()
    result = engine.evaluate(state)
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    solve()
