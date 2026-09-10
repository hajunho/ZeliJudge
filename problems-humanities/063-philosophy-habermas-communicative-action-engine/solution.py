# -*- coding: utf-8 -*-
"""
ZeliJudge Humanities Track Problem #063
Jürgen Habermas: Theory of Communicative Action & Ideal Speech Situation Engine
(위르겐 하버마스의 의사소통행위이론: 4대 타당성 요구, 생활세계의 식민지화 및 이상적 담화 상황 합의 엔진)

Operationalizes Jürgen Habermas's 'Theorie des kommunikativen Handelns' (1981):
1. 4 Universal Validity Claims: Comprehensibility, Truth (Wahrheit), Rightness (Richtigkeit), Sincerity (Wahrhaftigkeit).
2. Action Type Distinction: Communicative Action (oriented to mutual understanding) vs Strategic Action (success-oriented, distorting sincerity).
3. Steering Media Colonization Index (Money & Power invading the Lifeworld).
4. Ideal Speech Situation (Ideale Sprechsituation) conditions: Rational Consensus vs Contested Deliberation vs Systemic Distortion.
"""

import sys
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return

    data = json.loads(raw_input)

    config = data.get("config", {})
    consensus_thresh = float(config.get("consensus_threshold", 0.80))
    w_money = float(config.get("colonization_weight_money", 0.40))
    w_power = float(config.get("colonization_weight_power", 0.60))

    participants = {p["participant_id"]: p for p in data.get("discourse_participants", [])}
    utterances = data.get("utterances", [])

    utterance_logs = []
    consensus_cnt = 0
    distortion_cnt = 0
    lifeworld_health_list = []
    validity_scores = []

    for idx, utt in enumerate(utterances, start=1):
        u_id = utt.get("utterance_id", f"UTT-{idx:03d}")
        spk_id = utt.get("speaker_id")
        action_type = utt.get("action_type", "COMMUNICATIVE").upper()
        claims = utt.get("validity_claims", {})
        c = float(claims.get("comprehensibility", 1.0))
        t = float(claims.get("truth", 1.0))
        r = float(claims.get("rightness", 1.0))
        s = float(claims.get("sincerity", 1.0))

        if action_type == "STRATEGIC":
            s_eff = max(0.0, round(s - 0.40, 4))
        else:
            s_eff = s

        v_eff = round((c + t + r + s_eff) / 4.0, 4)
        validity_scores.append(v_eff)

        media = utt.get("steering_media_pressures", {})
        m_val = float(media.get("money", 0.0))
        p_val = float(media.get("power", 0.0))
        colonization = round(w_money * m_val + w_power * p_val, 4)
        lifeworld_health = max(0.0, round(1.0 - colonization, 4))
        lifeworld_health_list.append(lifeworld_health)

        if colonization > 0.50:
            colonization_state = "COLONIZED_BY_SYSTEM"
        elif colonization > 0.25:
            colonization_state = "MEDIA_INFILTRATED"
        else:
            colonization_state = "AUTONOMOUS_LIFEWORLD"

        if v_eff >= consensus_thresh and colonization <= 0.30:
            verdict = "RATIONAL_CONSENSUS_REACHED"
            consensus_cnt += 1
        elif v_eff < 0.50 or colonization > 0.50:
            verdict = "SYSTEMIC_DISTORTION"
            distortion_cnt += 1
        else:
            verdict = "CONTESTED_DELIBERATION"

        utterance_logs.append({
            "utterance_id": u_id,
            "speaker_id": spk_id,
            "action_type": action_type,
            "effective_validity": v_eff,
            "colonization_index": colonization,
            "lifeworld_status": colonization_state,
            "discourse_verdict": verdict
        })

    avg_health = round(sum(lifeworld_health_list) / len(lifeworld_health_list), 4) if lifeworld_health_list else 0.0
    avg_validity = round(sum(validity_scores) / len(validity_scores), 4) if validity_scores else 0.0

    output = {
        "summary": {
            "total_utterances": len(utterances),
            "rational_consensus_count": consensus_cnt,
            "systemic_distortion_count": distortion_cnt,
            "mean_discourse_validity": avg_validity,
            "mean_lifeworld_autonomy": avg_health
        },
        "utterance_evaluations": utterance_logs
    }

    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    solve()
