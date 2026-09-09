import sys

def gap_str(left, right):
    l_str = "-inf" if left is None else str(left)
    r_str = "+inf" if right is None else str(right)
    return f"({l_str}, {r_str})"

class Transaction:
    def __init__(self, tx_id, isolation_level):
        self.tx_id = tx_id
        self.isolation_level = isolation_level  # "RR" or "RC"
        self.status = "ACTIVE"                  # ACTIVE, BLOCKED, COMMITTED, ROLLEDBACK
        self.gap_locks = set()                  # set of (left, right)
        self.rec_locks = set()                  # set of key
        self.waiting_for = None                 # tx_id of the transaction it is waiting on
        self.waiting_gap = None                 # (left, right)
        self.pending_insert_key = None          # key waiting to be inserted
        self.inserted_keys = set()              # keys inserted by this tx

class LockManager:
    def __init__(self):
        self.keys = []
        self.transactions = {}
        self.deadlock_count = 0

    def init_table(self, keys):
        self.keys = sorted(list(set(keys)))
        self.transactions = {}
        self.deadlock_count = 0
        gaps = self._get_all_gaps()
        gaps_repr = ", ".join(gap_str(l, r) for l, r in gaps)
        keys_repr = ", ".join(str(k) for k in self.keys)
        return f"INIT_OK keys=[{keys_repr}] gaps=[{gaps_repr}]"

    def _get_all_gaps(self):
        if not self.keys:
            return [(None, None)]
        gaps = [(None, self.keys[0])]
        for i in range(len(self.keys) - 1):
            gaps.append((self.keys[i], self.keys[i + 1]))
        gaps.append((self.keys[-1], None))
        return gaps

    def _find_gap_for_key(self, key):
        if not self.keys:
            return (None, None)
        if key < self.keys[0]:
            return (None, self.keys[0])
        for i in range(len(self.keys) - 1):
            if self.keys[i] < key < self.keys[i + 1]:
                return (self.keys[i], self.keys[i + 1])
        if key > self.keys[-1]:
            return (self.keys[-1], None)
        return None  # Key is already in keys

    def begin(self, tx_id, isolation_level):
        self.transactions[tx_id] = Transaction(tx_id, isolation_level.upper())
        return f"BEGIN_OK tx={tx_id} isolation={isolation_level.upper()}"

    def select_for_update(self, tx_id, *args):
        if tx_id not in self.transactions or self.transactions[tx_id].status not in ("ACTIVE", "BLOCKED"):
            return f"ERROR:TRANSACTION_INACTIVE tx={tx_id}"
        tx = self.transactions[tx_id]
        acquired = []

        if len(args) == 1:
            # Point query: SELECT ... WHERE id = target
            target = int(args[0])
            if target in self.keys:
                tx.rec_locks.add(target)
                acquired.append(f"REC_LOCK({target})")
            else:
                if tx.isolation_level == "RR":
                    gap = self._find_gap_for_key(target)
                    if gap:
                        tx.gap_locks.add(gap)
                        acquired.append(f"GAP_LOCK{gap_str(*gap)}")
        elif len(args) >= 2:
            # Range query: SELECT ... WHERE id BETWEEN start AND end
            start_k = int(args[0])
            end_k = int(args[1])
            # Record locks for existing keys in range
            for k in self.keys:
                if start_k <= k <= end_k:
                    tx.rec_locks.add(k)
                    acquired.append(f"REC_LOCK({k})")

            # In RR mode, lock gaps intersecting with [start_k, end_k]
            if tx.isolation_level == "RR":
                for l, r in self._get_all_gaps():
                    # Intersects check
                    left_ok = (l is None) or (l < end_k)
                    right_ok = (r is None) or (r > start_k)
                    if left_ok and right_ok:
                        tx.gap_locks.add((l, r))
                        acquired.append(f"GAP_LOCK{gap_str(l, r)}")

        locks_repr = ", ".join(acquired)
        return f"LOCK_ACQUIRED tx={tx_id} locks=[{locks_repr}]"

    def _check_deadlock(self, start_tx_id, target_tx_id):
        # Check if target_tx_id transitively waits for start_tx_id
        curr = target_tx_id
        visited = set()
        while curr:
            if curr == start_tx_id:
                return True
            if curr in visited:
                break
            visited.add(curr)
            curr_tx = self.transactions.get(curr)
            curr = curr_tx.waiting_for if curr_tx else None
        return False

    def insert(self, tx_id, key):
        if tx_id not in self.transactions or self.transactions[tx_id].status not in ("ACTIVE", "BLOCKED"):
            return f"ERROR:TRANSACTION_INACTIVE tx={tx_id}"
        key = int(key)
        tx = self.transactions[tx_id]

        if key in self.keys:
            return f"ERROR:DUPLICATE_KEY key={key}"

        gap = self._find_gap_for_key(key)

        # Check if any OTHER active transaction holds a gap lock on this gap
        blocking_tx_id = None
        for other_id, other_tx in self.transactions.items():
            if other_id != tx_id and other_tx.status in ("ACTIVE", "BLOCKED"):
                if gap in other_tx.gap_locks:
                    blocking_tx_id = other_id
                    break

        if blocking_tx_id:
            # Check for deadlock
            if self._check_deadlock(tx_id, blocking_tx_id):
                # Deadlock detected! tx_id is the victim
                self.deadlock_count += 1
                self._rollback_tx(tx_id)
                res = [f"ERROR:DEADLOCK_DETECTED victim={tx_id} rollback=TRUE"]
                # Rollback of victim might unblock others
                unblocked_logs = self._wake_up_waiters()
                res.extend(unblocked_logs)
                return "\n".join(res)
            else:
                # Lock wait
                tx.status = "BLOCKED"
                tx.waiting_for = blocking_tx_id
                tx.waiting_gap = gap
                tx.pending_insert_key = key
                return f"STATUS:LOCK_WAIT tx={tx_id} waiting_for={blocking_tx_id} on_gap={gap_str(*gap)}"
        else:
            # Insert succeeds
            self.keys.append(key)
            self.keys.sort()
            tx.inserted_keys.add(key)
            return f"STATUS:INSERTED tx={tx_id} key={key}"

    def _rollback_tx(self, tx_id):
        tx = self.transactions[tx_id]
        tx.status = "ROLLEDBACK"
        tx.gap_locks.clear()
        tx.rec_locks.clear()
        tx.waiting_for = None
        tx.waiting_gap = None
        tx.pending_insert_key = None
        # Remove inserted keys
        for k in tx.inserted_keys:
            if k in self.keys:
                self.keys.remove(k)
        tx.inserted_keys.clear()

    def _wake_up_waiters(self):
        logs = []
        progress = True
        while progress:
            progress = False
            for t_id, t in list(self.transactions.items()):
                if t.status == "BLOCKED":
                    gap = self._find_gap_for_key(t.pending_insert_key)
                    # Check if still blocked
                    still_blocked = False
                    for o_id, o_tx in self.transactions.items():
                        if o_id != t_id and o_tx.status in ("ACTIVE", "BLOCKED"):
                            if gap in o_tx.gap_locks:
                                still_blocked = True
                                t.waiting_for = o_id
                                break
                    if not still_blocked:
                        # Can now insert!
                        key = t.pending_insert_key
                        self.keys.append(key)
                        self.keys.sort()
                        t.inserted_keys.add(key)
                        t.status = "ACTIVE"
                        t.waiting_for = None
                        t.waiting_gap = None
                        t.pending_insert_key = None
                        logs.append(f"STATUS:UNBLOCKED_INSERTED tx={t_id} key={key}")
                        progress = True
                        break
        return logs

    def commit(self, tx_id):
        if tx_id not in self.transactions or self.transactions[tx_id].status not in ("ACTIVE", "BLOCKED"):
            return f"ERROR:TRANSACTION_INACTIVE tx={tx_id}"
        tx = self.transactions[tx_id]
        tx.status = "COMMITTED"
        released_count = len(tx.gap_locks) + len(tx.rec_locks)
        tx.gap_locks.clear()
        tx.rec_locks.clear()
        tx.waiting_for = None

        unblocked_logs = self._wake_up_waiters()
        res = [f"COMMIT_OK tx={tx_id} released_locks={released_count}"]
        res.extend(unblocked_logs)
        return "\n".join(res)

    def rollback(self, tx_id):
        if tx_id not in self.transactions or self.transactions[tx_id].status not in ("ACTIVE", "BLOCKED"):
            return f"ERROR:TRANSACTION_INACTIVE tx={tx_id}"
        self._rollback_tx(tx_id)
        unblocked_logs = self._wake_up_waiters()
        res = [f"ROLLBACK_OK tx={tx_id}"]
        res.extend(unblocked_logs)
        return "\n".join(res)

    def stats(self):
        active_cnt = sum(1 for t in self.transactions.values() if t.status in ("ACTIVE", "BLOCKED"))
        blocked_cnt = sum(1 for t in self.transactions.values() if t.status == "BLOCKED")
        keys_repr = ", ".join(str(k) for k in self.keys)
        return f"STATS keys=[{keys_repr}] active_txs={active_cnt} blocked_txs={blocked_cnt} deadlocks={self.deadlock_count}"

def main():
    mgr = LockManager()
    lines = sys.stdin.read().splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        cmd = parts[0].upper()

        if cmd == "INIT":
            keys = [int(x.strip()) for x in parts[1].split(',') if x.strip()]
            print(mgr.init_table(keys))
        elif cmd == "BEGIN":
            tx_id = parts[1]
            iso = parts[2]
            print(mgr.begin(tx_id, iso))
        elif cmd == "SELECT_FOR_UPDATE":
            tx_id = parts[1]
            args = parts[2:]
            print(mgr.select_for_update(tx_id, *args))
        elif cmd == "INSERT":
            tx_id = parts[1]
            key = parts[2]
            print(mgr.insert(tx_id, key))
        elif cmd == "COMMIT":
            tx_id = parts[1]
            print(mgr.commit(tx_id))
        elif cmd == "ROLLBACK":
            tx_id = parts[1]
            print(mgr.rollback(tx_id))
        elif cmd == "STATS":
            print(mgr.stats())

if __name__ == '__main__':
    main()
