# scratch/sim_182.py
import json
import sys
from typing import Dict, List, Any, Optional, Set, Tuple

class BPlusNode:
    def __init__(self, node_id: str, is_leaf: bool, max_keys: int = 3):
        self.node_id = node_id
        self.is_leaf = is_leaf
        self.max_keys = max_keys
        self.keys: List[int] = []
        self.children: List[str] = []   # Child node_ids for internal nodes
        self.values: List[str] = []     # Values for leaf nodes
        self.next_leaf: Optional[str] = None

    def is_safe_insert(self) -> bool:
        return len(self.keys) < self.max_keys

class BPlusTree:
    def __init__(self, max_keys: int = 3):
        self.max_keys = max_keys
        self.root_id = "node_0"
        self.nodes: Dict[str, BPlusNode] = {
            "node_0": BPlusNode("node_0", is_leaf=True, max_keys=max_keys)
        }
        self.next_node_seq = 1

    def new_node(self, is_leaf: bool) -> BPlusNode:
        nid = f"node_{self.next_node_seq}"
        self.next_node_seq += 1
        node = BPlusNode(nid, is_leaf=is_leaf, max_keys=self.max_keys)
        self.nodes[nid] = node
        return node

    def get_child_id(self, node_id: str, key: int) -> str:
        node = self.nodes[node_id]
        idx = 0
        while idx < len(node.keys) and key >= node.keys[idx]:
            idx += 1
        return node.children[idx]

    def get_depth(self) -> int:
        depth = 1
        curr = self.nodes[self.root_id]
        while not curr.is_leaf:
            depth += 1
            curr = self.nodes[curr.children[0]]
        return depth

class LatchManager:
    def __init__(self):
        # node_id -> {"S": set of thread_ids, "X": Optional[thread_id]}
        self.latches: Dict[str, Dict[str, Any]] = {}
        self.global_latch: Optional[str] = None

    def get_state(self, node_id: str) -> Dict[str, Any]:
        if node_id not in self.latches:
            self.latches[node_id] = {"S": set(), "X": None}
        return self.latches[node_id]

    def try_acquire_s(self, node_id: str, thread_id: str) -> bool:
        st = self.get_state(node_id)
        if st["X"] is not None and st["X"] != thread_id:
            return False
        st["S"].add(thread_id)
        return True

    def release_s(self, node_id: str, thread_id: str):
        st = self.get_state(node_id)
        st["S"].discard(thread_id)

    def try_acquire_x(self, node_id: str, thread_id: str) -> bool:
        st = self.get_state(node_id)
        if st["X"] is not None and st["X"] != thread_id:
            return False
        other_s = st["S"] - {thread_id}
        if len(other_s) > 0:
            return False
        st["X"] = thread_id
        return True

    def release_x(self, node_id: str, thread_id: str):
        st = self.get_state(node_id)
        if st["X"] == thread_id:
            st["X"] = None

class OpTask:
    def __init__(self, op_id: int, op_dict: Dict[str, Any]):
        self.op_id = op_id
        self.thread_id: str = op_dict["thread_id"]
        self.type: str = op_dict["type"] # SEARCH or INSERT
        self.key: int = op_dict["key"]
        self.value: str = op_dict.get("value", "")
        self.time: int = op_dict.get("time", 0)

        self.state: str = "WAITING" # WAITING, IN_FLIGHT, COMPLETED
        self.curr_node_id: Optional[str] = None
        self.held_latches: List[str] = []
        self.result: Optional[str] = None
        self.corrupted: bool = False
        self.start_tick: Optional[int] = None
        self.finish_tick: Optional[int] = None

