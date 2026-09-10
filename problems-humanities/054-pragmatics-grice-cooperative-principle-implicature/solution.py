import sys
import json
from typing import Dict, List, Any, Optional

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

def evaluate_gricean_turn(context: Dict[str, Any], turn: Dict[str, Any]) -> Dict[str, Any]:
    spk = turn.get("speaker")
    stmt_claim = turn.get("statement_claim")
    inf_score = turn.get("informative_score", 1.0)
    rel_score = turn.get("relevance_score", 1.0)
    cla_score = turn.get("clarity_score", 1.0)
    is_blatant = turn.get("is_blatant", False)
    coop_presumption = turn.get("cooperative_presumption", True)
    
    # 1. Quality Maxim
    quality_status = "OBSERVED"
    quality_reason = "Speaker believes the statement to be true and has adequate evidence."
    if stmt_claim is not None:
        spk_belief = context.get("speaker_beliefs", {}).get(spk, {}).get(stmt_claim)
        if spk_belief is False:
            if is_blatant and coop_presumption:
                quality_status = "FLOUTED"
                quality_reason = "Speaker blatantly states an obvious falsehood (Irony/Metaphor/Hyperbole)."
            else:
                quality_status = "VIOLATED"
                quality_reason = "Speaker covertly utters a falsehood without communicative transparency (Deception)."

    # 2. Quantity Maxim
    quantity_status = "OBSERVED"
    quantity_reason = "Speaker provides the appropriate amount of information required."
    if inf_score < 0.4:
        if is_blatant and coop_presumption:
            quantity_status = "FLOUTED"
            quantity_reason = "Speaker blatantly provides less information than required (Tautology / Faint praise)."
        else:
            quantity_status = "VIOLATED"
            quantity_reason = "Speaker uncooperatively withholds required information."
    elif inf_score > 1.6:
        if is_blatant and coop_presumption:
            quantity_status = "FLOUTED"
            quantity_reason = "Speaker blatantly provides excessive detail to convey communicative subtext."
        else:
            quantity_status = "VIOLATED"
            quantity_reason = "Speaker provides superfluous information."

    # 3. Relation Maxim
    relation_status = "OBSERVED"
    relation_reason = "Speaker contribution is directly relevant to current conversational purpose."
    if rel_score < 0.4:
        if is_blatant and coop_presumption:
            relation_status = "FLOUTED"
            relation_reason = "Speaker blatantly changes the subject to signal social deflection or discomfort."
        else:
            relation_status = "VIOLATED"
            relation_reason = "Speaker produces an unmotivated, irrelevant tangent."

    # 4. Manner Maxim
    manner_status = "OBSERVED"
    manner_reason = "Speaker is clear, brief, orderly, and avoids obscurity."
    if cla_score < 0.4:
        if is_blatant and coop_presumption:
            manner_status = "FLOUTED"
            manner_reason = "Speaker deliberately uses obscure, convoluted, or euphemistic phrasing."
        else:
            manner_status = "VIOLATED"
            manner_reason = "Speaker is unintentionally obscure or confusing."

    maxims = {
        "Quantity": {"status": quantity_status, "reason": quality_reason if False else quantity_reason},
        "Quality": {"status": quality_status, "reason": quality_reason},
        "Relation": {"status": relation_status, "reason": relation_reason},
        "Manner": {"status": manner_status, "reason": manner_reason}
    }

    flouted_maxims = [k for k, v in maxims.items() if v["status"] == "FLOUTED"]
    violated_maxims = [k for k, v in maxims.items() if v["status"] == "VIOLATED"]
    
    rhetorical_figure = "HONEST_CONVERSATION"
    implicature_generated = False
    implicature = None
    
    if flouted_maxims and coop_presumption:
        implicature_generated = True
        implicature = turn.get("intended_implicature")
        if "Quality" in flouted_maxims:
            rhetorical_figure = turn.get("figure_type", "IRONY")
        elif "Quantity" in flouted_maxims:
            rhetorical_figure = turn.get("figure_type", "TAUTOLOGY_OR_UNDERSTATEMENT")
        elif "Relation" in flouted_maxims:
            rhetorical_figure = "TOPIC_DEFLECTION"
        elif "Manner" in flouted_maxims:
            rhetorical_figure = "DELIBERATE_OBSCURITY"
    elif violated_maxims:
        rhetorical_figure = "DECEPTION_OR_NON_COOPERATION"
        implicature_generated = False
        implicature = None

    return {
        "maxims": maxims,
        "cooperative_principle_preserved": coop_presumption,
        "implicature_generated": implicature_generated,
        "conversational_implicature": implicature,
        "rhetorical_figure": rhetorical_figure
    }

def process_dialogue(data: Dict[str, Any]) -> Dict[str, Any]:
    context = data.get("context", {})
    turns = data.get("turns", [])
    
    turn_evaluations = []
    for turn in turns:
        res = evaluate_gricean_turn(context, turn)
        turn_evaluations.append({
            "turn_id": turn.get("id", ""),
            "evaluation": res
        })
        
    return {
        "turn_evaluations": turn_evaluations
    }

def main():
    raw_data = sys.stdin.read().strip()
    if not raw_data:
        return
    data = json.loads(raw_data)
    result = process_dialogue(data)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
