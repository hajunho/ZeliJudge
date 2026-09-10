import sys
import json

class AutoNumaEngine:
    def __init__(self, config=None):
        config = config or {}
        self.local_latency = config.get("local_latency", 30.0)
        self.remote_latency = config.get("remote_latency", 90.0)
        self.page_migration_threshold = config.get("page_migration_threshold", 2)
        self.task_swap_threshold = config.get("task_swap_threshold", 0.6)
        self.interconnect_saturation_limit = config.get("interconnect_saturation_limit", 1000)

        self.tasks = {}
        self.pages = {}

        self.total_latency_ns = 0.0
        self.local_accesses = 0
        self.remote_accesses = 0
        self.hinting_faults = 0
        self.page_migrations = 0
        self.task_swaps = 0

    def register_task(self, task_id, cpu_node, page_ids, page_initial_nodes):
        self.tasks[task_id] = {
            "task_id": task_id,
            "cpu_node": cpu_node,
            "pages": page_ids,
            "numa_faults": {0: 0, 1: 0},
            "recent_remote_accesses": {}
        }
        for pid, pnode in zip(page_ids, page_initial_nodes):
            if pid not in self.pages:
                self.pages[pid] = {
                    "page_id": pid,
                    "node": pnode,
                    "armed_hinting": False,
                    "access_counts": {0: 0, 1: 0}
                }

    def arm_scan(self, task_id, page_ids=None):
        task = self.tasks.get(task_id)
        if not task: return
        target_pages = page_ids if page_ids else task["pages"]
        for pid in target_pages:
            if pid in self.pages:
                self.pages[pid]["armed_hinting"] = True

    def access(self, task_id, page_id):
        task = self.tasks[task_id]
        page = self.pages[page_id]
        cpu_node = task["cpu_node"]
        page_node = page["node"]

        is_local = (cpu_node == page_node)
        cost = self.local_latency if is_local else self.remote_latency
        self.total_latency_ns += cost

        if is_local:
            self.local_accesses += 1
        else:
            self.remote_accesses += 1

        page["access_counts"][cpu_node] += 1

        fault_triggered = False
        migrated_page = False
        if page["armed_hinting"]:
            self.hinting_faults += 1
            page["armed_hinting"] = False
            fault_triggered = True
            task["numa_faults"][page_node] += 1

            if not is_local:
                rem_count = task["recent_remote_accesses"].get(page_id, 0) + 1
                task["recent_remote_accesses"][page_id] = rem_count
                if rem_count >= self.page_migration_threshold:
                    page["node"] = cpu_node
                    self.page_migrations += 1
                    migrated_page = True
                    task["recent_remote_accesses"][page_id] = 0

        return {
            "task": task_id,
            "page": page_id,
            "is_local": is_local,
            "latency_ns": cost,
            "hinting_fault": fault_triggered,
            "page_migrated_to_node": cpu_node if migrated_page else None
        }

    def evaluate_task_placement(self, task_a_id, task_b_id=None):
        task_a = self.tasks[task_a_id]
        node_a = task_a["cpu_node"]

        if not task_b_id:
            total_faults = sum(task_a["numa_faults"].values())
            if total_faults > 0:
                remote_node = 1 - node_a
                remote_ratio = task_a["numa_faults"][remote_node] / total_faults
                if remote_ratio >= self.task_swap_threshold:
                    task_a["cpu_node"] = remote_node
                    self.task_swaps += 1
                    return {"action": "TASK_MIGRATED", "task": task_a_id, "new_node": remote_node}
            return {"action": "NOOP"}

        task_b = self.tasks[task_b_id]
        node_b = task_b["cpu_node"]

        if node_a != node_b:
            fa_b = task_a["numa_faults"].get(node_b, 0)
            fa_a = task_a["numa_faults"].get(node_a, 0)
            fb_a = task_b["numa_faults"].get(node_a, 0)
            fb_b = task_b["numa_faults"].get(node_b, 0)

            if fa_b > fa_a and fb_a > fb_b:
                task_a["cpu_node"] = node_b
                task_b["cpu_node"] = node_a
                self.task_swaps += 1
                return {"action": "TASKS_SWAPPED", "task_a": task_a_id, "task_b": task_b_id}

        return {"action": "NOOP"}

    def get_metrics(self):
        total_acc = self.local_accesses + self.remote_accesses
        local_ratio = round((self.local_accesses / total_acc * 100.0), 2) if total_acc > 0 else 100.0
        avg_latency = round((self.total_latency_ns / total_acc), 2) if total_acc > 0 else 0.0

        task_states = {}
        for tid, t in self.tasks.items():
            task_states[tid] = {
                "cpu_node": t["cpu_node"],
                "numa_faults": t["numa_faults"]
            }

        page_states = {}
        for pid, p in self.pages.items():
            page_states[pid] = {
                "current_node": p["node"]
            }

        return {
            "total_accesses": total_acc,
            "local_accesses": self.local_accesses,
            "remote_accesses": self.remote_accesses,
            "local_access_ratio_pct": local_ratio,
            "average_latency_ns": avg_latency,
            "hinting_faults_count": self.hinting_faults,
            "page_migrations_count": self.page_migrations,
            "task_swaps_count": self.task_swaps,
            "tasks": task_states,
            "pages": page_states
        }

def main():
    raw = sys.stdin.read()
    if not raw.strip():
        return

    data = json.loads(raw)
    config = data.get("config", {})
    engine = AutoNumaEngine(config)

    for task_init in data.get("initial_tasks", []):
        engine.register_task(
            task_id=task_init["task_id"],
            cpu_node=task_init["cpu_node"],
            page_ids=task_init["pages"],
            page_initial_nodes=task_init["page_initial_nodes"]
        )

    history = []
    for op in data.get("operations", []):
        op_type = op.get("op")
        if op_type == "ARM_SCAN":
            engine.arm_scan(op.get("task_id"), op.get("page_ids"))
            history.append({"op": "ARM_SCAN", "task_id": op.get("task_id")})
        elif op_type == "ACCESS":
            res = engine.access(op.get("task_id"), op.get("page_id"))
            history.append(res)
        elif op_type == "EVALUATE_PLACEMENT":
            res = engine.evaluate_task_placement(op.get("task_a"), op.get("task_b"))
            history.append(res)

    metrics = engine.get_metrics()
    output = {
        "operations_count": len(history),
        "history": history,
        "metrics": metrics
    }
    print(json.dumps(output, ensure_ascii=False))

if __name__ == "__main__":
    main()
