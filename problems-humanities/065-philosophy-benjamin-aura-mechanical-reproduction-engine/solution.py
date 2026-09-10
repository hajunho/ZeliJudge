import sys
import os
import json

def analyze_benjamin_ecosystem(input_data: dict) -> dict:
    config = input_data.get("config", {})
    artworks = input_data.get("artworks", [])
    n = len(artworks)

    if n == 0:
        return {
            "artwork_evaluations": [],
            "summary": {
                "total_artworks": 0,
                "aura_distribution": {"preserved": 0, "fading": 0, "decayed": 0},
                "value_distribution": {"cult_dominant": 0, "exhibition_dominant": 0, "equilibrium": 0},
                "optical_unconscious_unlocked_count": 0,
                "political_mode_counts": {"politicization_of_art": 0, "aestheticization_of_politics": 0, "autonomous_aesthetics": 0},
                "epoch_diagnosis": "TRANSITIONAL_MEDIA_ECOLOGY"
            }
        }

    evaluations = []
    aura_dist = {"preserved": 0, "fading": 0, "decayed": 0}
    val_dist = {"cult_dominant": 0, "exhibition_dominant": 0, "equilibrium": 0}
    opt_count = 0
    pol_counts = {"politicization_of_art": 0, "aestheticization_of_politics": 0, "autonomous_aesthetics": 0}

    for art in artworks:
        aid = art.get("id")
        name = art.get("name")
        hic = bool(art.get("hic_et_nunc", True))
        n_repro = int(art.get("reproduction_count", 0))
        d = float(art.get("distance_factor", 1.0))
        a = float(art.get("accessibility", 0.0))
        c = float(art.get("close_up_factor", 0.0))
        s = float(art.get("slow_motion_factor", 0.0))
        r = float(art.get("ritual_context", 1.0))
        p = float(art.get("spectacle_propaganda", 0.0))

        # 1. Aura
        if not hic:
            aura = 0.0
        else:
            aura = round(d * r / (1.0 + 0.001 * n_repro), 4)

        if aura >= 0.70:
            aura_status = "AURA_PRESERVED"
            aura_dist["preserved"] += 1
        elif aura >= 0.30:
            aura_status = "AURA_FADING"
            aura_dist["fading"] += 1
        else:
            aura_status = "AURA_DECAYED"
            aura_dist["decayed"] += 1

        # 2. Cult vs Exhibition Value
        v_cult = round(r * (1.0 / (1.0 + 0.0005 * n_repro)) * (1.0 - 0.5 * a), 4)
        repro_factor = min(1.0, n_repro / 1000.0)
        v_exhibit = min(1.0, round(a * (0.3 + 0.7 * repro_factor), 4))

        if v_cult > v_exhibit:
            dom_val = "CULT_VALUE_DOMINANT"
            val_dist["cult_dominant"] += 1
        elif v_cult < v_exhibit:
            dom_val = "EXHIBITION_VALUE_DOMINANT"
            val_dist["exhibition_dominant"] += 1
        else:
            dom_val = "TRANSITIONAL_EQUILIBRIUM"
            val_dist["equilibrium"] += 1

        # 3. Optical Unconscious
        opt_unc = round(0.5 * c + 0.5 * s, 4)
        if opt_unc >= 0.60:
            opt_status = "OPTICAL_UNCONSCIOUS_UNLOCKED"
            opt_count += 1
        else:
            opt_status = "CONVENTIONAL_VISION"

        # 4. Political Mode
        if p >= 0.70:
            pol_mode = "AESTHETICIZATION_OF_POLITICS"
            pol_counts["aestheticization_of_politics"] += 1
        elif a >= 0.70 and opt_unc >= 0.50:
            pol_mode = "POLITICIZATION_OF_ART"
            pol_counts["politicization_of_art"] += 1
        else:
            pol_mode = "AUTONOMOUS_AESTHETICS"
            pol_counts["autonomous_aesthetics"] += 1

        evaluations.append({
            "id": aid,
            "name": name,
            "hic_et_nunc": hic,
            "aura_index": aura,
            "aura_status": aura_status,
            "cult_value": v_cult,
            "exhibition_value": v_exhibit,
            "dominant_value": dom_val,
            "optical_unconscious": opt_unc,
            "optical_status": opt_status,
            "political_mode": pol_mode
        })

    decayed_ratio = aura_dist["decayed"] / n
    exhibit_ratio = val_dist["exhibition_dominant"] / n
    preserved_ratio = aura_dist["preserved"] / n

    if decayed_ratio >= 0.70 and exhibit_ratio >= 0.70:
        epoch_diag = "AGE_OF_MECHANICAL_REPRODUCTION"
    elif preserved_ratio >= 0.70:
        epoch_diag = "CLASSICAL_RITUAL_EPOCH"
    else:
        epoch_diag = "TRANSITIONAL_MEDIA_ECOLOGY"

    return {
        "artwork_evaluations": evaluations,
        "summary": {
            "total_artworks": n,
            "aura_distribution": aura_dist,
            "value_distribution": val_dist,
            "optical_unconscious_unlocked_count": opt_count,
            "political_mode_counts": pol_counts,
            "epoch_diagnosis": epoch_diag
        }
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
    result = analyze_benjamin_ecosystem(data)
    print(json.dumps(result, ensure_ascii=False))
