import sys
import json

# Windows 콘솔 UTF-8 입출력 호환성 보장
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

class MapleNode:
    def __init__(self, is_leaf: bool, capacity: int = 4):
        self.is_leaf = is_leaf
        self.capacity = capacity
        self.pivots = []
        self.slots = []

class MapleTreeEngine:
    def __init__(self, max_capacity: int = 4):
        self.max_capacity = max(2, max_capacity)
        self.root = MapleNode(is_leaf=True, capacity=self.max_capacity)
        self.vma_table = {}
        self.total_stores = 0
        self.total_erases = 0
        self.total_lookups = 0
        self.rcu_reads_count = 0

    def _normalize_intervals(self):
        sorted_keys = sorted(self.vma_table.keys(), key=lambda x: x[0])
        return [(k, self.vma_table[k]) for k in sorted_keys]

    def store_vma(self, start: int, end: int, vma_id: str, flags: list = None, name: str = ""):
        if flags is None:
            flags = ["READ", "WRITE"]
        if start > end:
            return {"status": "ERROR_INVALID_RANGE", "start": start, "end": end}

        new_table = {}
        for (s, e), v in self.vma_table.items():
            if e < start or s > end:
                new_table[(s, e)] = v
            else:
                if s < start:
                    new_table[(s, start - 1)] = {
                        "vma_id": v["vma_id"],
                        "flags": v["flags"],
                        "name": v["name"],
                        "start": s,
                        "end": start - 1
                    }
                if e > end:
                    new_table[(end + 1, e)] = {
                        "vma_id": v["vma_id"],
                        "flags": v["flags"],
                        "name": v["name"],
                        "start": end + 1,
                        "end": e
                    }

        new_vma = {
            "vma_id": vma_id,
            "start": start,
            "end": end,
            "flags": flags,
            "name": name,
            "size": end - start + 1
        }
        new_table[(start, end)] = new_vma
        self.vma_table = new_table
        self.total_stores += 1

        self._rebuild_btree()

        return {
            "status": "VMA_STORED",
            "vma_id": vma_id,
            "start": start,
            "end": end,
            "size": end - start + 1
        }

    def erase_vma(self, start: int, end: int):
        if start > end:
            return {"status": "ERROR_INVALID_RANGE", "start": start, "end": end}

        new_table = {}
        erased_count = 0
        bytes_unmapped = 0

        for (s, e), v in self.vma_table.items():
            if e < start or s > end:
                new_table[(s, e)] = v
            else:
                erased_count += 1
                overlap_s = max(s, start)
                overlap_e = min(e, end)
                bytes_unmapped += (overlap_e - overlap_s + 1)

                if s < start:
                    new_table[(s, start - 1)] = {
                        "vma_id": v["vma_id"],
                        "flags": v["flags"],
                        "name": v["name"],
                        "start": s,
                        "end": start - 1
                    }
                if e > end:
                    new_table[(end + 1, e)] = {
                        "vma_id": v["vma_id"],
                        "flags": v["flags"],
                        "name": v["name"],
                        "start": end + 1,
                        "end": e
                    }

        self.vma_table = new_table
        self.total_erases += 1
        self._rebuild_btree()

        return {
            "status": "VMA_ERASED",
            "range": [start, end],
            "affected_vmas": erased_count,
            "bytes_unmapped": bytes_unmapped
        }

    def _rebuild_btree(self):
        intervals = self._normalize_intervals()
        if not intervals:
            self.root = MapleNode(is_leaf=True, capacity=self.max_capacity)
            return

        leaves = []
        curr_leaf = MapleNode(is_leaf=True, capacity=self.max_capacity)
        for (s, e), vma in intervals:
            if len(curr_leaf.slots) >= self.max_capacity:
                leaves.append(curr_leaf)
                curr_leaf = MapleNode(is_leaf=True, capacity=self.max_capacity)
            curr_leaf.pivots.append(e)
            curr_leaf.slots.append(vma)
        if curr_leaf.slots:
            leaves.append(curr_leaf)

        current_level = leaves
        while len(current_level) > 1:
            next_level = []
            curr_branch = MapleNode(is_leaf=False, capacity=self.max_capacity)
            for node in current_level:
                if len(curr_branch.slots) >= self.max_capacity:
                    next_level.append(curr_branch)
                    curr_branch = MapleNode(is_leaf=False, capacity=self.max_capacity)
                max_pivot = node.pivots[-1]
                curr_branch.pivots.append(max_pivot)
                curr_branch.slots.append(node)
            if curr_branch.slots:
                next_level.append(curr_branch)
            current_level = next_level

        self.root = current_level[0]

    def find_vma(self, addr: int):
        self.total_lookups += 1
        curr = self.root
        while not curr.is_leaf:
            found = False
            for i, p in enumerate(curr.pivots):
                if addr <= p:
                    curr = curr.slots[i]
                    found = True
                    break
            if not found:
                curr = curr.slots[-1]

        for vma in curr.slots:
            if vma and vma["start"] <= addr <= vma["end"]:
                return {
                    "status": "FOUND",
                    "addr": addr,
                    "vma": vma
                }

        return {
            "status": "NOT_FOUND",
            "addr": addr,
            "vma": None
        }

    def range_query(self, start: int, end: int):
        self.total_lookups += 1
        results = []
        for (s, e), v in self._normalize_intervals():
            if not (e < start or s > end):
                results.append(v)
        return {
            "status": "RANGE_QUERY_RESULT",
            "range": [start, end],
            "count": len(results),
            "vmas": results
        }

    def rcu_batch_read(self, addrs: list):
        self.rcu_reads_count += len(addrs)
        hits = 0
        read_results = []
        for a in addrs:
            res = self.find_vma(a)
            if res["status"] == "FOUND":
                hits += 1
                read_results.append({"addr": a, "hit": True, "vma_id": res["vma"]["vma_id"]})
            else:
                read_results.append({"addr": a, "hit": False, "vma_id": None})
        return {
            "status": "RCU_BATCH_COMPLETE",
            "total_queries": len(addrs),
            "hits": hits,
            "results": read_results
        }

    def inspect_tree(self):
        intervals = self._normalize_intervals()
        total_mapped = sum(v["end"] - v["start"] + 1 for _, v in intervals)

        def get_stats(node, depth=1):
            nodes = 1
            max_depth = depth
            if not node.is_leaf:
                for child in node.slots:
                    n, d = get_stats(child, depth + 1)
                    nodes += n
                    max_depth = max(max_depth, d)
            return nodes, max_depth

        total_nodes, height = get_stats(self.root)

        return {
            "tree_height": height,
            "node_count": total_nodes,
            "vma_count": len(intervals),
            "total_mapped_bytes": total_mapped,
            "stats": {
                "total_stores": self.total_stores,
                "total_erases": self.total_erases,
                "total_lookups": self.total_lookups,
                "rcu_reads_count": self.rcu_reads_count
            }
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return

    commands = json.loads(raw_input)
    engine = None
    results = []

    for cmd in commands:
        op = cmd.get("op")
        if op == "INIT":
            cap = cmd.get("max_capacity", 4)
            engine = MapleTreeEngine(max_capacity=cap)
            results.append({"op": "INIT", "status": "OK", "max_capacity": cap})
        elif op == "STORE_VMA":
            res = engine.store_vma(cmd["start"], cmd["end"], cmd["vma_id"], cmd.get("flags"), cmd.get("name", ""))
            results.append({"op": "STORE_VMA", "result": res})
        elif op == "FIND_VMA":
            res = engine.find_vma(cmd["addr"])
            results.append({"op": "FIND_VMA", "result": res})
        elif op == "RANGE_QUERY":
            res = engine.range_query(cmd["start"], cmd["end"])
            results.append({"op": "RANGE_QUERY", "result": res})
        elif op == "ERASE_VMA":
            res = engine.erase_vma(cmd["start"], cmd["end"])
            results.append({"op": "ERASE_VMA", "result": res})
        elif op == "RCU_BATCH_READ":
            res = engine.rcu_batch_read(cmd["addrs"])
            results.append({"op": "RCU_BATCH_READ", "result": res})
        elif op == "INSPECT_TREE":
            res = engine.inspect_tree()
            results.append({"op": "INSPECT_TREE", "result": res})
        else:
            results.append({"op": op, "status": "UNKNOWN_OP"})

    print(json.dumps(results, separators=(',', ':')))

if __name__ == "__main__":
    main()
