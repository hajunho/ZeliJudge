# -*- coding: utf-8 -*-
import sys
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

class FregeanSemanticEngine:
    def __init__(self, ontology=None):
        ontology = ontology or {}
        self.objects = ontology.get("objects", {})
        self.senses = ontology.get("senses", {})
        self.agents = ontology.get("agents", {})

    def evaluate_identity(self, expr_a, expr_b):
        sense_a = self.senses.get(expr_a)
        sense_b = self.senses.get(expr_b)

        if not sense_a or not sense_b:
            return {"error": f"UNKNOWN_EXPRESSION_{expr_a if not sense_a else expr_b}"}

        ref_a = sense_a.get("referent_id")
        ref_b = sense_b.get("referent_id")

        has_ref_a = (ref_a is not None and ref_a in self.objects)
        has_ref_b = (ref_b is not None and ref_b in self.objects)

        if not has_ref_a or not has_ref_b:
            return {
                "identity_statement": f"{expr_a} = {expr_b}",
                "sense_a": sense_a.get("description"),
                "sense_b": sense_b.get("description"),
                "has_truth_value": False,
                "status": "EMPTY_NAME_LACKS_TRUTH_VALUE",
                "cognitive_value": "SYNTHETIC_EMPTY"
            }

        is_true = (ref_a == ref_b)
        if expr_a == expr_b:
            cog_val = "TRIVIAL_APRIORI (a = a)"
        elif is_true:
            cog_val = "INFORMATIVE_APOSTERIORI_DISCOVERY (a = b)"
        else:
            cog_val = "FALSE_SYNTHETIC"

        return {
            "identity_statement": f"{expr_a} = {expr_b}",
            "referent": ref_a if is_true else None,
            "referent_a": ref_a,
            "referent_b": ref_b,
            "is_identical": is_true,
            "truth_value": is_true,
            "cognitive_value": cog_val
        }

    def evaluate_propositional_attitude(self, agent_id, expr_subject, expr_predicate, substituted_subject=None):
        agent = self.agents.get(agent_id, {})
        known_identities = [tuple(k) for k in agent.get("known_identities", [])]
        beliefs = [tuple(b) for b in agent.get("beliefs", [])]

        primary_belief_true = (expr_subject, expr_predicate) in beliefs

        if substituted_subject is None:
            return {
                "agent": agent_id,
                "statement": f"{agent_id} believes that {expr_subject} is {expr_predicate}",
                "belief_held": primary_belief_true
            }

        knows_identity = (
            (expr_subject, substituted_subject) in known_identities or
            (substituted_subject, expr_subject) in known_identities
        )
        substituted_belief_true = (substituted_subject, expr_predicate) in beliefs or (primary_belief_true and knows_identity)

        ref_orig = self.senses.get(expr_subject, {}).get("referent_id")
        ref_sub = self.senses.get(substituted_subject, {}).get("referent_id")
        actually_co_refer = (ref_orig is not None and ref_orig == ref_sub)

        salva_veritate_failed = (actually_co_refer and primary_belief_true != substituted_belief_true)

        return {
            "agent": agent_id,
            "original_statement": f"{agent_id} believes that {expr_subject} is {expr_predicate}",
            "original_belief": primary_belief_true,
            "substituted_statement": f"{agent_id} believes that {substituted_subject} is {expr_predicate}",
            "substituted_belief": substituted_belief_true,
            "actually_co_refer": actually_co_refer,
            "agent_knows_identity": knows_identity,
            "salva_veritate_failed": salva_veritate_failed,
            "fregean_explanation": "INDIRECT_REFERENCE_IS_SENSE_NOT_OBJECT" if salva_veritate_failed else "EXTENSIONAL_SUBSTITUTION_PRESERVED"
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    ontology = data.get("ontology", {})
    operation = data.get("operation")
    params = data.get("params", {})
    engine = FregeanSemanticEngine(ontology)

    if operation == "evaluate_identity":
        res = engine.evaluate_identity(params.get("expr_a"), params.get("expr_b"))
    elif operation == "evaluate_propositional_attitude":
        res = engine.evaluate_propositional_attitude(
            params.get("agent_id"),
            params.get("expr_subject"),
            params.get("expr_predicate"),
            params.get("substituted_subject")
        )
    else:
        res = {"error": f"UNKNOWN_OPERATION_{operation}"}

    print(json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    main()
