import sys
import json

STRATEGIES = {
    "ALL_C": {"p0": 1, "p_CC": 1, "p_CD": 1, "p_DC": 1, "p_DD": 1, "is_nice": True},
    "ALL_D": {"p0": 0, "p_CC": 0, "p_CD": 0, "p_DC": 0, "p_DD": 0, "is_nice": False},
    "TIT_FOR_TAT": {"p0": 1, "p_CC": 1, "p_CD": 0, "p_DC": 1, "p_DD": 0, "is_nice": True},
    "SUSPICIOUS_TFT": {"p0": 0, "p_CC": 1, "p_CD": 0, "p_DC": 1, "p_DD": 0, "is_nice": False},
    "PAVLOV": {"p0": 1, "p_CC": 1, "p_CD": 0, "p_DC": 0, "p_DD": 1, "is_nice": True},
    "GRIM_TRIGGER": {"p0": 1, "p_CC": 1, "p_CD": 0, "p_DC": 0, "p_DD": 0, "is_nice": True}
}

def simulate_match(s1_name, s2_name, rounds, payoff_matrix):
    R, T, S, P = payoff_matrix
    pay_map = {
        ('C', 'C'): (R, R),
        ('C', 'D'): (S, T),
        ('D', 'C'): (T, S),
        ('D', 'D'): (P, P)
    }
    
    strat1 = STRATEGIES[s1_name]
    strat2 = STRATEGIES[s2_name]
    
    score1, score2 = 0, 0
    h1, h2 = [], []
    
    for r in range(rounds):
        if r == 0:
            a1 = 'C' if strat1["p0"] == 1 else 'D'
            a2 = 'C' if strat2["p0"] == 1 else 'D'
        else:
            prev1, prev2 = h1[-1], h2[-1]
            key1 = f"p_{prev1}{prev2}"
            key2 = f"p_{prev2}{prev1}"
            a1 = 'C' if strat1[key1] == 1 else 'D'
            a2 = 'C' if strat2[key2] == 1 else 'D'
            
        p1, p2 = pay_map[(a1, a2)]
        score1 += p1
        score2 += p2
        h1.append(a1)
        h2.append(a2)
        
    avg1 = round(score1 / rounds, 4)
    avg2 = round(score2 / rounds, 4)
    mutual_coop_rate = round(sum(1 for x, y in zip(h1, h2) if x == 'C' and y == 'C') / rounds, 4)
    
    return {
        "strategy1": s1_name,
        "strategy2": s2_name,
        "score1": score1,
        "score2": score2,
        "avg_payoff1": avg1,
        "avg_payoff2": avg2,
        "mutual_cooperation_rate": mutual_coop_rate,
        "history1": "".join(h1),
        "history2": "".join(h2)
    }

def run_tournament(strategy_names, rounds, payoff_matrix):
    n = len(strategy_names)
    matrix = {}
    total_scores = {s: 0 for s in strategy_names}
    
    for i in range(n):
        s1 = strategy_names[i]
        matrix[s1] = {}
        for j in range(n):
            s2 = strategy_names[j]
            res = simulate_match(s1, s2, rounds, payoff_matrix)
            matrix[s1][s2] = res["avg_payoff1"]
            total_scores[s1] += res["score1"]
            
    ranked = sorted(strategy_names, key=lambda s: (total_scores[s], STRATEGIES[s]["is_nice"]), reverse=True)
    rankings = []
    nice_scores = []
    nasty_scores = []
    
    for rank, s in enumerate(ranked, 1):
        avg_p = round(total_scores[s] / (n * rounds), 4)
        is_nice = STRATEGIES[s]["is_nice"]
        if is_nice:
            nice_scores.append(avg_p)
        else:
            nasty_scores.append(avg_p)
            
        rankings.append({
            "rank": rank,
            "strategy": s,
            "total_score": total_scores[s],
            "avg_payoff_per_round": avg_p,
            "is_nice": is_nice
        })
        
    avg_nice = round(sum(nice_scores) / len(nice_scores), 4) if nice_scores else 0.0
    avg_nasty = round(sum(nasty_scores) / len(nasty_scores), 4) if nasty_scores else 0.0
    
    return {
        "payoff_matrix_table": matrix,
        "tournament_rankings": rankings,
        "winner": rankings[0]["strategy"],
        "nice_strategies_avg_payoff": avg_nice,
        "nasty_strategies_avg_payoff": avg_nasty,
        "nice_dominates": avg_nice > avg_nasty
    }

