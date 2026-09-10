import sys
import json

# Ensure UTF-8 IO
sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

def evaluate_coins(req):
    market = req["market_prices"]
    p_silver = market["price_per_gram_silver"]
    p_gold = market["price_per_gram_gold"]
    
    results = []
    for c in req["coins"]:
        cid = c["coin_id"]
        face = c["nominal_face_value"]
        metal = c["metal"].lower()
        weight = c["gross_weight_grams"]
        fineness = c["fineness"]
        
        price_per_g = p_gold if metal == "gold" else p_silver
        fine_weight = round(weight * fineness, 4)
        bullion_val = round(fine_weight * price_per_g, 4)
        disparity = round(bullion_val / face, 4)
        
        if disparity > 1.0001:
            cls = "UNDERVALUED_GOOD_MONEY"
            act = "HOARD_OR_MELT"
        elif disparity < 0.9999:
            cls = "OVERVALUED_BAD_MONEY"
            act = "SPEND_IN_TRANSACTION"
        else:
            cls = "PAR_VALUE"
            act = "CIRCULATE_AT_PAR"
            
        results.append({
            "coin_id": cid,
            "fine_weight_grams": fine_weight,
            "intrinsic_bullion_value": bullion_val,
            "disparity_ratio": disparity,
            "classification": cls,
            "action_recommendation": act
        })
        
    return {
        "mode": "evaluate_coins",
        "evaluated_coins": results
    }

def bimetallic_arbitrage(req):
    mint_ratio = req["mint_legal_ratio"]
    market_ratio = req["market_commercial_ratio"]
    cap = req["capital"]
    cost_pct = req.get("transaction_cost_pct", 0.0)
    
    c_metal = cap["metal"].lower()
    c_amount = cap["amount"]
    
    if abs(market_ratio - mint_ratio) < 1e-6:
        return {
            "mode": "bimetallic_arbitrage",
            "is_arbitrage_profitable": False,
            "arbitrage_strategy": "NO_ARBITRAGE",
            "net_profit_amount": 0.0,
            "profit_percentage": 0.0
        }
        
    if market_ratio > mint_ratio:
        strat = "BRING_SILVER_TO_MINT_EXPORT_GOLD_TO_MARKET"
        multiplier = (market_ratio / mint_ratio) * (1.0 - cost_pct)
        profit_pct = round((multiplier - 1.0) * 100.0, 4)
        if profit_pct > 0:
            gross_return = c_amount * (market_ratio / mint_ratio)
            net_return = gross_return * (1.0 - cost_pct)
            profit = round(net_return - c_amount, 4)
            return {
                "mode": "bimetallic_arbitrage",
                "is_arbitrage_profitable": True,
                "arbitrage_strategy": strat,
                "net_profit_amount": profit,
                "profit_percentage": profit_pct
            }
        else:
            return {
                "mode": "bimetallic_arbitrage",
                "is_arbitrage_profitable": False,
                "arbitrage_strategy": "UNPROFITABLE_DUE_TO_FRICTION",
                "net_profit_amount": 0.0,
                "profit_percentage": 0.0
            }
    else:
        strat = "BRING_GOLD_TO_MINT_EXPORT_SILVER_TO_MARKET"
        multiplier = (mint_ratio / market_ratio) * (1.0 - cost_pct)
        profit_pct = round((multiplier - 1.0) * 100.0, 4)
        if profit_pct > 0:
            gross_return = c_amount * (mint_ratio / market_ratio)
            net_return = gross_return * (1.0 - cost_pct)
            profit = round(net_return - c_amount, 4)
            return {
                "mode": "bimetallic_arbitrage",
                "is_arbitrage_profitable": True,
                "arbitrage_strategy": strat,
                "net_profit_amount": profit,
                "profit_percentage": profit_pct
            }
        else:
            return {
                "mode": "bimetallic_arbitrage",
                "is_arbitrage_profitable": False,
                "arbitrage_strategy": "UNPROFITABLE_DUE_TO_FRICTION",
                "net_profit_amount": 0.0,
                "profit_percentage": 0.0
            }

def simulate_greshams_circulation(req):
    wallet = list(req["initial_wallet"])
    tx_results = []
    
    for tx in req["transactions"]:
        tx_id = tx["transaction_id"]
        due = tx["amount_due"]
        
        best_subset = None
        best_intrinsic = float("inf")
        
        available = list(enumerate(wallet))
        available.sort(key=lambda x: (x[1]["intrinsic_value"] / x[1]["face_value"], x[1]["intrinsic_value"], x[1]["coin_id"]))
        
        def search(idx, current_sum, current_intrinsic, chosen_indices):
            nonlocal best_subset, best_intrinsic
            if current_sum == due:
                if current_intrinsic < best_intrinsic:
                    best_intrinsic = current_intrinsic
                    best_subset = list(chosen_indices)
                return
            if current_sum > due or current_intrinsic >= best_intrinsic or idx >= len(available):
                return
            
            orig_i, c = available[idx]
            search(idx + 1, current_sum + c["face_value"], current_intrinsic + c["intrinsic_value"], chosen_indices + [orig_i])
            search(idx + 1, current_sum, current_intrinsic, chosen_indices)

        search(0, 0, 0, [])
        
        if best_subset is None:
            tx_results.append({
                "transaction_id": tx_id,
                "status": "FAILED_INSUFFICIENT_FUNDS",
                "coins_spent": []
            })
            continue
            
        spent_coins = [wallet[i] for i in best_subset]
        spent_ids = [c["coin_id"] for c in spent_coins]
        total_face = sum(c["face_value"] for c in spent_coins)
        total_intr = round(sum(c["intrinsic_value"] for c in spent_coins), 4)
        
        chosen_set = set(best_subset)
        wallet = [c for i, c in enumerate(wallet) if i not in chosen_set]
        
        tx_results.append({
            "transaction_id": tx_id,
            "status": "COMPLETED",
            "coins_spent": spent_ids,
            "total_face_value": total_face,
            "total_intrinsic_value_spent": total_intr
        })
        
    hoard_ids = [c["coin_id"] for c in wallet]
    retained_face = sum(c["face_value"] for c in wallet)
    retained_intr = round(sum(c["intrinsic_value"] for c in wallet), 4)
    hoard_ratio = round(retained_intr / retained_face, 4) if retained_face > 0 else 1.0
    
    return {
        "mode": "simulate_greshams_circulation",
        "transactions_executed": tx_results,
        "retained_hoard": {
            "coins": hoard_ids,
            "total_face_value": retained_face,
            "total_intrinsic_value": retained_intr,
            "hoard_quality_ratio": hoard_ratio
        }
    }

def solve():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    req = json.loads(raw)
    mode = req.get("mode")
    
    if mode == "evaluate_coins":
        res = evaluate_coins(req)
    elif mode == "bimetallic_arbitrage":
        res = bimetallic_arbitrage(req)
    elif mode == "simulate_greshams_circulation":
        res = simulate_greshams_circulation(req)
    else:
        res = {"error": f"Unknown mode: {mode}"}
        
    print(json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    solve()
