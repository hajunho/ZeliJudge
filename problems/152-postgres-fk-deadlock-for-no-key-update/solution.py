import json
import sys

COMPATIBILITY = {
    "FOR_KEY_SHARE": {
        "FOR_KEY_SHARE": True,
        "FOR_SHARE": True,
        "FOR_NO_KEY_UPDATE": True,
        "FOR_UPDATE": False
    },
    "FOR_SHARE": {
        "FOR_KEY_SHARE": True,
        "FOR_SHARE": True,
        "FOR_NO_KEY_UPDATE": False,
        "FOR_UPDATE": False
    },
    "FOR_NO_KEY_UPDATE": {
        "FOR_KEY_SHARE": True,
        "FOR_SHARE": False,
        "FOR_NO_KEY_UPDATE": False,
        "FOR_UPDATE": False
    },
    "FOR_UPDATE": {
        "FOR_KEY_SHARE": False,
        "FOR_SHARE": False,
        "FOR_NO_KEY_UPDATE": False,
        "FOR_UPDATE": False
    }
}

def solve(data):
    operations = data.get("operations", [])
    
    # lock_table: resource_key -> list of (tx_id, mode)
    lock_table = {}
    
    # tx_locks: tx_id -> list of (resource_key, mode)
    tx_locks = {}
    
    # waiting_tx: tx_id -> (resource_key, mode, op_index)
    waiting_tx = {}
    
    # wait_for_graph: tx_id -> set of tx_ids it is waiting for
    wait_for_graph = {}
    
    committed_txs = set()
    aborted_txs = set()
    
    lock_requests_total = 0
    lock_granted_count = 0
    lock_wait_count = 0
    deadlock_detected = False
    deadlock_cycle = []
    
    def can_acquire(tx_id, resource, req_mode):
        holders = lock_table.get(resource, [])
        for h_tx, h_mode in holders:
            if h_tx == tx_id:
                continue
            if not COMPATIBILITY.get(req_mode, {}).get(h_mode, False):
                return False, h_tx
        return True, None

    def find_cycle():
        # DFS to find cycle in wait_for_graph
        visited = {}
        path = []
        cycle_found = []

        def dfs(node):
            nonlocal cycle_found
            visited[node] = 1 # in stack
            path.append(node)
            for neighbor in sorted(list(wait_for_graph.get(node, set()))):
                if visited.get(neighbor, 0) == 1:
                    # cycle!
                    idx = path.index(neighbor)
                    cycle_found = path[idx:] + [neighbor]
                    return True
                elif visited.get(neighbor, 0) == 0:
                    if dfs(neighbor):
                        return True
            path.pop()
            visited[node] = 2 # finished
            return False

        for n in sorted(list(wait_for_graph.keys())):
            if visited.get(n, 0) == 0:
                if dfs(n):
                    return cycle_found
        return []

    def release_tx(tx_id):
        nonlocal lock_granted_count
        # Release all locks held by tx_id
        for res, mode in tx_locks.get(tx_id, []):
            if res in lock_table:
                lock_table[res] = [item for item in lock_table[res] if item[0] != tx_id]
                if not lock_table[res]:
                    del lock_table[res]
        tx_locks[tx_id] = []
        if tx_id in waiting_tx:
            del waiting_tx[tx_id]
        if tx_id in wait_for_graph:
            del wait_for_graph[tx_id]
        for t in wait_for_graph:
            wait_for_graph[t].discard(tx_id)

        # Try to wake up waiting transactions
        for w_tx in sorted(list(waiting_tx.keys())):
            if w_tx in aborted_txs or w_tx in committed_txs:
                continue
            w_res, w_mode, _ = waiting_tx[w_tx]
            ok, blocking_tx = can_acquire(w_tx, w_res, w_mode)
            if ok:
                # Grant lock!
                lock_granted_count += 1
                if w_res not in lock_table:
                    lock_table[w_res] = []
                lock_table[w_res].append((w_tx, w_mode))
                tx_locks[w_tx].append((w_res, w_mode))
                del waiting_tx[w_tx]
                if w_tx in wait_for_graph:
                    del wait_for_graph[w_tx]
                for t in wait_for_graph:
                    wait_for_graph[t].discard(w_tx)

    for op_idx, op in enumerate(operations):
        tx_id = op.get("tx_id", "")
        if tx_id in aborted_txs or tx_id in committed_txs:
            continue
            
        if tx_id not in tx_locks:
            tx_locks[tx_id] = []
        if tx_id not in wait_for_graph:
            wait_for_graph[tx_id] = set()

        action = op.get("action", "").upper()
        
        if action == "COMMIT":
            committed_txs.add(tx_id)
            release_tx(tx_id)
            
        elif action == "ROLLBACK":
            aborted_txs.add(tx_id)
            release_tx(tx_id)
            
        elif action == "LOCK_PARENT":
            p_id = op.get("parent_id")
            mode = op.get("lock_mode", "FOR_UPDATE").upper()
            res = f"PARENT_{p_id}"
            lock_requests_total += 1
            
            ok, blocking_tx = can_acquire(tx_id, res, mode)
            if ok:
                lock_granted_count += 1
                if res not in lock_table:
                    lock_table[res] = []
                lock_table[res].append((tx_id, mode))
                tx_locks[tx_id].append((res, mode))
            else:
                lock_wait_count += 1
                waiting_tx[tx_id] = (res, mode, op_idx)
                wait_for_graph[tx_id].add(blocking_tx)
                cycle = find_cycle()
                if cycle:
                    deadlock_detected = True
                    deadlock_cycle = cycle
                    # Abort current transaction
                    aborted_txs.add(tx_id)
                    release_tx(tx_id)

        elif action == "INSERT_CHILD":
            c_id = op.get("child_id")
            p_id = op.get("parent_id")
            
            # 1. Lock child tuple (Exclusive)
            c_res = f"CHILD_{c_id}"
            lock_requests_total += 1
            if c_res not in lock_table:
                lock_table[c_res] = []
            lock_table[c_res].append((tx_id, "FOR_UPDATE"))
            tx_locks[tx_id].append((c_res, "FOR_UPDATE"))
            lock_granted_count += 1
            
            # 2. Foreign Key validation on Parent: acquires FOR_KEY_SHARE on Parent!
            p_res = f"PARENT_{p_id}"
            fk_mode = "FOR_KEY_SHARE"
            lock_requests_total += 1
            
            ok, blocking_tx = can_acquire(tx_id, p_res, fk_mode)
            if ok:
                lock_granted_count += 1
                if p_res not in lock_table:
                    lock_table[p_res] = []
                lock_table[p_res].append((tx_id, fk_mode))
                tx_locks[tx_id].append((p_res, fk_mode))
            else:
                lock_wait_count += 1
                waiting_tx[tx_id] = (p_res, fk_mode, op_idx)
                wait_for_graph[tx_id].add(blocking_tx)
                cycle = find_cycle()
                if cycle:
                    deadlock_detected = True
                    deadlock_cycle = cycle
                    aborted_txs.add(tx_id)
                    release_tx(tx_id)

        elif action == "LOCK_CHILD":
            c_id = op.get("child_id")
            mode = op.get("lock_mode", "FOR_UPDATE").upper()
            res = f"CHILD_{c_id}"
            lock_requests_total += 1
            
            ok, blocking_tx = can_acquire(tx_id, res, mode)
            if ok:
                lock_granted_count += 1
                if res not in lock_table:
                    lock_table[res] = []
                lock_table[res].append((tx_id, mode))
                tx_locks[tx_id].append((res, mode))
            else:
                lock_wait_count += 1
                waiting_tx[tx_id] = (res, mode, op_idx)
                wait_for_graph[tx_id].add(blocking_tx)
                cycle = find_cycle()
                if cycle:
                    deadlock_detected = True
                    deadlock_cycle = cycle
                    aborted_txs.add(tx_id)
                    release_tx(tx_id)

    # Verdict
    if deadlock_detected:
        verdict = "FOR_UPDATE_FK_DEADLOCK_DISASTER"
    elif lock_wait_count == 0 and len(committed_txs) > 1:
        verdict = "FOR_NO_KEY_UPDATE_OPTIMAL"
    else:
        verdict = "BALANCED_EXECUTION"

    summary = {
        "lock_requests_total": lock_requests_total,
        "lock_granted_count": lock_granted_count,
        "lock_wait_count": lock_wait_count,
        "deadlock_detected": deadlock_detected,
        "deadlock_cycle": deadlock_cycle,
        "committed_transactions": sorted(list(committed_txs)),
        "aborted_transactions": sorted(list(aborted_txs)),
        "overall_verdict": verdict
    }

    return {
        "summary": summary
    }

if __name__ == "__main__":
    raw = sys.stdin.read().strip()
    if raw:
        inp = json.loads(raw)
        res = solve(inp)
        print(json.dumps(res, indent=2))
