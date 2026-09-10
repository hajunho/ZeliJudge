# -*- coding: utf-8 -*-
import sys
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

def levenshtein_distance(seq1, seq2):
    m, n = len(seq1), len(seq2)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if seq1[i - 1] == seq2[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])
    return dp[m][n]

class ProppianEngine:
    FUNCTION_ORDER = [
        "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta",
        "A", "a", "B", "C", "UP",
        "D", "E", "F",
        "G", "H", "J", "I", "K",
        "DOWN", "Pr", "Rs",
        "o", "L", "M", "N", "Q", "Ex", "T", "U", "W"
    ]

    def _parse_story(self, story):
        title = story.get("title", "Untitled")
        events = story.get("events", [])

        extracted_functions = []
        function_symbols = []
        syntax_errors = []

        for idx, ev in enumerate(events):
            func = ev.get("function")
            actor = ev.get("actor")
            target = ev.get("target")
            desc = ev.get("description", "")

            if func not in self.FUNCTION_ORDER:
                syntax_errors.append(f"UNKNOWN_FUNCTION_{func}_AT_EVENT_{idx}")
                continue

            extracted_functions.append({
                "step": idx + 1,
                "function": func,
                "actor": actor,
                "target": target,
                "description": desc
            })
            function_symbols.append(func)

        # Rule A: Complication must exist (either A or a)
        has_complication = ("A" in function_symbols or "a" in function_symbols)
        if not has_complication:
            syntax_errors.append("MISSING_COMPLICATION")

        # Rule B: F requires preceding D and E
        if "F" in function_symbols:
            idx_F = function_symbols.index("F")
            if "D" not in function_symbols[:idx_F] or "E" not in function_symbols[:idx_F]:
                syntax_errors.append("ILLEGAL_GIFT_WITHOUT_DONOR_CYCLE")

        # Rule C: I requires preceding H
        if "I" in function_symbols:
            idx_I = function_symbols.index("I")
            if "H" not in function_symbols[:idx_I]:
                syntax_errors.append("VICTORY_WITHOUT_STRUGGLE")

        # Rule D: K must follow A or a
        if "K" in function_symbols:
            idx_K = function_symbols.index("K")
            if not any(f in function_symbols[:idx_K] for f in ["A", "a"]):
                syntax_errors.append("LIQUIDATION_WITHOUT_COMPLICATION")

        # Rule E: Macro-phase chronological monotonicity
        landmarks = [("A/a", ["A", "a"]), ("D/E/F", ["D", "E", "F"]), ("H/I", ["H", "I"]), ("K", ["K"]), ("W", ["W"])]
        last_max_pos = -1
        for lm_name, group in landmarks:
            indices = [function_symbols.index(f) for f in group if f in function_symbols]
            if indices:
                min_pos = min(indices)
                if min_pos < last_max_pos:
                    syntax_errors.append(f"CHRONOLOGICAL_INVERSION_IN_{lm_name}")
                last_max_pos = max(indices)

        core_elements = ["complication", "departure", "donor_sequence", "struggle_victory", "liquidation", "resolution"]
        elements_present = {
            "complication": ("A" in function_symbols or "a" in function_symbols),
            "departure": ("UP" in function_symbols),
            "donor_sequence": ("D" in function_symbols and "E" in function_symbols and "F" in function_symbols),
            "struggle_victory": ("H" in function_symbols and "I" in function_symbols),
            "liquidation": ("K" in function_symbols),
            "resolution": any(f in function_symbols for f in ["W", "Q", "T", "U"])
        }
        score = int(sum(elements_present.values()) / len(core_elements) * 100)
        canonical_formula = " ".join(function_symbols)

        return {
            "title": title,
            "canonical_formula": canonical_formula,
            "function_symbols": function_symbols,
            "functions_count": len(extracted_functions),
            "elements_present": elements_present,
            "completeness_score": score,
            "is_grammatically_valid": (len(syntax_errors) == 0),
            "syntax_errors": syntax_errors
        }

    def process(self, payload):
        mode = payload.get("mode", "parse_story")

        if mode == "parse_story":
            story = payload.get("story", {})
            res = self._parse_story(story)
            res.pop("function_symbols", None)
            return {
                "mode": "parse_story",
                "result": res
            }

        elif mode == "compare_stories":
            story_a = payload.get("story_a", {})
            story_b = payload.get("story_b", {})
            res_a = self._parse_story(story_a)
            res_b = self._parse_story(story_b)

            set_a = set(res_a["function_symbols"])
            set_b = set(res_b["function_symbols"])
            intersection = set_a.intersection(set_b)
            union = set_a.union(set_b)

            jaccard = round(len(intersection) / len(union), 3) if union else 1.0
            edit_dist = levenshtein_distance(res_a["function_symbols"], res_b["function_symbols"])

            res_a.pop("function_symbols", None)
            res_b.pop("function_symbols", None)

            return {
                "mode": "compare_stories",
                "story_a": res_a,
                "story_b": res_b,
                "comparison": {
                    "shared_functions": sorted(list(intersection)),
                    "jaccard_similarity": jaccard,
                    "edit_distance": edit_dist,
                    "structural_affinity": "HIGH_AFFINITY" if jaccard >= 0.6 else "MODERATE_AFFINITY" if jaccard >= 0.3 else "LOW_AFFINITY"
                }
            }

        elif mode == "corpus_grammar_audit":
            stories = payload.get("stories", [])
            results = [self._parse_story(s) for s in stories]

            valid_count = sum(1 for r in results if r["is_grammatically_valid"])
            avg_completeness = round(sum(r["completeness_score"] for r in results) / len(results), 2) if results else 0

            clean_results = []
            for r in results:
                r.pop("function_symbols", None)
                clean_results.append(r)

            return {
                "mode": "corpus_grammar_audit",
                "total_stories": len(stories),
                "valid_stories_count": valid_count,
                "average_completeness_score": avg_completeness,
                "stories": clean_results
            }

        else:
            return {"error": f"Unknown mode: {mode}"}

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    engine = ProppianEngine()
    result = engine.process(data)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
