import sys
import json
import math

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

INTCAL_ANCHORS = [
    (-1000, 2850, 20),
    (-800,  2620, 20),
    (-500,  2420, 25),
    (-300,  2240, 20),
    (-100,  2090, 20),
    (0,     1980, 20),
    (200,   1820, 20),
    (400,   1670, 20),
    (600,   1460, 20),
    (800,   1220, 20),
    (1000,  1040, 20),
    (1200,  830,  20),
    (1400,  550,  20),
    (1600,  320,  20)
]

def interpolate_calibration_curve(cal_ad: float):
    if cal_ad <= INTCAL_ANCHORS[0][0]:
        return INTCAL_ANCHORS[0][1], INTCAL_ANCHORS[0][2]
    if cal_ad >= INTCAL_ANCHORS[-1][0]:
        return INTCAL_ANCHORS[-1][1], INTCAL_ANCHORS[-1][2]
    for i in range(len(INTCAL_ANCHORS) - 1):
        x0, y0, s0 = INTCAL_ANCHORS[i]
        x1, y1, s1 = INTCAL_ANCHORS[i+1]
        if x0 <= cal_ad <= x1:
            ratio = (cal_ad - x0) / (x1 - x0)
            bp_interp = y0 + ratio * (y1 - y0)
            sigma_interp = s0 + ratio * (s1 - s0)
            return bp_interp, sigma_interp
    return INTCAL_ANCHORS[-1][1], INTCAL_ANCHORS[-1][2]

def calibrate_c14_sample(bp_age: float, bp_error: float, grid_step: int = 5):
    densities = {}
    total_density = 0.0
    for cal_yr in range(-1000, 1601, grid_step):
        curve_bp, curve_sig = interpolate_calibration_curve(cal_yr)
        total_sig = math.sqrt(bp_error**2 + curve_sig**2)
        diff = bp_age - curve_bp
        prob = math.exp(-0.5 * (diff / total_sig)**2) / total_sig
        densities[cal_yr] = prob
        total_density += prob

    if total_density > 0:
        for k in densities:
            densities[k] /= total_density

    mean_ad = sum(k * p for k, p in densities.items())
    variance = sum(((k - mean_ad)**2) * p for k, p in densities.items())
    std_ad = math.sqrt(variance)

    sorted_points = sorted(densities.items(), key=lambda x: x[1], reverse=True)
    accum = 0.0
    hpd_years = []
    for yr, p in sorted_points:
        accum += p
        hpd_years.append(yr)
        if accum >= 0.954:
            break
    min_2sig = min(hpd_years)
    max_2sig = max(hpd_years)

    return {
        "mean_cal_ad": round(mean_ad, 1),
        "std_ad": round(std_ad, 1),
        "range_95_ad": [min_2sig, max_2sig]
    }

