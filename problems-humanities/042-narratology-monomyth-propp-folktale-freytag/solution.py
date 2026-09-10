# -*- coding: utf-8 -*-
import sys
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

CAMPBELL_STAGES = [
    "ORDINARY_WORLD",
    "CALL_TO_ADVENTURE",
    "REFUSAL_OF_THE_CALL",
    "MEETING_WITH_THE_MENTOR",
    "CROSSING_THE_FIRST_THRESHOLD",
    "TESTS_ALLIES_ENEMIES",
    "APPROACH_TO_INMOST_CAVE",
    "ORDEAL",
    "REWARD",
    "THE_ROAD_BACK",
    "RESURRECTION",
    "RETURN_WITH_THE_ELIXIR"
]

STAGE_TO_INDEX = {s: i + 1 for i, s in enumerate(CAMPBELL_STAGES)}

def evaluate_single_story(story):
    story_id = story.get("story_id", "STORY_001")
    title = story.get("title", "Untitled Story")
    characters = story.get("characters", [])
    events = story.get("sequence_of_events", [])

    char_map = {c["name"]: c.get("archetype", "UNKNOWN") for c in characters}
    archetype_map = {}
    for name, arc in char_map.items():
        archetype_map.setdefault(arc, []).append(name)

    issues = []
    
    if "HERO" not in archetype_map:
        issues.append("MISSING_HERO_ARCHETYPE")
    if "VILLAIN" not in archetype_map:
        issues.append("MISSING_VILLAIN_ARCHETYPE")

    has_false_hero = "FALSE_HERO" in archetype_map
    false_hero_exposed = False

    stage_indices = []
    tensions = []
    co_occurrences = {}

    prev_idx = 0
    illegal_regression = False

    for ev in events:
        c_stage = ev.get("campbell_stage", "ORDINARY_WORLD")
        idx = STAGE_TO_INDEX.get(c_stage, 1)
        stage_indices.append(idx)
        
        func = ev.get("propp_function", "NONE")
        t = float(ev.get("tension_rating", 50.0))
        tensions.append(t)
        
        ev_chars = sorted(ev.get("characters_involved", []))

        for i in range(len(ev_chars)):
            for j in range(i + 1, len(ev_chars)):
                pair = (ev_chars[i], ev_chars[j])
                co_occurrences[pair] = co_occurrences.get(pair, 0) + 1

        if func == "DISPATCH":
            if not any(char_map.get(ch) == "DISPATCHER" for ch in ev_chars):
                issues.append("DISPATCH_WITHOUT_DISPATCHER")
        elif func == "DONOR_TEST":
            if not any(char_map.get(ch) == "DONOR" for ch in ev_chars):
                issues.append("DONOR_TEST_WITHOUT_DONOR")
        elif func in ["STRUGGLE", "ORDEAL"]:
            if not any(char_map.get(ch) == "VILLAIN" for ch in ev_chars):
                issues.append("CLIMACTIC_STRUGGLE_WITHOUT_VILLAIN")
        elif func in ["EXPOSURE", "PUNISHMENT"]:
            if any(char_map.get(ch) == "FALSE_HERO" for ch in ev_chars):
                false_hero_exposed = True

        if prev_idx > 0 and idx < prev_idx - 2:
            illegal_regression = True
        prev_idx = idx

    if has_false_hero and not false_hero_exposed:
        issues.append("UNEXPOSED_FALSE_HERO")

    if illegal_regression:
        issues.append("ILLEGAL_STAGE_REGRESSION")

    unique_stages = set(stage_indices)
    has_act1 = any(1 <= s <= 5 for s in unique_stages)
    has_act2 = any(6 <= s <= 9 for s in unique_stages)
    has_act3 = any(10 <= s <= 12 for s in unique_stages)

    act_coverage_count = sum([has_act1, has_act2, has_act3])
    stage_coverage_ratio = round(len(unique_stages) / 12.0, 4)

    if tensions:
        peak_tension = max(tensions)
        peak_idx = tensions.index(peak_tension)
        peak_stage = events[peak_idx].get("campbell_stage", "UNKNOWN")
        initial_tension = tensions[0]
        final_tension = tensions[-1]

        rising_slope = round((peak_tension - initial_tension) / peak_idx, 2) if peak_idx > 0 else 0.0
        rem_steps = len(tensions) - 1 - peak_idx
        falling_slope = round((final_tension - peak_tension) / rem_steps, 2) if rem_steps > 0 else 0.0
        climax_in_proper_phase = stage_indices[peak_idx] in [7, 8, 9, 11]
    else:
        peak_tension = 0.0
        peak_idx = 0
        peak_stage = "NONE"
        rising_slope = 0.0
        falling_slope = 0.0
        initial_tension = 0.0
        final_tension = 0.0
        climax_in_proper_phase = False

    if len(issues) == 0 and act_coverage_count == 3 and stage_coverage_ratio >= 0.75 and climax_in_proper_phase:
        rating = "MASTERPIECE_MONOMYTH"
    elif len(issues) == 0 and act_coverage_count >= 2:
        rating = "COHERENT_STANDARD"
    elif illegal_regression:
        rating = "BROKEN_NARRATIVE"
    else:
        rating = "IRREGULAR_AVANT_GARDE"

    co_occ_list = [
        {"char1": p[0], "char2": p[1], "co_occurrences": count}
        for p, count in sorted(co_occurrences.items(), key=lambda x: (-x[1], x[0][0], x[0][1]))
    ]

    return {
        "story_id": story_id,
        "title": title,
        "narrative_rating": rating,
        "is_valid_monomyth": len(issues) == 0 and act_coverage_count == 3,
        "monomyth_metrics": {
            "unique_stages_count": len(unique_stages),
            "stage_coverage_ratio": stage_coverage_ratio,
            "acts_covered": {
                "act_1_departure": has_act1,
                "act_2_initiation": has_act2,
                "act_3_return": has_act3
            }
        },
        "freytag_pyramid": {
            "peak_tension": peak_tension,
            "peak_event_step": events[peak_idx].get("step", peak_idx + 1) if events else 0,
            "peak_stage": peak_stage,
            "rising_action_slope": rising_slope,
            "falling_action_slope": falling_slope,
            "initial_tension": initial_tension,
            "final_tension": final_tension,
            "climax_in_proper_phase": climax_in_proper_phase
        },
        "character_network": {
            "archetypes_present": sorted(list(set(char_map.values()))),
            "total_characters": len(characters),
            "character_co_occurrences": co_occ_list
        },
        "structural_issues": issues
    }

