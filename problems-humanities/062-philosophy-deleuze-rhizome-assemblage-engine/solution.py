# -*- coding: utf-8 -*-
"""
ZeliJudge Humanities Track Problem #062
Gilles Deleuze & Felix Guattari: Rhizome, Assemblage & Deterritorialization Engine
(질 들뢰즈와 펠릭스 과타리의 천 개의 고원: 리좀, 아상블라주 및 탈영토화 엔진)

Operationalizes Gilles Deleuze & Felix Guattari's 'Mille Plateaux' (A Thousand Plateaus, 1980):
1. Arborescent (Tree / Hierarchical) vs Rhizomatic (Decentralized Multiplicity) topology.
2. 6 Principles of the Rhizome: Connection, Heterogeneity, Multiplicity, Asignifying Rupture, Cartography, Decalcomania.
3. Dynamic Territorialization Degree (T in [0.0, 1.0]): Striated vs Smooth Space.
4. Lines of Flight (Lignes de fuite), Deterritorialization Ruptures & Reterritorialization Consolidation.
5. Stratum State Transitions: ARBORESCENT_TREE -> RHIZOMATIC_MULTIPLICITY <-> STABILIZED_ASSEMBLAGE / OVERCODED_ARBORESCENT.
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
    rupture_threshold = float(config.get("rupture_threshold", 0.60))

    initial_nodes = {n["id"]: dict(n) for n in data.get("nodes", [])}
    initial_edges = list(data.get("edges", []))
    assemblage = dict(data.get("assemblage", {
        "name": "default_assemblage",
        "territorialization": 0.80,
        "stratum_type": "ARBORESCENT_TREE"
    }))

    events = data.get("perturbations", [])
    event_logs = []

    adj = {nid: set() for nid in initial_nodes}
    for e in initial_edges:
        u, v = e["source"], e["target"]
        adj.setdefault(u, set()).add(v)
        if not e.get("directed", False):
            adj.setdefault(v, set()).add(u)

    current_t = float(assemblage.get("territorialization", 0.80))
    current_stratum = assemblage.get("stratum_type", "ARBORESCENT_TREE")

    for idx, ev in enumerate(events, start=1):
        ev_type = ev.get("type", "INTENSITY_SURGE")
        intensity = float(ev.get("intensity", 0.50))
        source = ev.get("source")
        target = ev.get("target")

        log = {
            "event_index": idx,
            "type": ev_type,
            "intensity": intensity,
            "details": {}
        }

        if ev_type == "LINE_OF_FLIGHT":
            if intensity >= rupture_threshold - 1e-7:
                if source in adj and target:
                    adj[source].add(target)
                    adj.setdefault(target, set()).add(source)

                deterr = round(intensity * 0.30, 4)
                current_t = max(0.0, round(current_t - deterr, 4))
                outcome = "DETERRITORIALIZATION_RUPTURE"
                if current_t < 0.40:
                    current_stratum = "RHIZOMATIC_MULTIPLICITY"
                elif current_t < 0.70:
                    current_stratum = "STABILIZED_ASSEMBLAGE"
            else:
                outcome = "CAPTURED_BY_STRATUM"

            log["details"] = {
                "outcome": outcome,
                "territorialization_level": round(current_t, 4),
                "stratum_type": current_stratum,
                "connection_created": [source, target] if (intensity >= rupture_threshold - 1e-7 and source and target) else None
            }

        elif ev_type == "RETERRITORIALIZATION":
            reterr = round(intensity * 0.25, 4)
            current_t = min(1.0, round(current_t + reterr, 4))
            if current_t >= 0.70:
                current_stratum = "OVERCODED_ARBORESCENT"
            elif current_t >= 0.40:
                current_stratum = "STABILIZED_ASSEMBLAGE"
            else:
                current_stratum = "RHIZOMATIC_MULTIPLICITY"

            log["details"] = {
                "outcome": "RETERRITORIALIZATION_CONSOLIDATED",
                "territorialization_level": round(current_t, 4),
                "stratum_type": current_stratum
            }

        event_logs.append(log)

    total_edges = sum(len(neighbors) for neighbors in adj.values()) // 2
    avg_degree = round((2.0 * total_edges) / len(adj), 4) if adj else 0.0

    output = {
        "summary": {
            "assemblage_name": assemblage.get("name", "assemblage"),
            "final_territorialization": round(current_t, 4),
            "final_stratum_type": current_stratum,
            "total_plateau_nodes": len(adj),
            "total_rhizome_connections": total_edges,
            "average_rhizomatic_degree": avg_degree
        },
        "event_history": event_logs
    }

    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    solve()