def analyze_archaeological_site(input_data: dict) -> dict:
    contexts = input_data["contexts"]
    relationships = input_data["relationships"]
    c14_samples = input_data.get("c14_samples", [])

    ctx_ids = sorted([c["id"] for c in contexts])
    ctx_set = set(ctx_ids)

    adj = {c: set() for c in ctx_ids}
    raw_edges_count = len(relationships)

    for rel in relationships:
        u = rel["source"]
        v = rel["target"]
        typ = rel["type"]
        if u not in ctx_set or v not in ctx_set:
            continue
        if typ == "ABOVE":
            adj[v].add(u)
        elif typ == "BELOW":
            adj[u].add(v)
        elif typ == "CUTS":
            adj[v].add(u)
        elif typ == "FILLED_BY":
            adj[u].add(v)

    in_deg = {c: 0 for c in ctx_ids}
    for u in ctx_ids:
        for v in adj[u]:
            in_deg[v] += 1

    queue = sorted([c for c in ctx_ids if in_deg[c] == 0])
    topo_order = []
    while queue:
        queue.sort()
        u = queue.pop(0)
        topo_order.append(u)
        for v in sorted(adj[u]):
            in_deg[v] -= 1
            if in_deg[v] == 0:
                queue.append(v)

    if len(topo_order) != len(ctx_ids):
        return {
            "site_name": input_data.get("site_name", "UNKNOWN_SITE"),
            "is_valid_dag": False,
            "error": "STRATIGRAPHIC_CYCLE_DETECTED",
            "topological_sequence": [],
            "canonical_harris_matrix": [],
            "stratigraphic_phases": {},
            "c14_chronology": {},
            "stratigraphic_anomalies": [],
            "summary": {
                "total_contexts": len(ctx_ids),
                "total_relationships": raw_edges_count,
                "canonical_edges_count": 0,
                "redundant_edges_removed": 0,
                "max_phase": 0,
                "anomalies_count": 0,
                "archaeological_interpretation": "FATAL_STRATIGRAPHIC_CYCLE_REVERSE_EXCAVATION"
            }
        }

    reachable = {u: set() for u in ctx_ids}
    for u in reversed(topo_order):
        for v in adj[u]:
            reachable[u].add(v)
            reachable[u].update(reachable[v])

    canonical_edges = []
    for u in ctx_ids:
        for v in sorted(adj[u]):
            is_redundant = False
            for w in adj[u]:
                if w != v and v in reachable[w]:
                    is_redundant = True
                    break
            if not is_redundant:
                canonical_edges.append({"source": u, "target": v})

    phases = {c: 1 for c in ctx_ids}
    for u in topo_order:
        for v in adj[u]:
            if phases[u] + 1 > phases[v]:
                phases[v] = phases[u] + 1

    c14_results = {}
    sample_lookup = {}
    for s in c14_samples:
        cid = s["context_id"]
        bp = s["c14_age_bp"]
        err = s["c14_error_bp"]
        material = s.get("material", "ORGANIC")
        cal = calibrate_c14_sample(bp, err)
        cal["material"] = material
        cal["stratigraphic_phase"] = phases.get(cid, 1)
        sample_lookup[cid] = cal
        c14_results[cid] = {
            "mean_cal_ad": cal["mean_cal_ad"],
            "std_ad": cal["std_ad"],
            "range_95_ad": cal["range_95_ad"],
            "material": material,
            "stratigraphic_phase": phases.get(cid, 1)
        }

    anomalies = []
    for edge in canonical_edges:
        u = edge["source"]
        v = edge["target"]
        if u in sample_lookup and v in sample_lookup:
            cal_u = sample_lookup[u]
            cal_v = sample_lookup[v]
            if cal_u["mean_cal_ad"] > cal_v["mean_cal_ad"]:
                comb_sig = math.sqrt(cal_u["std_ad"]**2 + cal_v["std_ad"]**2)
                diff = cal_u["mean_cal_ad"] - cal_v["mean_cal_ad"]
                if diff > 2.0 * comb_sig:
                    anomalies.append({
                        "type": "STRATIGRAPHIC_AGE_INVERSION",
                        "older_context": u,
                        "younger_context": v,
                        "older_mean_ad": cal_u["mean_cal_ad"],
                        "younger_mean_ad": cal_v["mean_cal_ad"],
                        "inversion_years": round(diff, 1)
                    })

    max_phase = max(phases.values()) if phases else 0
    redundant_count = raw_edges_count - len(canonical_edges)
    if anomalies:
        interp = "ANOMALOUS_STRATA_OR_INTRUSION_DETECTED"
    else:
        interp = "CHRONOLOGY_CONSISTENT_WITH_STRATIGRAPHY"

    return {
        "site_name": input_data.get("site_name", "UNKNOWN_SITE"),
        "is_valid_dag": True,
        "error": None,
        "topological_sequence": topo_order,
        "canonical_harris_matrix": canonical_edges,
        "stratigraphic_phases": dict(sorted(phases.items())),
        "c14_chronology": dict(sorted(c14_results.items())),
        "stratigraphic_anomalies": anomalies,
        "summary": {
            "total_contexts": len(ctx_ids),
            "total_relationships": raw_edges_count,
            "canonical_edges_count": len(canonical_edges),
            "redundant_edges_removed": redundant_count,
            "max_phase": max_phase,
            "anomalies_count": len(anomalies),
            "archaeological_interpretation": interp
        }
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)
    result = analyze_archaeological_site(input_data)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
