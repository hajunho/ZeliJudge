# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #056: 샤를 샌더스 퍼스의 3분법 기호학 및 무한 기호작용(Infinite Semiosis) 추론 엔진
Charles Sanders Peirce's Triadic Semiotics (Representamen, Object, Interpretant),
Icon / Index / Symbol Classification & Infinite Semiosis Chain Simulator
"""
import sys
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def run_semiotics_engine(data):
    config = data.get("config", {})
    max_depth = config.get("max_semiosis_depth", 10)
    grounding_thresh = config.get("grounding_threshold", 0.75)

    sign_dict = {s["sign_id"]: s for s in data.get("sign_dictionary", [])}
    tasks = data.get("inquiry_tasks", [])

    results = []

    for task in tasks:
        t_id = task["task_id"]
        init_id = task["initial_sign_id"]
        ctx = task.get("observed_context", {})
        phys_presence = set(ctx.get("physical_presence", []))
        active_convs = set(ctx.get("active_conventions", []))

        current_id = init_id
        visited = []
        steps = []
        term_reason = "UNKNOWN"
        final_belief = None

        while True:
            if current_id not in sign_dict:
                term_reason = "UNKNOWN_SIGN"
                break

            sign = sign_dict[current_id]
            visited.append(current_id)
            step_num = len(visited)

            rel_type = sign.get("relation_type", "SYMBOL")
            grounding = sign.get("grounding", {})
            grounded = True

            if rel_type == "ICON":
                sim = grounding.get("similarity_score", 0.0)
                if sim < grounding_thresh:
                    grounded = False
            elif rel_type == "INDEX":
                causal = grounding.get("causal_factor", "")
                prox = grounding.get("physical_proximity", False)
                if prox and (causal not in phys_presence) and (sign.get("target_object") not in phys_presence):
                    grounded = False
            elif rel_type == "SYMBOL":
                soc_ctx = grounding.get("social_context", "")
                if soc_ctx and (soc_ctx not in active_convs):
                    grounded = False

            inter_rule = sign.get("interpretant_rule", {})
            next_id = inter_rule.get("next_sign_id")
            is_habit = inter_rule.get("habit_forming", False)

            if is_habit:
                i_type = "FINAL"
            elif step_num == 1:
                i_type = "IMMEDIATE"
            else:
                i_type = "DYNAMICAL"

            steps.append({
                "step": step_num,
                "sign_id": current_id,
                "name": sign.get("name", ""),
                "triad": {
                    "representamen": sign.get("name", ""),
                    "object": sign.get("target_object", ""),
                    "interpretant_type": i_type
                },
                "classification": rel_type,
                "grounded": grounded
            })

            if not grounded:
                term_reason = "UNGROUNDED_SIGN"
                break

            if is_habit:
                term_reason = "FINAL_HABIT_CONVERGENCE"
                final_belief = sign.get("target_object")
                break

            if not next_id:
                term_reason = "TERMINAL_INTERPRETANT"
                final_belief = sign.get("target_object")
                break

            if next_id in visited:
                term_reason = "SEMIOTIC_CYCLE_DETECTED"
                break

            if step_num >= max_depth:
                term_reason = "MAX_DEPTH_EXCEEDED"
                break

            current_id = next_id

        results.append({
            "task_id": t_id,
            "initial_sign": init_id,
            "chain_length": len(steps),
            "termination_reason": term_reason,
            "final_belief": final_belief,
            "semiosis_path": [s["sign_id"] for s in steps],
            "steps": steps
        })

    return {
        "summary": {
            "total_tasks": len(tasks),
            "converged_habits": sum(1 for r in results if r["termination_reason"] == "FINAL_HABIT_CONVERGENCE"),
            "cycles_detected": sum(1 for r in results if r["termination_reason"] == "SEMIOTIC_CYCLE_DETECTED"),
            "ungrounded_failures": sum(1 for r in results if r["termination_reason"] == "UNGROUNDED_SIGN")
        },
        "results": results
    }


def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    result = run_semiotics_engine(data)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
