#!/usr/bin/env python3
"""
ZeliJudge Problem #208: Ceph Distributed Storage - CRUSH Map Straw vs Straw2 Bucket Rebalancing & Data Movement Minimization
분산 스토리지 Ceph: CRUSH 맵 가중치 재분배, Straw vs Straw2 버킷 알고리즘과 데이터 이동 최소화

Reference Implementation
"""

import sys
import json
import math
import hashlib
from typing import Dict, Any, List, Tuple

def crush_hash(pg_id: int, item_id: str, replica_idx: int) -> int:
    s = f"{pg_id}:{item_id}:{replica_idx}"
    h = hashlib.md5(s.encode("utf-8")).hexdigest()
    return int(h[:8], 16)

def calc_classic_straws(children: List[Dict[str, Any]]) -> Dict[str, float]:
    sorted_items = sorted(children, key=lambda x: x["weight"])
    n = len(sorted_items)
    straws = {}
    straw = 1.0
    wbelow = 0.0
    for i in range(n):
        item_id = sorted_items[i]["id"]
        w = sorted_items[i]["weight"]
        if w <= 0:
            straws[item_id] = 0.0
            continue
        straws[item_id] = straw * 65536.0
        if i < n - 1:
            next_w = sorted_items[i+1]["weight"]
            if w == next_w:
                continue
            wbelow += w
            if wbelow > 0:
                straw *= math.pow((wbelow + next_w) / wbelow, 1.0 / (n - 1 - i))
    return straws

def pick_from_bucket(children: List[Dict[str, Any]], pg_id: int, replica_idx: int, algorithm: str) -> str:
    valid_children = [c for c in children if c["weight"] > 0]
    if not valid_children:
        return ""
    if len(valid_children) == 1:
        return valid_children[0]["id"]

    if algorithm == "STRAW2":
        best_score = -float("inf")
        best_item = ""
        for c in valid_children:
            h = crush_hash(pg_id, c["id"], replica_idx)
            u = (h % 65535 + 1) / 65536.0
            score = math.log(u) / c["weight"]
            if score > best_score:
                best_score = score
                best_item = c["id"]
        return best_item

    elif algorithm == "CLASSIC_STRAW":
        straws = calc_classic_straws(valid_children)
        max_straw = -1.0
        best_item = ""
        for c in valid_children:
            h = crush_hash(pg_id, c["id"], replica_idx) & 0xffff
            val = h * straws.get(c["id"], 0.0)
            if val > max_straw:
                max_straw = val
                best_item = c["id"]
        return best_item

    return ""

