# -*- coding: utf-8 -*-
import sys
import json
import heapq

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

def dijkstra_cost(nodes, edges_by_node, origin, destination, allowed_modes, interest_rate, unit_val):
    dist = {n: float("inf") for n in nodes}
    dist[origin] = 0.0
    pq = [(0.0, origin)]
    
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]:
            continue
        if u == destination:
            return d
            
        for v, mode, info in edges_by_node.get(u, []):
            if mode not in allowed_modes:
                continue
            
            cost = info["distance_miles"] * info["rate_per_ton_mile"]
            
            if mode == "water":
                frozen_days = info.get("frozen_days_per_year", 0)
                transship = info.get("transshipment_cost_per_ton", 0.0)
                carrying_cost = unit_val * interest_rate * (frozen_days / 365.0)
                cost += transship + carrying_cost
                
            if dist[u] + cost < dist[v]:
                dist[v] = dist[u] + cost
                heapq.heappush(pq, (dist[v], v))
                
    return dist[destination]

def calculate_social_savings(data):
    gnp = float(data.get("gnp_dollars", 12000000000.0))
    interest_rate = float(data.get("inventory_interest_rate", 0.06))
    nodes = data.get("nodes", [])
    raw_edges = data.get("edges", [])
    flows = data.get("commodity_flows", [])
    
    edges_by_node = {n: [] for n in nodes}
    for e in raw_edges:
        u = e["u"]
        v = e["v"]
        for mode, info in e["modes"].items():
            edges_by_node[u].append((v, mode, info))
            edges_by_node[v].append((u, mode, info))
            
    actual_allowed = {"rail", "water", "wagon"}
    counterfactual_allowed = {"water", "wagon"}
    
    flow_results = []
    total_actual_cost = 0.0
    total_counterfactual_cost = 0.0
    
    for f in flows:
        orig = f["origin"]
        dest = f["destination"]
        tons = float(f["tons"])
        unit_val = float(f.get("unit_value_per_ton", 25.0))
        commodity = f.get("commodity", "AGRICULTURAL_GRAIN")
        
        c_actual = dijkstra_cost(nodes, edges_by_node, orig, dest, actual_allowed, interest_rate, unit_val)
        c_counter = dijkstra_cost(nodes, edges_by_node, orig, dest, counterfactual_allowed, interest_rate, unit_val)
        
        bill_actual = round(c_actual * tons, 2)
        bill_counter = round(c_counter * tons, 2)
        saving = round(bill_counter - bill_actual, 2)
        
        total_actual_cost += bill_actual
        total_counterfactual_cost += bill_counter
        
        flow_results.append({
            "origin": orig,
            "destination": dest,
            "commodity": commodity,
            "tons": tons,
            "actual_cost_per_ton": round(c_actual, 2),
            "counterfactual_cost_per_ton": round(c_counter, 2),
            "actual_total_bill": bill_actual,
            "counterfactual_total_bill": bill_counter,
            "social_savings": saving
        })
        
    total_savings = round(total_counterfactual_cost - total_actual_cost, 2)
    gnp_share_pct = round((total_savings / gnp) * 100.0, 2) if gnp > 0 else 0.0
    
    verdict = "DISPROVED_AXIOM_OF_INDISPENSABILITY" if gnp_share_pct < 5.0 else "INDISPENSABLE_INFRASTRUCTURE"
    
    return {
        "gnp_dollars": gnp,
        "total_actual_freight_bill": round(total_actual_cost, 2),
        "total_counterfactual_freight_bill": round(total_counterfactual_cost, 2),
        "total_social_savings": total_savings,
        "social_savings_pct_of_gnp": gnp_share_pct,
        "verdict": verdict,
        "flow_breakdown": flow_results
    }

def run_sensitivity_analysis(data):
    base_data = data.get("base_data", {})
    variations = data.get("wagon_rate_variations", [0.10, 0.15, 0.20, 0.25])
    results = []
    
    for rate in variations:
        temp_data = json.loads(json.dumps(base_data))
        for e in temp_data.get("edges", []):
            if "wagon" in e.get("modes", {}):
                e["modes"]["wagon"]["rate_per_ton_mile"] = rate
        res = calculate_social_savings(temp_data)
        results.append({
            "wagon_rate_per_ton_mile": rate,
            "total_social_savings": res["total_social_savings"],
            "social_savings_pct_of_gnp": res["social_savings_pct_of_gnp"],
            "verdict": res["verdict"]
        })
        
    return {
        "sensitivity_parameter": "wagon_rate_per_ton_mile",
        "tested_points": len(results),
        "results": results
    }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    mode = data.get("mode", "CALCULATE_SOCIAL_SAVINGS")
    
    if mode == "CALCULATE_SOCIAL_SAVINGS":
        res = calculate_social_savings(data)
        print(json.dumps(res, ensure_ascii=False))
    elif mode == "SENSITIVITY_ANALYSIS":
        res = run_sensitivity_analysis(data)
        print(json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    main()