def run_replicator_dynamics(initial_shares, payoff_table, generations):
    shares = dict(initial_shares)
    strats = list(shares.keys())
    
    trajectory = []
    
    for gen in range(generations + 1):
        cur_record = {"generation": gen, "shares": {s: round(shares[s], 4) for s in strats}}
        trajectory.append(cur_record)
        
        if gen == generations:
            break
            
        fitness = {}
        for s in strats:
            f = sum(shares[s2] * payoff_table[s][s2] for s2 in strats)
            fitness[s] = f
            
        avg_fitness = sum(shares[s] * fitness[s] for s in strats)
        
        if avg_fitness <= 1e-9:
            break
            
        new_shares = {}
        for s in strats:
            new_share = shares[s] * (fitness[s] / avg_fitness)
            if new_share < 1e-5:
                new_share = 0.0
            new_shares[s] = new_share
            
        tot_new = sum(new_shares.values())
        if tot_new > 0:
            shares = {s: new_shares[s] / tot_new for s in strats}
        else:
            break
            
    surviving = [s for s in strats if shares[s] > 0.01]
    extinct = [s for s in strats if shares[s] <= 0.01]
    
    return {
        "generations_run": generations,
        "final_shares": {s: round(shares[s], 4) for s in strats},
        "surviving_strategies": surviving,
        "extinct_strategies": extinct,
        "dominant_strategy": max(shares, key=lambda s: shares[s])
    }

def run_simulation(req):
    default_payoff = req.get("payoff_matrix", [3, 5, 0, 1])
    logs = []
    last_tourn_table = None
    
    for op_item in req.get("operations", []):
        step = op_item["step"]
        op = op_item["op"]
        
        if op == "MATCH":
            s1 = op_item["strategy1"]
            s2 = op_item["strategy2"]
            rounds = op_item.get("rounds", 20)
            payoff = op_item.get("payoff_matrix", default_payoff)
            res = simulate_match(s1, s2, rounds, payoff)
            logs.append({"step": step, "op": op, **res})
            
        elif op == "TOURNAMENT":
            strats = op_item["strategies"]
            rounds = op_item.get("rounds", 20)
            payoff = op_item.get("payoff_matrix", default_payoff)
            res = run_tournament(strats, rounds, payoff)
            last_tourn_table = res["payoff_matrix_table"]
            logs.append({"step": step, "op": op, **res})
            
        elif op == "REPLICATOR_DYNAMICS":
            init_shares = op_item["initial_shares"]
            generations = op_item.get("generations", 10)
            p_table = op_item.get("payoff_table", last_tourn_table)
            if not p_table:
                strats = list(init_shares.keys())
                rounds = op_item.get("rounds", 20)
                payoff = op_item.get("payoff_matrix", default_payoff)
                tourn_res = run_tournament(strats, rounds, payoff)
                p_table = tourn_res["payoff_matrix_table"]
            res = run_replicator_dynamics(init_shares, p_table, generations)
            logs.append({"step": step, "op": op, **res})
            
        elif op == "INVASION_ANALYSIS":
            resident = op_item["resident_strategy"]
            invader = op_item["invader_strategy"]
            cluster_share = op_item.get("cluster_share", 0.05)
            rounds = op_item.get("rounds", 20)
            payoff = op_item.get("payoff_matrix", default_payoff)
            
            m_res = run_tournament([resident, invader], rounds, payoff)
            p_tab = m_res["payoff_matrix_table"]
            
            res_share = 1.0 - cluster_share
            fit_resident = res_share * p_tab[resident][resident] + cluster_share * p_tab[resident][invader]
            fit_invader = res_share * p_tab[invader][resident] + cluster_share * p_tab[invader][invader]
            can_invade = fit_invader > fit_resident
            
            logs.append({
                "step": step,
                "op": op,
                "resident_strategy": resident,
                "invader_strategy": invader,
                "cluster_share": cluster_share,
                "resident_fitness": round(fit_resident, 4),
                "invader_fitness": round(fit_invader, 4),
                "can_invade": can_invade
            })
            
    return {"operations_log": logs}

def main():
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        
    raw_in = sys.stdin.read().strip()
    if not raw_in:
        return
        
    req = json.loads(raw_in)
    res = run_simulation(req)
    print(json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    main()