def simulate_ceph_crush(data: Dict[str, Any]) -> Dict[str, Any]:
    crush_cfg = data["crush_map"]
    algorithm = crush_cfg.get("bucket_algorithm", "STRAW2")
    failure_domain = crush_cfg.get("failure_domain_type", "rack")

    pool_cfg = data["pool_config"]
    num_pgs = pool_cfg.get("num_pgs", 1000)
    replica_count = pool_cfg.get("replica_count", 3)
    pg_size_gb = pool_cfg.get("pg_size_gb", 100.0)

    racks = crush_cfg.get("racks", {})
    racks_initial = {r: [dict(c) for c in osds] for r, osds in racks.items()}

    osd_to_fd = {}
    for r, osds in racks_initial.items():
        for o in osds:
            osd_to_fd[o["id"]] = r

    action = data.get("rebalance_action", {})
    action_type = action.get("action_type", "ADD_OSD")
    target_rack = action.get("target_rack", list(racks_initial.keys())[0] if racks_initial else "")
    target_osd = action.get("target_osd", "")
    new_weight = float(action.get("new_weight", 1.0))

    racks_rebalanced = {r: [dict(c) for c in osds] for r, osds in racks_initial.items()}

    if action_type == "ADD_OSD":
        if target_rack in racks_rebalanced:
            racks_rebalanced[target_rack].append({"id": target_osd, "weight": new_weight})
            osd_to_fd[target_osd] = target_rack
    elif action_type == "MODIFY_WEIGHT":
        if target_rack in racks_rebalanced:
            for c in racks_rebalanced[target_rack]:
                if c["id"] == target_osd:
                    c["weight"] = new_weight
                    break
    elif action_type == "REMOVE_OSD":
        if target_rack in racks_rebalanced:
            racks_rebalanced[target_rack] = [c for c in racks_rebalanced[target_rack] if c["id"] != target_osd]

    rack_names = sorted(list(racks_initial.keys()))
    num_racks = len(rack_names)

    def place_pg(rack_state: Dict[str, List[Dict[str, Any]]], pg_id: int) -> Tuple[List[str], int]:
        replicas = []
        violations = 0
        used_racks = set()

        if num_racks < replica_count:
            for r_idx in range(replica_count):
                assigned_rack = rack_names[r_idx % num_racks]
                if assigned_rack in used_racks:
                    violations += 1
                used_racks.add(assigned_rack)
                picked_osd = pick_from_bucket(rack_state[assigned_rack], pg_id, r_idx, algorithm)
                if picked_osd:
                    replicas.append(picked_osd)
        else:
            for r_idx in range(replica_count):
                assigned_rack = rack_names[r_idx % num_racks]
                used_racks.add(assigned_rack)
                picked_osd = pick_from_bucket(rack_state[assigned_rack], pg_id, r_idx, algorithm)
                if picked_osd:
                    replicas.append(picked_osd)

        return replicas, violations

    initial_placements = {}
    new_placements = {}
    total_violations = 0

    for pg in range(num_pgs):
        old_reps, v_old = place_pg(racks_initial, pg)
        new_reps, v_new = place_pg(racks_rebalanced, pg)
        initial_placements[pg] = old_reps
        new_placements[pg] = new_reps
        total_violations += v_new

    total_pg_replicas = num_pgs * replica_count
    moved_replicas = 0
    moves_to_or_from_target = 0
    unnecessary_moves = 0

    for pg in range(num_pgs):
        old_reps = initial_placements[pg]
        new_reps = new_placements[pg]
        for r in range(min(len(old_reps), len(new_reps))):
            o_old = old_reps[r]
            o_new = new_reps[r]
            if o_old != o_new:
                moved_replicas += 1
                if o_old == target_osd or o_new == target_osd:
                    moves_to_or_from_target += 1
                else:
                    unnecessary_moves += 1

    total_data_movement_tb = round((moved_replicas * pg_size_gb) / 1024.0, 2)
    unnecessary_data_movement_tb = round((unnecessary_moves * pg_size_gb) / 1024.0, 2)
    unnecessary_ratio = round((unnecessary_moves / moved_replicas * 100.0), 2) if moved_replicas > 0 else 0.0

    if total_violations > 0:
        verdict = "FAILURE_DOMAIN_VIOLATION"
    elif unnecessary_moves > 0:
        verdict = "CLASSIC_STRAW_UNNECESSARY_DATA_MOVEMENT_STORM"
    else:
        verdict = "OPTIMAL_STRAW2_MINIMAL_DATA_MOVEMENT"

    output = {
        "status": "SUCCESS" if total_violations == 0 else "FAILED",
        "verdict": verdict,
        "bucket_algorithm": algorithm,
        "failure_domain_type": failure_domain,
        "metrics": {
            "total_pgs": num_pgs,
            "replica_count": replica_count,
            "total_pg_replicas": total_pg_replicas,
            "moved_replicas": moved_replicas,
            "moves_to_or_from_target": moves_to_or_from_target,
            "unnecessary_moves": unnecessary_moves,
            "unnecessary_move_ratio_pct": unnecessary_ratio,
            "total_data_movement_tb": total_data_movement_tb,
            "unnecessary_data_movement_tb": unnecessary_data_movement_tb,
            "failure_domain_violations": total_violations
        }
    }
    return output

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    result = simulate_ceph_crush(data)
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