def evaluate_corpus(stories):
    total = len(stories)
    evals = [evaluate_single_story(s) for s in stories]
    
    masterpiece = sum(1 for e in evals if e["narrative_rating"] == "MASTERPIECE_MONOMYTH")
    coherent = sum(1 for e in evals if e["narrative_rating"] == "COHERENT_STANDARD")
    avant_garde = sum(1 for e in evals if e["narrative_rating"] == "IRREGULAR_AVANT_GARDE")
    broken = sum(1 for e in evals if e["narrative_rating"] == "BROKEN_NARRATIVE")
    valid_monomyth = sum(1 for e in evals if e["is_valid_monomyth"])
    
    avg_stage_cov = round(sum(e["monomyth_metrics"]["stage_coverage_ratio"] for e in evals) / total, 4) if total > 0 else 0.0
    avg_peak_tension = round(sum(e["freytag_pyramid"]["peak_tension"] for e in evals) / total, 2) if total > 0 else 0.0
    adherence_rate = round(valid_monomyth / total, 4) if total > 0 else 0.0

    return {
        "total_stories": total,
        "masterpiece_count": masterpiece,
        "coherent_count": coherent,
        "avant_garde_count": avant_garde,
        "broken_count": broken,
        "monomyth_adherence_rate": adherence_rate,
        "average_stage_coverage": avg_stage_cov,
        "average_peak_tension": avg_peak_tension,
        "story_evaluations": evals
    }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    mode = data.get("mode", "ANALYZE_STORY")
    
    if mode == "ANALYZE_STORY":
        story = data.get("story", {})
        res = evaluate_single_story(story)
        print(json.dumps(res, ensure_ascii=False))
    elif mode == "BATCH_CORPUS_ANALYTICS":
        stories = data.get("stories", [])
        res = evaluate_corpus(stories)
        print(json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    main()
