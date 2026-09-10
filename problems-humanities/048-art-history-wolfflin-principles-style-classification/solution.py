# -*- coding: utf-8 -*-
import sys
import json
import math

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

def clamp(val, min_v, max_v):
    return max(min_v, min(max_v, val))

class WolfflinEngine:
    CATEGORIES = [
        "linear_vs_painterly",
        "plane_vs_recession",
        "closed_vs_open_form",
        "multiplicity_vs_unity",
        "absolute_vs_relative_clarity"
    ]

    def _eval_artwork(self, artwork):
        m = artwork.get("metrics", {})

        c_def = m.get("contour_definition", 0.5)
        b_blend = m.get("brushstroke_blending", 0.5)
        s1 = round(clamp(b_blend - c_def, -1.0, 1.0), 3)

        p_plane = m.get("parallel_planes", 0.5)
        d_recess = m.get("diagonal_recession", 0.5)
        s2 = round(clamp(d_recess - p_plane, -1.0, 1.0), 3)

        f_contain = m.get("frame_containment", 0.5)
        o_canvas = m.get("off_canvas_focus", 0.5)
        s3 = round(clamp(o_canvas - f_contain, -1.0, 1.0), 3)

        p_auto = m.get("part_autonomy", 0.5)
        s_focus = m.get("subordination_to_focus", 0.5)
        s4 = round(clamp(s_focus - p_auto, -1.0, 1.0), 3)

        u_illum = m.get("uniform_illumination", 0.5)
        c_obsc = m.get("chiaroscuro_obscuration", 0.5)
        s5 = round(clamp(c_obsc - u_illum, -1.0, 1.0), 3)

        scores = {
            "linear_vs_painterly": s1,
            "plane_vs_recession": s2,
            "closed_vs_open_form": s3,
            "multiplicity_vs_unity": s4,
            "absolute_vs_relative_clarity": s5
        }

        composite_idx = round(sum(scores.values()) / 5.0, 3)

        if composite_idx <= -0.40:
            classification = "HIGH_RENAISSANCE"
            style_label = "전성기 르네상스 (High Renaissance)"
        elif composite_idx <= -0.10:
            classification = "MANNERISM"
            style_label = "매너리즘 / 과도기 르네상스 (Mannerism)"
        elif composite_idx <= 0.10:
            classification = "BALANCED_HYBRID"
            style_label = "절충적 고전주의 (Balanced Hybrid Classicism)"
        elif composite_idx <= 0.40:
            classification = "EARLY_BAROQUE"
            style_label = "초기/온건 바로크 (Early/Moderate Baroque)"
        else:
            classification = "HIGH_BAROQUE"
            style_label = "전성기 바로크 (High/Dynamic Baroque)"

        polarities = {}
        for cat, sc in scores.items():
            if sc < -0.15:
                pol = "RENAISSANCE_DOMINANT"
            elif sc > 0.15:
                pol = "BAROQUE_DOMINANT"
            else:
                pol = "NEUTRAL"
            polarities[cat] = pol

        return {
            "title": artwork.get("title", "Untitled"),
            "artist": artwork.get("artist", "Unknown"),
            "year": artwork.get("year"),
            "category_scores": scores,
            "composite_wolfflin_index": composite_idx,
            "classification": classification,
            "style_label": style_label,
            "polarities": polarities
        }

    def process(self, payload):
        mode = payload.get("mode", "single")

        if mode == "single":
            artwork = payload.get("artwork", {})
            res = self._eval_artwork(artwork)
            return {
                "mode": "single",
                "result": res
            }

        elif mode == "compare":
            art_a = payload.get("artwork_a", {})
            art_b = payload.get("artwork_b", {})
            res_a = self._eval_artwork(art_a)
            res_b = self._eval_artwork(art_b)

            delta = {}
            dist_sq = 0.0
            max_cat = None
            max_abs_diff = -1.0

            for cat in self.CATEGORIES:
                diff = round(res_b["category_scores"][cat] - res_a["category_scores"][cat], 3)
                delta[cat] = diff
                dist_sq += diff * diff
                if abs(diff) > max_abs_diff:
                    max_abs_diff = abs(diff)
                    max_cat = cat

            euclidean_distance = round(math.sqrt(dist_sq), 3)
            composite_shift = round(res_b["composite_wolfflin_index"] - res_a["composite_wolfflin_index"], 3)

            if composite_shift > 0.30:
                shift_type = "RENAISSANCE_TO_BAROQUE_TRANSITION"
            elif composite_shift < -0.30:
                shift_type = "CLASSICAL_LINEAR_REVIVAL"
            else:
                shift_type = "INTRA_ERA_VARIATION"

            return {
                "mode": "compare",
                "artwork_a": res_a,
                "artwork_b": res_b,
                "comparison": {
                    "delta_scores": delta,
                    "composite_shift": composite_shift,
                    "euclidean_distance": euclidean_distance,
                    "max_divergence_category": max_cat,
                    "shift_type": shift_type
                }
            }

        elif mode == "batch":
            artworks = payload.get("artworks", [])
            evaluated = [self._eval_artwork(a) for a in artworks]

            class_dist = {
                "HIGH_RENAISSANCE": 0,
                "MANNERISM": 0,
                "BALANCED_HYBRID": 0,
                "EARLY_BAROQUE": 0,
                "HIGH_BAROQUE": 0
            }
            avg_scores = {cat: 0.0 for cat in self.CATEGORIES}
            total_composite = 0.0

            for item in evaluated:
                class_dist[item["classification"]] += 1
                total_composite += item["composite_wolfflin_index"]
                for cat in self.CATEGORIES:
                    avg_scores[cat] += item["category_scores"][cat]

            n = len(evaluated) if evaluated else 1
            avg_composite = round(total_composite / n, 3)
            for cat in self.CATEGORIES:
                avg_scores[cat] = round(avg_scores[cat] / n, 3)

            return {
                "mode": "batch",
                "total_artworks": len(evaluated),
                "artworks": evaluated,
                "summary": {
                    "average_composite_index": avg_composite,
                    "average_category_scores": avg_scores,
                    "classification_distribution": class_dist
                }
            }

        else:
            return {"error": f"Unknown mode: {mode}"}

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    engine = WolfflinEngine()
    result = engine.process(data)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
