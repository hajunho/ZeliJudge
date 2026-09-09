import sys
from collections import defaultdict

class InnoDBSimulator:
    def __init__(self, initial_keys):
        self.committed_keys = sorted(list(set(initial_keys)))
        self.active_txs = set()
        self.committed_txs = set()
        self.rolled_back_txs = set()
        
        self.gap_locks = defaultdict(set)
        self.rec_locks = {}
        self.staged_inserts = defaultdict(set)
        
        self.waiting_order = []
        self.waiting_map = {}
        self.deadlocks = 0

    def get_gap(self, key):
        keys = self.committed_keys
        if not keys:
            return (float('-inf'), float('inf'))
        if key < keys[0]:
            return (float('-inf'), keys[0])
        if key > keys[-1]:
            return (keys[-1], float('inf'))
        for i in range(len(keys) - 1):
            if keys[i] < key < keys[i+1]:
                return (keys[i], keys[i+1])
        return None

    def find_cycle(self, start_tx, target_tx, visited=None):
        if visited is None:
            visited = set()
        if start_tx == target_tx:
            return True
        visited.add(start_tx)
        if start_tx in self.waiting_map:
            for next_tx in self.waiting_map[start_tx]['waiting_for']:
                if next_tx not in visited:
                    if self.find_cycle(next_tx, target_tx, visited):
                        return True
                elif next_tx == target_tx:
                    return True
        return False

    def abort_tx(self, tx):
        self.rolled_back_txs.add(tx)
        if tx in self.active_txs:
            self.active_txs.remove(tx)
        if tx in self.waiting_map:
            del self.waiting_map[tx]
            if tx in self.waiting_order:
                self.waiting_order.remove(tx)
        self.release_locks(tx)
        if tx in self.staged_inserts:
            del self.staged_inserts[tx]
        self.process_waiting()

    def release_locks(self, tx):
        empty_gaps = []
        for gap, txs in self.gap_locks.items():
            if tx in txs:
                txs.remove(tx)
                if not txs:
                    empty_gaps.append(gap)
        for g in empty_gaps:
            del self.gap_locks[g]
            
        keys_to_free = [k for k, holder in self.rec_locks.items() if holder == tx]
        for k in keys_to_free:
            del self.rec_locks[k]

    def commit_tx(self, tx):
        if tx not in self.active_txs:
            return
        self.committed_txs.add(tx)
        self.active_txs.remove(tx)
        if tx in self.staged_inserts:
            for k in self.staged_inserts[tx]:
                if k not in self.committed_keys:
                    self.committed_keys.append(k)
            self.committed_keys.sort()
            del self.staged_inserts[tx]
        self.release_locks(tx)
        self.process_waiting()

    def rollback_tx(self, tx):
        if tx not in self.active_txs:
            return
        self.abort_tx(tx)

    def process_waiting(self):
        progress = True
        while progress:
            progress = False
            i = 0
            while i < len(self.waiting_order):
                tx = self.waiting_order[i]
                info = self.waiting_map[tx]
                op = info['op']
                arg = info['arg']
                
                if op == 'INSERT':
                    key = arg
                    gap = self.get_gap(key)
                    conflicting = set()
                    if gap and gap in self.gap_locks:
                        for other in self.gap_locks[gap]:
                            if other != tx:
                                conflicting.add(other)
                    info['waiting_for'] = conflicting
                    if not conflicting:
                        del self.waiting_map[tx]
                        self.waiting_order.pop(i)
                        self.staged_inserts[tx].add(key)
                        self.rec_locks[key] = tx
                        progress = True
                        continue
                elif op in ('SELECT_FOR_UPDATE', 'UPDATE'):
                    key = arg
                    holder = self.rec_locks.get(key)
                    if holder and holder != tx:
                        info['waiting_for'] = {holder}
                    else:
                        info['waiting_for'] = set()
                        del self.waiting_map[tx]
                        self.waiting_order.pop(i)
                        self.rec_locks[key] = tx
                        progress = True
                        continue
                i += 1

    def execute_op(self, line):
        parts = line.strip().split()
        if not parts:
            return
        cmd = parts[0]
        tx = parts[1]
        
        if cmd == 'BEGIN':
            self.active_txs.add(tx)
            return
            
        if tx not in self.active_txs:
            return
            
        if tx in self.waiting_map:
            return

        if cmd == 'COMMIT':
            self.commit_tx(tx)
        elif cmd == 'ROLLBACK':
            self.rollback_tx(tx)
        elif cmd in ('SELECT_FOR_UPDATE', 'UPDATE'):
            key = int(parts[2])
            if key in self.committed_keys or any(key in s for s in self.staged_inserts.values()):
                holder = self.rec_locks.get(key)
                if holder and holder != tx:
                    if self.find_cycle(holder, tx):
                        self.deadlocks += 1
                        self.abort_tx(tx)
                    else:
                        self.waiting_map[tx] = {'op': cmd, 'arg': key, 'waiting_for': {holder}}
                        self.waiting_order.append(tx)
                else:
                    self.rec_locks[key] = tx
            else:
                gap = self.get_gap(key)
                if gap:
                    self.gap_locks[gap].add(tx)
        elif cmd == 'INSERT':
            key = int(parts[2])
            gap = self.get_gap(key)
            conflicting = set()
            if gap and gap in self.gap_locks:
                for other in self.gap_locks[gap]:
                    if other != tx:
                        conflicting.add(other)
            if conflicting:
                is_deadlock = False
                for other in conflicting:
                    if self.find_cycle(other, tx):
                        is_deadlock = True
                        break
                if is_deadlock:
                    self.deadlocks += 1
                    self.abort_tx(tx)
                else:
                    self.waiting_map[tx] = {'op': 'INSERT', 'arg': key, 'waiting_for': conflicting}
                    self.waiting_order.append(tx)
            else:
                self.staged_inserts[tx].add(key)
                self.rec_locks[key] = tx

def solve():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    k = int(lines[0].strip())
    line_idx = 1
    if k > 0:
        initial_keys = list(map(int, lines[line_idx].strip().split()))
        line_idx += 1
    else:
        initial_keys = []
        line_idx += 1
        
    m = int(lines[line_idx].strip())
    line_idx += 1
    
    sim = InnoDBSimulator(initial_keys)
    for _ in range(m):
        if line_idx < len(lines):
            sim.execute_op(lines[line_idx])
            line_idx += 1
            
    rows_str = ",".join(map(str, sim.committed_keys)) if sim.committed_keys else "EMPTY"
    print(f"COMMITTED: {len(sim.committed_txs)} ROLLED_BACK: {len(sim.rolled_back_txs)} DEADLOCKS: {sim.deadlocks} ROWS: {rows_str}")

if __name__ == '__main__':
    solve()
