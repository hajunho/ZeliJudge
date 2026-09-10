import sys
import os
import json

class BanalityOfEvilEngine:
    def __init__(self, config: dict):
        self.bureaucratic_euphemisms = set(config.get("bureaucratic_euphemisms", [
            "special_treatment", "evacuation", "final_solution", "administrative_measure",
            "duty_bound", "orders_from_above", "standard_procedure", "relocation"
        ]))
        self.critical_inquiry_keywords = set(config.get("critical_inquiry_keywords", [
            "moral_responsibility", "human_dignity", "questioning_authority", "empathy",
            "autonomous_choice", "conscience", "self_reflection"
        ]))
        self.agents = {}
        self.event_log = []
        self.history = []
        self.stats = {
            "evaluations": 0,
            "banality_of_evil_count": 0,
            "bureaucratic_conformism_count": 0,
            "autonomous_conscience_count": 0,
            "max_banality_index": 0.0
        }

    def log(self, msg: str):
        self.event_log.append(msg)

    def register_agent(self, agent_id: str, name: str, role: str):
        self.agents[agent_id] = {
            "name": name,
            "role": role,
            "orders_received": 0,
            "orders_blindly_executed": 0,
            "euphemisms_used": 0,
            "critical_inquiries": 0,
            "self_reflections": 0,
            "cliche_count": 0,
            "banality_index": 0.0,
            "state": "UNEXAMINED"
        }
        self.log(f"REGISTER_AGENT id={agent_id} name={name} role={role}")

    def process_action(self, agent_id: str, action: dict) -> dict:
        agent = self.agents[agent_id]
        act_type = action.get("type", "EXECUTE_ORDER")
        euphemisms = action.get("euphemisms", [])
        inquiries = action.get("critical_inquiries", [])
        empathy_shown = action.get("empathy_shown", False)
        is_blind_compliance = action.get("blind_compliance", True)

        if act_type == "RECEIVE_ORDER":
            agent["orders_received"] += 1
        elif act_type == "EXECUTE_ORDER":
            agent["orders_received"] += 1
            if is_blind_compliance:
                agent["orders_blindly_executed"] += 1

        detected_euphemisms = sum(1 for e in euphemisms if e in self.bureaucratic_euphemisms)
        detected_inquiries = sum(1 for q in inquiries if q in self.critical_inquiry_keywords)

        agent["euphemisms_used"] += detected_euphemisms
        agent["cliche_count"] += action.get("cliche_phrases_count", 0)
        agent["critical_inquiries"] += detected_inquiries
        if not is_blind_compliance or detected_inquiries > 0:
            agent["self_reflections"] += 1

        # 1. Thoughtlessness Score
        reflection_score = min(1.0, agent["critical_inquiries"] * 0.3 + agent["self_reflections"] * 0.2)
        thoughtlessness = round(max(0.0, 1.0 - reflection_score), 4)

        # 2. Cliche Reliance Score
        cliche_total = agent["euphemisms_used"] + agent["cliche_count"]
        vocab_total = cliche_total + agent["critical_inquiries"]
        if vocab_total > 0:
            cliche_reliance = round(min(1.0, cliche_total / vocab_total), 4)
        else:
            cliche_reliance = 0.0

        # 3. Moral Outsourcing
        moral_outsourcing = round(agent["orders_blindly_executed"] / max(1, agent["orders_received"]), 4)

        # 4. Lack of Empathy
        lack_of_empathy = 0.0 if empathy_shown else 1.0

        # Composite Banality Index B
        banality_index = round(min(1.0, (
            0.35 * thoughtlessness +
            0.30 * cliche_reliance +
            0.25 * moral_outsourcing +
            0.10 * lack_of_empathy
        )), 4)

        if banality_index >= 0.70:
            state = "BANALITY_OF_EVIL"
        elif banality_index >= 0.40:
            state = "BUREAUCRATIC_CONFORMISM"
        else:
            state = "AUTONOMOUS_CRITICAL_CONSCIENCE"

        agent["banality_index"] = banality_index
        agent["state"] = state

        self.log(f"EVAL_AGENT id={agent_id} B={banality_index} state={state} thoughtlessness={thoughtlessness}")
        res = {
            "agent_id": agent_id,
            "action_type": act_type,
            "thoughtlessness": thoughtlessness,
            "cliche_reliance": cliche_reliance,
            "moral_outsourcing": moral_outsourcing,
            "lack_of_empathy": lack_of_empathy,
            "banality_index": banality_index,
            "state": state
        }
        self.history.append(res)
        return res

def run_simulation(input_data: dict) -> dict:
    config = input_data.get("config", {})
    operations = input_data.get("operations", [])

    engine = BanalityOfEvilEngine(config)

    for op_info in operations:
        op = op_info.get("op")
        if op == "REGISTER_AGENT":
            aid = op_info.get("agent_id")
            name = op_info.get("name", "")
            role = op_info.get("role", "")
            engine.register_agent(aid, name, role)
        elif op == "PROCESS_ACTION":
            aid = op_info.get("agent_id")
            act = op_info.get("action", {})
            engine.process_action(aid, act)

    agents_dump = {}
    banality_count = 0
    conformism_count = 0
    autonomous_count = 0
    max_b = 0.0

    for aid, a in sorted(engine.agents.items()):
        b = a["banality_index"]
        if b > max_b:
            max_b = b
        if a["state"] == "BANALITY_OF_EVIL":
            banality_count += 1
        elif a["state"] == "BUREAUCRATIC_CONFORMISM":
            conformism_count += 1
        elif a["state"] == "AUTONOMOUS_CRITICAL_CONSCIENCE":
            autonomous_count += 1

        agents_dump[aid] = {
            "name": a["name"],
            "role": a["role"],
            "orders_received": a["orders_received"],
            "orders_blindly_executed": a["orders_blindly_executed"],
            "euphemisms_used": a["euphemisms_used"],
            "critical_inquiries": a["critical_inquiries"],
            "banality_index": a["banality_index"],
            "state": a["state"]
        }

    engine.stats.update({
        "evaluations": len(engine.history),
        "banality_of_evil_count": banality_count,
        "bureaucratic_conformism_count": conformism_count,
        "autonomous_conscience_count": autonomous_count,
        "max_banality_index": max_b
    })

    return {
        "stats": engine.stats,
        "agents": agents_dump,
        "history": engine.history,
        "event_log": engine.event_log
    }

if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            sys.stdin.reconfigure(encoding="utf-8")
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    input_text = sys.stdin.read().strip()
    if not input_text:
        sys.exit(0)

    data = json.loads(input_text)
    result = run_simulation(data)
    print(json.dumps(result, ensure_ascii=False))
