import sys
import json

class RpsRfsEngine:
    def __init__(self, config):
        self.num_cpus = config.get("num_cpus", 4)
        self.netdev_max_backlog = config.get("netdev_max_backlog", 100)
        self.napi_weight = config.get("napi_weight", 64)
        self.rps_cpus = config.get("rps_cpus", list(range(self.num_cpus)))
        self.rfs_enabled = config.get("rfs_enabled", True)
        
        self.backlogs = {c: [] for c in range(self.num_cpus)}
        self.cpu_enqueued = {c: 0 for c in range(self.num_cpus)}
        self.cpu_processed = {c: 0 for c in range(self.num_cpus)}
        
        self.sock_flow_table = {}
        self.dev_flow_table = {}
        
        self.stats = {
            "total_steered_rps": 0,
            "total_steered_rfs": 0,
            "total_dropped_backlog": 0,
            "total_napi_processed": 0
        }

    def app_socket_recv(self, flow_hash, app_cpu):
        self.sock_flow_table[flow_hash] = app_cpu
        return {"status": "SOCK_FLOW_UPDATED", "flow_hash": flow_hash, "app_cpu": app_cpu}

    def ingress_packet(self, pkt_id, time_us, flow_hash, length=64):
        target_cpu = None
        method = "RPS"

        if self.rfs_enabled and flow_hash in self.sock_flow_table:
            desired_cpu = self.sock_flow_table[flow_hash]
            if flow_hash not in self.dev_flow_table:
                self.dev_flow_table[flow_hash] = {"cpu": desired_cpu, "last_qtail": 0}
                target_cpu = desired_cpu
                method = "RFS"
            else:
                curr_dev_flow = self.dev_flow_table[flow_hash]
                old_cpu = curr_dev_flow["cpu"]
                if desired_cpu == old_cpu:
                    target_cpu = desired_cpu
                    method = "RFS"
                else:
                    if self.cpu_processed[old_cpu] >= curr_dev_flow["last_qtail"]:
                        curr_dev_flow["cpu"] = desired_cpu
                        target_cpu = desired_cpu
                        method = "RFS"
                    else:
                        target_cpu = old_cpu
                        method = "RFS_DRAIN_HOLD"
        else:
            target_cpu = self.rps_cpus[flow_hash % len(self.rps_cpus)]
            method = "RPS"

        queue = self.backlogs[target_cpu]
        if len(queue) < self.netdev_max_backlog:
            queue.append({"pkt_id": pkt_id, "time_us": time_us, "len": length, "flow_hash": flow_hash})
            self.cpu_enqueued[target_cpu] += 1
            if flow_hash in self.dev_flow_table and self.dev_flow_table[flow_hash]["cpu"] == target_cpu:
                self.dev_flow_table[flow_hash]["last_qtail"] = self.cpu_enqueued[target_cpu]
            
            if "RFS" in method:
                self.stats["total_steered_rfs"] += 1
            else:
                self.stats["total_steered_rps"] += 1

            return {
                "status": "STEERED",
                "pkt_id": pkt_id,
                "target_cpu": target_cpu,
                "method": method,
                "backlog_len": len(queue)
            }
        else:
            self.stats["total_dropped_backlog"] += 1
            return {
                "status": "DROPPED_BACKLOG_FULL",
                "pkt_id": pkt_id,
                "target_cpu": target_cpu
            }

    def process_napi_softirq(self, cpu_id, budget=None):
        if budget is None:
            budget = self.napi_weight

        queue = self.backlogs[cpu_id]
        processed = 0
        while queue and processed < budget:
            queue.pop(0)
            processed += 1

        self.cpu_processed[cpu_id] += processed
        self.stats["total_napi_processed"] += processed

        return {
            "status": "NAPI_PROCESSED",
            "cpu_id": cpu_id,
            "processed_count": processed,
            "remaining_backlog": len(queue)
        }

    def query_stats(self):
        return {
            "total_steered_rps": self.stats["total_steered_rps"],
            "total_steered_rfs": self.stats["total_steered_rfs"],
            "total_dropped_backlog": self.stats["total_dropped_backlog"],
            "total_napi_processed": self.stats["total_napi_processed"],
            "per_cpu_backlog": {str(c): len(self.backlogs[c]) for c in range(self.num_cpus)},
            "per_cpu_processed": {str(c): self.cpu_processed[c] for c in range(self.num_cpus)}
        }

def solve():
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    raw = sys.stdin.read().strip()
    if not raw:
        return

    input_data = json.loads(raw)
    engine = RpsRfsEngine(input_data.get("config", {}))
    results = []

    for op in input_data.get("operations", []):
        cmd = op.get("op")
        if cmd == "APP_SOCKET_RECV":
            res = engine.app_socket_recv(op["flow_hash"], op["app_cpu"])
            results.append(res)
        elif cmd == "INGRESS_PACKET":
            res = engine.ingress_packet(op["pkt_id"], op["time_us"], op["flow_hash"], op.get("len", 64))
            results.append(res)
        elif cmd == "PROCESS_NAPI":
            res = engine.process_napi_softirq(op["cpu_id"], op.get("budget"))
            results.append(res)
        elif cmd == "QUERY_STATS":
            res = engine.query_stats()
            results.append(res)

    out_obj = {"results": results}
    print(json.dumps(out_obj, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    solve()
