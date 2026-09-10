import sys
import json

class KuhnParadigmEngine:
    def __init__(self, initial_paradigm):
        self.active_paradigm = initial_paradigm
        self.competing_paradigms = {}
        self.state = "NORMAL_SCIENCE"
        
        self.solved_puzzles = 0
        self.accumulated_anomalies = []
        self.total_anomaly_severity = 0.0
        
        self.stats = {
            "puzzles_solved": 0,
            "anomalies_encountered": 0,
            "paradigm_shifts": 0,
            "crises_triggered": 0
        }

    def observe_phenomenon(self, pheno_id, description, expected_prediction, observed_outcome, severity=1.0):
        if expected_prediction == observed_outcome:
            self.solved_puzzles += 1
            self.stats["puzzles_solved"] += 1
            return {
                "phenomenon_id": pheno_id,
                "status": "PUZZLE_SOLVED",
                "current_state": self.state,
                "paradigm_id": self.active_paradigm["id"]
            }
        else:
            anomaly = {
                "id": pheno_id,
                "description": description,
                "severity": severity,
                "expected": expected_prediction,
                "observed": observed_outcome
            }
            self.accumulated_anomalies.append(anomaly)
            self.total_anomaly_severity += severity
            self.stats["anomalies_encountered"] += 1
            
            threshold = self.active_paradigm["anomaly_threshold"]
            if self.total_anomaly_severity >= threshold and self.state == "NORMAL_SCIENCE":
                self.state = "CRISIS"
                self.stats["crises_triggered"] += 1
                
            return {
                "phenomenon_id": pheno_id,
                "status": "ANOMALY_RECORDED",
                "severity": severity,
                "total_severity": round(self.total_anomaly_severity, 2),
                "threshold": threshold,
                "current_state": self.state
            }

    def propose_paradigm(self, paradigm_data):
        p_id = paradigm_data["id"]
        self.competing_paradigms[p_id] = paradigm_data
        if self.state == "CRISIS":
            self.state = "REVOLUTION"
        return {"proposed_paradigm_id": p_id, "current_state": self.state}

    def evaluate_revolution(self, candidate_paradigm_id):
        if candidate_paradigm_id not in self.competing_paradigms:
            return {"status": "PARADIGM_NOT_FOUND"}
            
        candidate = self.competing_paradigms[candidate_paradigm_id]
        resolves = set(candidate.get("resolves_anomalies", []))
        
        resolved_sev = sum(a["severity"] for a in self.accumulated_anomalies if a["id"] in resolves)
        unresolved = [a for a in self.accumulated_anomalies if a["id"] not in resolves]
        
        success = (self.total_anomaly_severity > 0 and resolved_sev / self.total_anomaly_severity >= 0.75)
        
        if success:
            old_p = self.active_paradigm
            self.active_paradigm = candidate
            self.state = "NORMAL_SCIENCE"
            self.stats["paradigm_shifts"] += 1
            
            self.accumulated_anomalies = unresolved
            self.total_anomaly_severity = sum(a["severity"] for a in unresolved)
            
            return {
                "status": "PARADIGM_SHIFT_COMPLETED",
                "former_paradigm": old_p["id"],
                "new_active_paradigm": candidate["id"],
                "resolved_severity": round(resolved_sev, 2),
                "remaining_anomaly_count": len(unresolved),
                "new_state": self.state
            }
        else:
            return {
                "status": "REVOLUTION_REJECTED",
                "candidate_id": candidate["id"],
                "resolved_severity": round(resolved_sev, 2),
                "required_severity": round(self.total_anomaly_severity * 0.75, 2),
                "current_state": self.state
            }

    def analyze_incommensurability(self, other_paradigm_id):
        if other_paradigm_id not in self.competing_paradigms and other_paradigm_id != self.active_paradigm["id"]:
            return {"status": "NOT_FOUND"}
            
        other = self.competing_paradigms[other_paradigm_id] if other_paradigm_id in self.competing_paradigms else self.active_paradigm
        v1 = self.active_paradigm.get("vocabulary", {})
        v2 = other.get("vocabulary", {})
        
        common_terms = set(v1.keys()) & set(v2.keys())
        shifted_terms = []
        for t in sorted(common_terms):
            if v1[t] != v2[t]:
                shifted_terms.append({
                    "term": t,
                    "meaning_in_active": v1[t],
                    "meaning_in_target": v2[t]
                })
                
        incomm_index = round(len(shifted_terms) / len(common_terms), 2) if common_terms else 1.0
        
        return {
            "active_paradigm": self.active_paradigm["id"],
            "target_paradigm": other["id"],
            "shared_terms_count": len(common_terms),
            "shifted_terms_count": len(shifted_terms),
            "incommensurability_index": incomm_index,
            "semantic_shifts": shifted_terms
        }

    def get_snapshot(self):
        return {
            "active_paradigm": self.active_paradigm["id"],
            "active_paradigm_name": self.active_paradigm["name"],
            "epistemological_state": self.state,
            "accumulated_anomaly_count": len(self.accumulated_anomalies),
            "total_anomaly_severity": round(self.total_anomaly_severity, 2),
            "anomaly_threshold": self.active_paradigm["anomaly_threshold"],
            "metrics": dict(self.stats)
        }

def run_simulation(req):
    init_p = req.get("initial_paradigm", {})
    engine = KuhnParadigmEngine(init_p)
    
    logs = []
    for op_item in req.get("operations", []):
        step = op_item["step"]
        op = op_item["op"]
        
        if op == "OBSERVE_PHENOMENON":
            res = engine.observe_phenomenon(
                pheno_id=op_item["phenomenon_id"],
                description=op_item.get("description", ""),
                expected_prediction=op_item["expected_prediction"],
                observed_outcome=op_item["observed_outcome"],
                severity=op_item.get("severity", 1.0)
            )
            logs.append({"step": step, "op": op, **res})
            
        elif op == "PROPOSE_PARADIGM":
            res = engine.propose_paradigm(op_item["paradigm"])
            logs.append({"step": step, "op": op, **res})
            
        elif op == "EVALUATE_REVOLUTION":
            cand_id = op_item["candidate_id"]
            res = engine.evaluate_revolution(cand_id)
            logs.append({"step": step, "op": op, **res})
            
        elif op == "ANALYZE_INCOMMENSURABILITY":
            target_id = op_item["target_paradigm_id"]
            res = engine.analyze_incommensurability(target_id)
            logs.append({"step": step, "op": op, **res})
            
        elif op == "GET_SNAPSHOT":
            snap = engine.get_snapshot()
            logs.append({"step": step, "op": op, "snapshot": snap})
            
    final_snap = engine.get_snapshot()
    return {
        "operations_log": logs,
        "final_state": final_snap
    }

def main():
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        
    raw_in = sys.stdin.read().strip()
    if not raw_in:
        return
        
    req = json.loads(raw_in)
    res = run_simulation(req)
    print(json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    main()
