import sys
import json
from typing import List, Dict, Any

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

def match_condition(item: Any, cond: Dict[str, Any]) -> bool:
    if cond.get("boundary") == "#":
        return False
    if item is None:
        return False
    feat = item.get("features", {})
    for k, v in cond.items():
        if k == "boundary":
            continue
        if feat.get(k) != v:
            return False
    return True

def find_matching_symbol(inventory: Dict[str, Dict[str, str]], features: Dict[str, str]) -> str:
    best_sym = "?"
    best_score = -1
    for sym, inv_feat in inventory.items():
        match = True
        for k, v in inv_feat.items():
            if features.get(k) != v:
                match = False
                break
        if match:
            score = len(inv_feat)
            if score > best_score:
                best_score = score
                best_sym = sym
    return best_sym

def apply_spe_rules(inventory: Dict[str, Dict[str, str]], 
                    underlying: List[str], 
                    rules: List[Dict[str, Any]]) -> Dict[str, Any]:
    current_segments = []
    for s in underlying:
        feat = dict(inventory.get(s, {}))
        current_segments.append({"symbol": s, "features": feat})
        
    derivation = [{
        "stage": "Underlying Representation", 
        "form": [seg["symbol"] for seg in current_segments], 
        "applied_at": []
    }]

    for rule in rules:
        rule_name = rule["name"]
        action = rule.get("action", "change") # "change", "delete", "insert"
        target_cond = rule.get("target", {})
        left_ctx = rule.get("left_context", [])
        right_ctx = rule.get("right_context", [])
        
        n = len(current_segments)
        
        def match_left(pos: int) -> bool:
            k = len(left_ctx)
            if k == 0:
                return True
            for offset, cond in enumerate(left_ctx):
                target_idx = pos - k + offset
                if cond.get("boundary") == "#":
                    if target_idx != -1:
                        return False
                else:
                    if target_idx < 0 or target_idx >= n:
                        return False
                    if not match_condition(current_segments[target_idx], cond):
                        return False
            return True

        def match_right(pos: int) -> bool:
            k = len(right_ctx)
            if k == 0:
                return True
            for offset, cond in enumerate(right_ctx):
                target_idx = pos + offset
                if cond.get("boundary") == "#":
                    if target_idx != n:
                        return False
                else:
                    if target_idx < 0 or target_idx >= n:
                        return False
                    if not match_condition(current_segments[target_idx], cond):
                        return False
            return True

        applied_indices = []
        
        if action in ("change", "delete"):
            matched_indices = []
            for i in range(n):
                if match_condition(current_segments[i], target_cond):
                    if match_left(i) and match_right(i + 1):
                        matched_indices.append(i)
            
            applied_indices = list(matched_indices)
            
            if matched_indices:
                if action == "delete":
                    current_segments = [seg for idx, seg in enumerate(current_segments) if idx not in set(matched_indices)]
                elif action == "change":
                    changes = rule.get("change", {})
                    copy_source = rule.get("copy_from", None)
                    result_symbol = rule.get("result_symbol", None)
                    
                    for idx in matched_indices:
                        new_feat = dict(current_segments[idx]["features"])
                        for f, val in changes.items():
                            new_feat[f] = val
                        if copy_source:
                            direction = copy_source.get("direction")
                            offset = copy_source.get("offset", 0)
                            features_to_copy = copy_source.get("features", [])
                            src_idx = (idx + 1 + offset) if direction == "right" else (idx - 1 - offset)
                            if 0 <= src_idx < n:
                                src_feat = current_segments[src_idx]["features"]
                                for f in features_to_copy:
                                    if f in src_feat:
                                        new_feat[f] = src_feat[f]
                                        
                        sym = result_symbol
                        if not sym:
                            sym = find_matching_symbol(inventory, new_feat)
                        current_segments[idx] = {"symbol": sym, "features": new_feat}
                        
        elif action == "insert":
            insert_points = []
            for i in range(n + 1):
                if match_left(i) and match_right(i):
                    insert_points.append(i)
            
            applied_indices = list(insert_points)
            if insert_points:
                insert_seg_def = rule.get("insert_segment", {})
                insert_sym = insert_seg_def.get("symbol", "")
                insert_feat = dict(insert_seg_def.get("features", inventory.get(insert_sym, {})))
                if not insert_sym:
                    insert_sym = find_matching_symbol(inventory, insert_feat)
                    
                for pt in reversed(insert_points):
                    current_segments.insert(pt, {
                        "symbol": insert_sym,
                        "features": dict(insert_feat)
                    })
                    
        derivation.append({
            "stage": rule_name,
            "form": [seg["symbol"] for seg in current_segments],
            "applied_at": applied_indices
        })
        
    surface = [seg["symbol"] for seg in current_segments]
    return {
        "surface_representation": surface,
        "surface_string": "".join(surface),
        "derivation": derivation
    }

def main():
    raw_data = sys.stdin.read().strip()
    if not raw_data:
        return
    data = json.loads(raw_data)
    inventory = data.get("inventory", {})
    underlying = data.get("underlying_representation", [])
    rules = data.get("rules", [])
    
    result = apply_spe_rules(inventory, underlying, rules)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