class LatchCrabbingEngine:
    def __init__(self, data: Dict[str, Any]):
        config = data.get("config", {})
        self.concurrency_mode = config.get("concurrency_mode", "LATCH_CRABBING")
        self.max_keys = config.get("max_keys", 3)
        self.track_trace = config.get("track_trace", False)

        self.tree = BPlusTree(self.max_keys)
        self.latch_mgr = LatchManager()

        # Handle initial pre-populated data if any
        if "initial_data" in config:
            for item in config["initial_data"]:
                self._insert_sequential(item["key"], item["value"])

        self.metrics = {
            "total_reads": 0,
            "total_inserts": 0,
            "read_successes": 0,
            "read_failures": 0,
            "root_splits": 0,
            "early_unlocked_ancestors": 0,
            "latch_contention_events": 0,
            "data_race_corruptions": 0,
            "peak_concurrent_threads": 0,
            "total_ticks": 0,
            "verdict": ""
        }
        self.tasks: List[OpTask] = []
        self.trace: List[Dict[str, Any]] = []

    def _insert_sequential(self, key: int, value: str):
        # Initial deterministic load
        curr_id = self.tree.root_id
        path = []
        while not self.tree.nodes[curr_id].is_leaf:
            path.append(curr_id)
            curr_id = self.tree.get_child_id(curr_id, key)
        path.append(curr_id)

        leaf = self.tree.nodes[curr_id]
        pos = 0
        while pos < len(leaf.keys) and leaf.keys[pos] < key:
            pos += 1
        if pos < len(leaf.keys) and leaf.keys[pos] == key:
            leaf.values[pos] = value
            return
        leaf.keys.insert(pos, key)
        leaf.values.insert(pos, value)

        if len(leaf.keys) > self.max_keys:
            # Split
            mid = len(leaf.keys) // 2
            right_leaf = self.tree.new_node(is_leaf=True)
            right_leaf.keys = leaf.keys[mid:]
            right_leaf.values = leaf.values[mid:]
            right_leaf.next_leaf = leaf.next_leaf
            leaf.keys = leaf.keys[:mid]
            leaf.values = leaf.values[:mid]
            leaf.next_leaf = right_leaf.node_id

            promoted_key = right_leaf.keys[0]
            promoted_child = right_leaf.node_id
            curr_child_id = leaf.node_id
            parent_idx = len(path) - 2

            while parent_idx >= 0:
                parent = self.tree.nodes[path[parent_idx]]
                c_pos = parent.children.index(curr_child_id)
                parent.keys.insert(c_pos, promoted_key)
                parent.children.insert(c_pos + 1, promoted_child)
                if len(parent.keys) <= self.max_keys:
                    promoted_key = None
                    break
                imid = len(parent.keys) // 2
                promoted_key = parent.keys[imid]
                right_int = self.tree.new_node(is_leaf=False)
                right_int.keys = parent.keys[imid + 1:]
                right_int.children = parent.children[imid + 1:]
                parent.keys = parent.keys[:imid]
                parent.children = parent.children[:imid + 1]
                promoted_child = right_int.node_id
                curr_child_id = parent.node_id
                parent_idx -= 1

            if promoted_key is not None:
                new_root = self.tree.new_node(is_leaf=False)
                new_root.keys = [promoted_key]
                new_root.children = [curr_child_id, promoted_child]
                self.tree.root_id = new_root.node_id

    def run_simulation(self, raw_operations: List[Dict[str, Any]]) -> Dict[str, Any]:
        self.tasks = [OpTask(i, op) for i, op in enumerate(raw_operations)]
        tick = 0
        max_ticks = 2000

        while any(t.state != "COMPLETED" for t in self.tasks) and tick < max_ticks:
            ready_tasks = [t for t in self.tasks if t.state != "COMPLETED" and t.time <= tick]

            active_count = len([t for t in ready_tasks if t.state == "IN_FLIGHT" or t.time == tick])
            self.metrics["peak_concurrent_threads"] = max(self.metrics["peak_concurrent_threads"], active_count)

            # In-flight tasks prioritized to free latches quickly, then by arrival time & op_id
            ready_tasks.sort(key=lambda t: (0 if t.state == "IN_FLIGHT" else 1, t.time, t.op_id))

            for task in ready_tasks:
                if task.state == "WAITING":
                    self._start_task(task, tick)
                elif task.state == "IN_FLIGHT":
                    self._advance_task(task, tick)

            tick += 1

        self.metrics["total_ticks"] = tick
        self._finalize_metrics()

        read_results = []
        for t in self.tasks:
            if t.type == "SEARCH":
                read_results.append({
                    "op_id": t.op_id,
                    "thread_id": t.thread_id,
                    "key": t.key,
                    "result": t.result,
                    "corrupted": t.corrupted
                })

        return {
            "status": "SUCCESS",
            "concurrency_mode": self.concurrency_mode,
            "metrics": dict(self.metrics),
            "read_results": read_results,
            "tree_summary": {
                "root_id": self.tree.root_id,
                "total_nodes": len(self.tree.nodes),
                "depth": self.tree.get_depth()
            }
        }

    def _start_task(self, task: OpTask, tick: int):
        task.start_tick = tick
        root_id = self.tree.root_id

        if self.concurrency_mode == "GLOBAL_LATCH":
            if self.latch_mgr.global_latch is not None and self.latch_mgr.global_latch != task.thread_id:
                self.metrics["latch_contention_events"] += 1
                return
            self.latch_mgr.global_latch = task.thread_id
            task.state = "IN_FLIGHT"
            task.curr_node_id = root_id
            self._check_leaf_execution(task, tick)

        elif self.concurrency_mode == "UNSYNCHRONIZED":
            task.state = "IN_FLIGHT"
            task.curr_node_id = root_id
            self._check_leaf_execution(task, tick)

        elif self.concurrency_mode == "LATCH_CRABBING":
            if task.type == "SEARCH":
                ok = self.latch_mgr.try_acquire_s(root_id, task.thread_id)
                if not ok:
                    self.metrics["latch_contention_events"] += 1
                    return
                task.held_latches = [root_id]
                task.curr_node_id = root_id
                task.state = "IN_FLIGHT"
                self._check_leaf_execution(task, tick)

            elif task.type == "INSERT":
                ok = self.latch_mgr.try_acquire_x(root_id, task.thread_id)
                if not ok:
                    self.metrics["latch_contention_events"] += 1
                    return
                task.held_latches = [root_id]
                task.curr_node_id = root_id
                task.state = "IN_FLIGHT"
                self._check_leaf_execution(task, tick)

    def _advance_task(self, task: OpTask, tick: int):
        curr_node = self.tree.nodes[task.curr_node_id]
        if curr_node.is_leaf:
            self._execute_leaf(task, tick)
            return

        child_id = self.tree.get_child_id(task.curr_node_id, task.key)
        child_node = self.tree.nodes[child_id]

        if self.concurrency_mode == "GLOBAL_LATCH":
            task.curr_node_id = child_id
            self._check_leaf_execution(task, tick)

        elif self.concurrency_mode == "UNSYNCHRONIZED":
            task.curr_node_id = child_id
            self._check_leaf_execution(task, tick)

        elif self.concurrency_mode == "LATCH_CRABBING":
            if task.type == "SEARCH":
                ok = self.latch_mgr.try_acquire_s(child_id, task.thread_id)
                if not ok:
                    self.metrics["latch_contention_events"] += 1
                    return
                # S-Latch Crabbing: Release parent S-latch
                self.latch_mgr.release_s(task.curr_node_id, task.thread_id)
                task.held_latches = [child_id]
                task.curr_node_id = child_id
                self._check_leaf_execution(task, tick)

            elif task.type == "INSERT":
                ok = self.latch_mgr.try_acquire_x(child_id, task.thread_id)
                if not ok:
                    self.metrics["latch_contention_events"] += 1
                    return
                task.held_latches.append(child_id)
                task.curr_node_id = child_id

                # Safe Node Optimization!
                if child_node.is_safe_insert():
                    ancestors = task.held_latches[:-1]
                    for anc_id in ancestors:
                        self.latch_mgr.release_x(anc_id, task.thread_id)
                    self.metrics["early_unlocked_ancestors"] += len(ancestors)
                    task.held_latches = [child_id]

                self._check_leaf_execution(task, tick)

    def _check_leaf_execution(self, task: OpTask, tick: int):
        if self.tree.nodes[task.curr_node_id].is_leaf:
            self._execute_leaf(task, tick)

    def _execute_leaf(self, task: OpTask, tick: int):
        leaf = self.tree.nodes[task.curr_node_id]

        if task.type == "SEARCH":
            self.metrics["total_reads"] += 1

            if task.key in leaf.keys:
                idx = leaf.keys.index(task.key)
                task.result = leaf.values[idx]
                self.metrics["read_successes"] += 1
            else:
                task.result = None
                self.metrics["read_failures"] += 1
                if self.concurrency_mode == "UNSYNCHRONIZED":
                    task.corrupted = True
                    self.metrics["data_race_corruptions"] += 1

            if self.concurrency_mode == "GLOBAL_LATCH":
                self.latch_mgr.global_latch = None
            elif self.concurrency_mode == "LATCH_CRABBING":
                for nid in task.held_latches:
                    self.latch_mgr.release_s(nid, task.thread_id)
                task.held_latches = []

            task.state = "COMPLETED"
            task.finish_tick = tick

        elif task.type == "INSERT":
            self.metrics["total_inserts"] += 1
            
            pos = 0
            while pos < len(leaf.keys) and leaf.keys[pos] < task.key:
                pos += 1
            if pos < len(leaf.keys) and leaf.keys[pos] == task.key:
                leaf.values[pos] = task.value
            else:
                leaf.keys.insert(pos, task.key)
                leaf.values.insert(pos, task.value)

            if len(leaf.keys) > self.max_keys:
                self._handle_split(task, leaf)

            if self.concurrency_mode == "GLOBAL_LATCH":
                self.latch_mgr.global_latch = None
            elif self.concurrency_mode == "LATCH_CRABBING":
                for nid in task.held_latches:
                    self.latch_mgr.release_x(nid, task.thread_id)
                task.held_latches = []

            task.state = "COMPLETED"
            task.finish_tick = tick

    def _handle_split(self, task: OpTask, leaf: BPlusNode):
        mid = len(leaf.keys) // 2
        right_leaf = self.tree.new_node(is_leaf=True)
        right_leaf.keys = leaf.keys[mid:]
        right_leaf.values = leaf.values[mid:]
        right_leaf.next_leaf = leaf.next_leaf

        leaf.keys = leaf.keys[:mid]
        leaf.values = leaf.values[:mid]
        leaf.next_leaf = right_leaf.node_id

        promoted_key = right_leaf.keys[0]
        promoted_child = right_leaf.node_id

        if leaf.node_id == self.tree.root_id:
            new_root = self.tree.new_node(is_leaf=False)
            new_root.keys = [promoted_key]
            new_root.children = [leaf.node_id, promoted_child]
            self.tree.root_id = new_root.node_id
            self.metrics["root_splits"] += 1
        else:
            parent_id = None
            if self.concurrency_mode == "LATCH_CRABBING":
                idx = task.held_latches.index(leaf.node_id)
                if idx > 0:
                    parent_id = task.held_latches[idx - 1]
            else:
                for nid, node in self.tree.nodes.items():
                    if leaf.node_id in node.children:
                        parent_id = nid
                        break

            if parent_id:
                parent = self.tree.nodes[parent_id]
                c_pos = parent.children.index(leaf.node_id)
                parent.keys.insert(c_pos, promoted_key)
                parent.children.insert(c_pos + 1, promoted_child)

                if len(parent.keys) > self.max_keys:
                    self._handle_internal_split(task, parent)

    def _handle_internal_split(self, task: OpTask, node: BPlusNode):
        mid = len(node.keys) // 2
        promoted_key = node.keys[mid]

        right_internal = self.tree.new_node(is_leaf=False)
        right_internal.keys = node.keys[mid + 1:]
        right_internal.children = node.children[mid + 1:]

        node.keys = node.keys[:mid]
        node.children = node.children[:mid + 1]

        if node.node_id == self.tree.root_id:
            new_root = self.tree.new_node(is_leaf=False)
            new_root.keys = [promoted_key]
            new_root.children = [node.node_id, right_internal.node_id]
            self.tree.root_id = new_root.node_id
            self.metrics["root_splits"] += 1
        else:
            parent_id = None
            if self.concurrency_mode == "LATCH_CRABBING":
                idx = task.held_latches.index(node.node_id)
                if idx > 0:
                    parent_id = task.held_latches[idx - 1]
            else:
                for nid, n in self.tree.nodes.items():
                    if node.node_id in n.children:
                        parent_id = nid
                        break
            if parent_id:
                parent = self.tree.nodes[parent_id]
                c_pos = parent.children.index(node.node_id)
                parent.keys.insert(c_pos, promoted_key)
                parent.children.insert(c_pos + 1, right_internal.node_id)
                if len(parent.keys) > self.max_keys:
                    self._handle_internal_split(task, parent)

    def _finalize_metrics(self):
        if self.concurrency_mode == "UNSYNCHRONIZED" and self.metrics["data_race_corruptions"] > 0:
            self.metrics["verdict"] = "UNSYNCHRONIZED_DATA_RACE_CORRUPTION"
        elif self.concurrency_mode == "GLOBAL_LATCH" and self.metrics["latch_contention_events"] > 0:
            self.metrics["verdict"] = "GLOBAL_LATCH_SERIALIZATION_BOTTLENECK"
        elif self.metrics["root_splits"] > 0 and self.concurrency_mode == "LATCH_CRABBING":
            self.metrics["verdict"] = "ROOT_NODE_SPLIT_SAFE_UPGRADE"
        elif self.concurrency_mode == "LATCH_CRABBING" and (self.metrics["early_unlocked_ancestors"] > 0 or self.metrics["peak_concurrent_threads"] > 1):
            self.metrics["verdict"] = "LATCH_CRABBING_CONCURRENT_SUCCESS"
        else:
            self.metrics["verdict"] = "STANDARD_OPERATION"

def solve(data: Dict[str, Any]) -> Dict[str, Any]:
    engine = LatchCrabbingEngine(data)
    operations = data.get("operations", [])
    return engine.run_simulation(operations)

def main():
    raw_data = sys.stdin.read().strip()
    if not raw_data:
        return
    req = json.loads(raw_data)
    res = solve(req)
    print(json.dumps(res, indent=2))

if __name__ == "__main__":
    main()
