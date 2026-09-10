import sys
import json

class SpatialCompetitionEngine:
    def __init__(self, voter_distribution, alienation_threshold=None):
        self.voters = voter_distribution
        self.alienation_threshold = alienation_threshold
        self.tot_voters = sum(v["weight"] for v in self.voters)

    def compute_median(self):
        cum = 0.0
        target = self.tot_voters / 2.0
        for v in sorted(self.voters, key=lambda item: item["x"]):
            cum += v["weight"]
            if cum >= target:
                return v["x"]
        return self.voters[-1]["x"]

    def evaluate_election(self, candidates):
        shares = {c: 0.0 for c in candidates}
        abstentions = 0.0
        
        for v in self.voters:
            vx, vw = v["x"], v["weight"]
            dists = {c: abs(vx - pos) for c, pos in candidates.items()}
            min_d = min(dists.values())
            
            if self.alienation_threshold is not None and min_d > self.alienation_threshold:
                abstentions += vw
                continue
                
            closest = [c for c, d in dists.items() if abs(d - min_d) < 1e-6]
            for c in closest:
                shares[c] += vw / len(closest)
                
        percentages = {c: round((shares[c] / self.tot_voters) * 100.0, 2) for c in candidates}
        abstention_pct = round((abstentions / self.tot_voters) * 100.0, 2)
        
        ranked = sorted(candidates.keys(), key=lambda c: (shares[c], -candidates[c]), reverse=True)
        winner = ranked[0]
        margin = round(shares[ranked[0]] - (shares[ranked[1]] if len(ranked) > 1 else 0.0), 2)
        is_tie = len(ranked) > 1 and abs(shares[ranked[0]] - shares[ranked[1]]) < 1e-4
        
        return {
            "candidate_positions": candidates,
            "raw_votes": {c: round(shares[c], 2) for c in candidates},
            "vote_percentages": percentages,
            "abstention_votes": round(abstentions, 2),
            "abstention_pct": abstention_pct,
            "winner": winner if not is_tie else "TIE",
            "margin_of_victory": margin,
            "is_tie": is_tie
        }

    def optimize_position(self, candidate_to_move, current_candidates, grid_min=0, grid_max=100, grid_step=1):
        other_cands = {c: pos for c, pos in current_candidates.items() if c != candidate_to_move}
        best_pos = current_candidates[candidate_to_move]
        
        cur_eval = self.evaluate_election(current_candidates)
        best_votes = cur_eval["raw_votes"][candidate_to_move]
        
        grid = [grid_min + i * grid_step for i in range(int((grid_max - grid_min) / grid_step) + 1)]
        
        for pos in grid:
            trial = dict(other_cands)
            trial[candidate_to_move] = pos
            ev = self.evaluate_election(trial)
            v = ev["raw_votes"][candidate_to_move]
            if v > best_votes + 1e-4:
                best_votes = v
                best_pos = pos
                
        new_cands = dict(other_cands)
        new_cands[candidate_to_move] = best_pos
        new_eval = self.evaluate_election(new_cands)
        
        return {
            "candidate": candidate_to_move,
            "previous_position": current_candidates[candidate_to_move],
            "optimal_position": best_pos,
            "votes_before": cur_eval["raw_votes"][candidate_to_move],
            "votes_after": new_eval["raw_votes"][candidate_to_move],
            "vote_gain": round(new_eval["raw_votes"][candidate_to_move] - cur_eval["raw_votes"][candidate_to_move], 2)
        }

def run_simulation(req):
    voters = req.get("voters", [])
    alienation = req.get("alienation_threshold", None)
    engine = SpatialCompetitionEngine(voters, alienation)
    
    logs = []
    current_candidates = dict(req.get("initial_candidates", {}))
    
    for op_item in req.get("operations", []):
        step = op_item["step"]
        op = op_item["op"]
        
        if op == "COMPUTE_MEDIAN":
            med = engine.compute_median()
            logs.append({"step": step, "op": op, "median_voter_position": med})
            
        elif op == "EVALUATE_ELECTION":
            cands = op_item.get("candidates", current_candidates)
            current_candidates = dict(cands)
            res = engine.evaluate_election(cands)
            logs.append({"step": step, "op": op, **res})
            
        elif op == "OPTIMIZE_POSITION":
            cand = op_item["candidate"]
            g_min = op_item.get("grid_min", 0)
            g_max = op_item.get("grid_max", 100)
            g_step = op_item.get("grid_step", 1)
            res = engine.optimize_position(cand, current_candidates, g_min, g_max, g_step)
            current_candidates[cand] = res["optimal_position"]
            logs.append({"step": step, "op": op, **res})
            
        elif op == "SIMULATE_CAMPAIGN":
            rounds = op_item.get("rounds", 3)
            turn_order = op_item.get("turn_order", list(current_candidates.keys()))
            g_min = op_item.get("grid_min", 0)
            g_max = op_item.get("grid_max", 100)
            g_step = op_item.get("grid_step", 1)
            
            campaign_history = []
            for r in range(1, rounds + 1):
                round_moves = {}
                for cand in turn_order:
                    res = engine.optimize_position(cand, current_candidates, g_min, g_max, g_step)
                    current_candidates[cand] = res["optimal_position"]
                    round_moves[cand] = {
                        "from": res["previous_position"],
                        "to": res["optimal_position"],
                        "votes": res["votes_after"]
                    }
                campaign_history.append({"round": r, "moves": round_moves})
                
            final_eval = engine.evaluate_election(current_candidates)
            logs.append({
                "step": step,
                "op": op,
                "campaign_history": campaign_history,
                "final_evaluation": final_eval
            })
            
    return {
        "operations_log": logs,
        "final_candidates": current_candidates
    }

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
