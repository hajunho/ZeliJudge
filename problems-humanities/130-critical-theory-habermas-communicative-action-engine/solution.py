# -*- coding: utf-8 -*-
"""
ZeliJudge Humanities Track Problem #130: Jürgen Habermas: The Theory of Communicative Action Engine
Canonical Solution Implementation
"""
import sys
import json

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class HabermasDiscourseEngine:
    def __init__(self, config):
        self.participants = {p["id"]: dict(p) for p in config.get("participants", [])}
        self.lifeworld = dict(config.get("lifeworld", {
            "cultural_meaning": 800.0,
            "social_integration": 800.0,
            "socialization": 800.0,
            "colonization_index": 0.10
        }))
        self.system_pressures = dict(config.get("system_pressures", {
            "monetization_rate": 0.05,
            "bureaucratization_rate": 0.05
        }))
        self.sessions_history = []
        self.legitimate_norms = []
        self.distorted_norms = []

    def evaluate_session(self, session):
        sess_id = session["session_id"]
        target_norm = session["target_norm"]
        itype = session.get("interaction_type", "COMMUNICATIVE")
        claims = session.get("claims", [])
        objections = session.get("objections", [])
        intrusion = session.get("system_intrusion", {"bribe_money": 0, "coercive_power": 0})
        
        bribe = intrusion.get("bribe_money", 0)
        coercion = intrusion.get("coercive_power", 0)

        claim_scores = {
            "COMPREHENSIBILITY": 1.0,
            "TRUTH": 1.0,
            "RIGHTNESS": 1.0,
            "TRUTHFULNESS": 1.0
        }
        
        for c in claims:
            ctype = c.get("claim_type", "TRUTH")
            sp_id = c.get("speaker_id")
            sp = self.participants.get(sp_id, {"competence": 0.8, "lifeworld_anchoring": 0.8})
            
            comp_score = c.get("comprehensibility", 1.0) * sp.get("competence", 1.0)
            truth_score = c.get("evidence_score", 0.8)
            sincerity_score = c.get("sincerity_score", 0.8)
            rightness_score = c.get("normative_justification", 0.8) * sp.get("lifeworld_anchoring", 0.8)
            
            if ctype == "COMPREHENSIBILITY":
                claim_scores["COMPREHENSIBILITY"] = min(claim_scores["COMPREHENSIBILITY"], comp_score)
            elif ctype == "TRUTH":
                claim_scores["TRUTH"] = min(claim_scores["TRUTH"], truth_score)
            elif ctype == "RIGHTNESS":
                claim_scores["RIGHTNESS"] = min(claim_scores["RIGHTNESS"], rightness_score)
            elif ctype == "TRUTHFULNESS":
                claim_scores["TRUTHFULNESS"] = min(claim_scores["TRUTHFULNESS"], sincerity_score)

        unresolved_objections = 0
        for obj in objections:
            target_claim = obj.get("target_claim")
            strength = obj.get("strength", 0.5)
            if target_claim in claim_scores:
                if strength > claim_scores[target_claim]:
                    claim_scores[target_claim] = round(max(0.0, claim_scores[target_claim] - strength * 0.5), 3)
                    unresolved_objections += 1

        claims_valid = all(v >= 0.65 for v in claim_scores.values())
        coercion_free = (bribe == 0 and coercion == 0)
        
        speakers = set(c.get("speaker_id") for c in claims)
        total_parts = len(self.participants)
        symmetry_ratio = round(len(speakers) / max(1, total_parts), 3)
        is_symmetrical = (symmetry_ratio >= 0.5)

        status = "FAILED"
        detail = ""
        legitimacy = 0.0

        if itype == "COMMUNICATIVE":
            if claims_valid and coercion_free and is_symmetrical and unresolved_objections == 0:
                status = "CONSENSUS_REACHED"
                legitimacy = round(sum(claim_scores.values()) / 4.0 * min(1.0, symmetry_ratio + 0.2), 3)
                detail = "unforced force of the better argument prevailed; rational communicative consensus achieved"
                self.legitimate_norms.append({"session_id": sess_id, "norm": target_norm, "legitimacy": legitimacy})
                
                self.lifeworld["social_integration"] = round(min(1000.0, self.lifeworld["social_integration"] + 25.0), 2)
                self.lifeworld["cultural_meaning"] = round(min(1000.0, self.lifeworld["cultural_meaning"] + 20.0), 2)
                self.lifeworld["colonization_index"] = round(max(0.0, self.lifeworld["colonization_index"] - 0.03), 3)
            else:
                status = "DISSENSUS"
                legitimacy = round(sum(claim_scores.values()) / 8.0, 3)
                reasons = []
                if not claims_valid:
                    failed_claims = [k for k, v in claim_scores.items() if v < 0.65]
                    reasons.append(f"failed validity claims ({','.join(failed_claims)})")
                if not is_symmetrical:
                    reasons.append(f"insufficient symmetry ({symmetry_ratio})")
                if unresolved_objections > 0:
                    reasons.append(f"{unresolved_objections} unresolved objections")
                if not coercion_free:
                    reasons.append(f"coercion or bribe present ({bribe},{coercion})")
                detail = "rational discourse ended in dissensus: " + "; ".join(reasons)
        else: # STRATEGIC
            if bribe > 0 or coercion > 0:
                status = "COLONIZED_COMPROMISE"
                legitimacy = round(max(0.05, 0.30 - (bribe + coercion) * 0.001), 3)
                detail = f"lifeworld colonized by steering media (bribe={bribe}, coercion={coercion}); pseudo-consensus imposed"
                self.distorted_norms.append({"session_id": sess_id, "norm": target_norm, "coercion_score": bribe + coercion})
                
                erosion = (bribe * 0.05 + coercion * 0.1)
                self.lifeworld["social_integration"] = round(max(0.0, self.lifeworld["social_integration"] - erosion), 2)
                self.lifeworld["cultural_meaning"] = round(max(0.0, self.lifeworld["cultural_meaning"] - erosion * 0.8), 2)
                self.lifeworld["colonization_index"] = round(min(1.0, self.lifeworld["colonization_index"] + 0.05 + (erosion * 0.001)), 3)
            else:
                status = "STRATEGIC_DEADLOCK"
                legitimacy = 0.10
                detail = "egocentric utility-maximizing actors failed to reach strategic equilibrium"

        record = {
            "session_id": sess_id,
            "target_norm": target_norm,
            "interaction_type": itype,
            "status": status,
            "legitimacy_score": legitimacy,
            "claim_scores": claim_scores,
            "symmetry_ratio": symmetry_ratio,
            "detail": detail
        }
        self.sessions_history.append(record)

    def get_summary(self):
        total_sessions = len(self.sessions_history)
        consensus_count = sum(1 for s in self.sessions_history if s["status"] == "CONSENSUS_REACHED")
        colonized_count = sum(1 for s in self.sessions_history if s["status"] == "COLONIZED_COMPROMISE")
        dissensus_count = sum(1 for s in self.sessions_history if s["status"] in ("DISSENSUS", "STRATEGIC_DEADLOCK"))
        
        pathology = "HEALTHY_DEMOCRATIC_SPHERE"
        if self.lifeworld["colonization_index"] >= 0.70:
            pathology = "LEGITIMATION_CRISIS_AND_ANOMIE"
        elif self.lifeworld["colonization_index"] >= 0.40:
            pathology = "SIGNIFICANT_SYSTEM_COLONIZATION"

        return {
            "total_sessions": total_sessions,
            "consensus_count": consensus_count,
            "colonized_count": colonized_count,
            "dissensus_count": dissensus_count,
            "lifeworld_status": {
                "cultural_meaning": self.lifeworld["cultural_meaning"],
                "social_integration": self.lifeworld["social_integration"],
                "socialization": self.lifeworld["socialization"],
                "colonization_index": self.lifeworld["colonization_index"],
                "pathology_state": pathology
            },
            "legitimate_norms_count": len(self.legitimate_norms),
            "distorted_norms_count": len(self.distorted_norms)
        }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    eng = HabermasDiscourseEngine(data["config"])
    for sess in data["sessions"]:
        eng.evaluate_session(sess)
    result = {
        "history": eng.sessions_history,
        "summary": eng.get_summary()
    }
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
