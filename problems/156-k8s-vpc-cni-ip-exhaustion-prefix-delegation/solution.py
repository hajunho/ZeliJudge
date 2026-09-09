import json
import sys

INSTANCE_SPECS = {
    "t3.medium": {"max_enis": 3, "ips_per_eni": 6},
    "m5.large": {"max_enis": 3, "ips_per_eni": 10},
    "c5.xlarge": {"max_enis": 4, "ips_per_eni": 15},
    "m5.2xlarge": {"max_enis": 4, "ips_per_eni": 30}
}

class NodeCNI:
    def __init__(self, node_id, instance_type, cni_mode, warm_ip_target):
        self.node_id = node_id
        self.instance_type = instance_type
        self.spec = INSTANCE_SPECS[instance_type]
        self.max_enis = self.spec["max_enis"]
        self.ips_per_eni = self.spec["ips_per_eni"]
        self.cni_mode = cni_mode
        self.warm_ip_target = warm_ip_target

        self.attached_enis = 1 # Primary ENI attached at boot
        self.total_ip_slots = (self.ips_per_eni - 1)
        self.allocated_ips = 0
        self.used_ips = 0
        self.active_pods = {}

class VPCClusterSimulator:
    def __init__(self, config):
        self.cni_mode = config.get("cni_mode", "ON_DEMAND")
        self.warm_ip_target = int(config.get("warm_ip_target", 0))
        self.subnet_ips = int(config.get("subnet_available_ips", 100))
        self.delays = config.get("delays", {})
        self.eni_attach_ms = float(self.delays.get("eni_attach_ms", 3000))
        self.ip_assign_ms = float(self.delays.get("ip_assign_ms", 500))
        self.throttle_penalty_ms = float(self.delays.get("api_throttle_penalty_ms", 5000))
        self.rate_limit_per_sec = int(self.delays.get("api_rate_limit_per_second", 5))

        self.nodes = {}
        for n in config.get("nodes", []):
            nid = n["node_id"]
            itype = n["instance_type"]
            self.nodes[nid] = NodeCNI(nid, itype, self.cni_mode, self.warm_ip_target)

        self.api_call_timestamps = []
        self.total_api_calls = 0
        self.throttled_calls = 0
        self.eni_attach_calls = 0

    def _call_ec2_api(self, current_time, is_eni_attach=False):
        self.total_api_calls += 1
        if is_eni_attach:
            self.eni_attach_calls += 1

        recent_calls = [t for t in self.api_call_timestamps if current_time - t < 1000.0]
        base_delay = self.eni_attach_ms if is_eni_attach else self.ip_assign_ms

        if len(recent_calls) >= self.rate_limit_per_sec:
            self.throttled_calls += 1
            delay = base_delay + self.throttle_penalty_ms
        else:
            delay = base_delay

        self.api_call_timestamps.append(current_time)
        return delay

    def warm_up(self):
        if self.cni_mode == "WARM_IP":
            for node in self.nodes.values():
                needed = self.warm_ip_target - (node.allocated_ips - node.used_ips)
                while needed > 0 and self.subnet_ips > 0:
                    free_slots = node.total_ip_slots - node.allocated_ips
                    if free_slots <= 0 and node.attached_enis < node.max_enis:
                        node.attached_enis += 1
                        node.total_ip_slots += (node.ips_per_eni - 1)
                        self._call_ec2_api(0, is_eni_attach=True)
                    
                    can_grab = min(needed, node.total_ip_slots - node.allocated_ips, self.subnet_ips)
                    if can_grab <= 0:
                        break
                    node.allocated_ips += can_grab
                    self.subnet_ips -= can_grab
                    self._call_ec2_api(0, is_eni_attach=False)
                    needed = self.warm_ip_target - (node.allocated_ips - node.used_ips)

        elif self.cni_mode == "PREFIX_DELEGATION":
            for node in self.nodes.values():
                if self.subnet_ips >= 16:
                    node.allocated_ips += 16
                    self.subnet_ips -= 16
                    self._call_ec2_api(0, is_eni_attach=False)

    def run_events(self, events):
        self.warm_up()
        pod_results = {}
        failed_pods = []

        for ev in events:
            t = float(ev["time_ms"])
            act = ev["action"]
            pid = ev["pod_id"]

            if act == "SCHEDULE":
                nid = ev["node_id"]
                node = self.nodes[nid]
                free_warm_ips = node.allocated_ips - node.used_ips

                if free_warm_ips > 0:
                    node.used_ips += 1
                    node.active_pods[pid] = "WARM_POOL"
                    pod_results[pid] = {
                        "scheduled_at_ms": t,
                        "ready_at_ms": t,
                        "latency_ms": 0.0,
                        "status": "RUNNING"
                    }
                else:
                    if self.cni_mode == "PREFIX_DELEGATION":
                        if self.subnet_ips < 16:
                            failed_pods.append((pid, "SubnetIPExhausted"))
                            pod_results[pid] = {"scheduled_at_ms": t, "ready_at_ms": None, "latency_ms": None, "status": "FAILED_SUBNET_EXHAUSTED"}
                            continue
                        delay = self._call_ec2_api(t, is_eni_attach=False)
                        node.allocated_ips += 16
                        self.subnet_ips -= 16
                        node.used_ips += 1
                        node.active_pods[pid] = "PREFIX"
                        pod_results[pid] = {
                            "scheduled_at_ms": t,
                            "ready_at_ms": t + delay,
                            "latency_ms": delay,
                            "status": "RUNNING"
                        }
                    else:
                        if self.subnet_ips < 1:
                            failed_pods.append((pid, "SubnetIPExhausted"))
                            pod_results[pid] = {"scheduled_at_ms": t, "ready_at_ms": None, "latency_ms": None, "status": "FAILED_SUBNET_EXHAUSTED"}
                            continue
                        
                        free_slots = node.total_ip_slots - node.allocated_ips
                        total_delay = 0.0
                        if free_slots <= 0:
                            if node.attached_enis < node.max_enis:
                                delay_eni = self._call_ec2_api(t, is_eni_attach=True)
                                node.attached_enis += 1
                                node.total_ip_slots += (node.ips_per_eni - 1)
                                total_delay += delay_eni
                            else:
                                failed_pods.append((pid, "NodeCapacityExceeded"))
                                pod_results[pid] = {"scheduled_at_ms": t, "ready_at_ms": None, "latency_ms": None, "status": "FAILED_NODE_CAPACITY"}
                                continue
                        
                        delay_ip = self._call_ec2_api(t + total_delay, is_eni_attach=False)
                        total_delay += delay_ip
                        node.allocated_ips += 1
                        self.subnet_ips -= 1
                        node.used_ips += 1
                        node.active_pods[pid] = "ON_DEMAND"
                        pod_results[pid] = {
                            "scheduled_at_ms": t,
                            "ready_at_ms": t + total_delay,
                            "latency_ms": total_delay,
                            "status": "RUNNING"
                        }

            elif act == "TERMINATE":
                for node in self.nodes.values():
                    if pid in node.active_pods:
                        del node.active_pods[pid]
                        node.used_ips -= 1
                        break

        running_latencies = [p["latency_ms"] for p in pod_results.values() if p["status"] == "RUNNING"]
        avg_latency = sum(running_latencies) / len(running_latencies) if running_latencies else 0.0
        max_latency = max(running_latencies) if running_latencies else 0.0
        running_latencies.sort()
        p95_idx = int(len(running_latencies) * 0.95)
        p95_latency = running_latencies[min(p95_idx, len(running_latencies)-1)] if running_latencies else 0.0

        if failed_pods:
            subnet_errs = [f for f in failed_pods if f[1] == "SubnetIPExhausted"]
            node_errs = [f for f in failed_pods if f[1] == "NodeCapacityExceeded"]
            if subnet_errs:
                diag = f"CRITICAL: Subnet CIDR IP exhaustion! {len(subnet_errs)} pods failed to schedule because the VPC subnet has no remaining IP addresses."
            else:
                diag = f"CRITICAL: Node ENI capacity limit reached! {len(node_errs)} pods failed because node instance type exceeded maximum ENIs and secondary IPs."
        else:
            if self.cni_mode == "ON_DEMAND":
                if self.throttled_calls > 0:
                    diag = f"CRITICAL: EC2 API rate limit exceeded ({self.throttled_calls} throttled calls). Pods suffered provisioning delays up to {max_latency:.1f}ms due to on-demand ENI/IP allocation."
                elif max_latency > 0:
                    diag = f"WARNING: On-demand IP allocation caused pod startup latency of {max_latency:.1f}ms. Consider WARM_IP_TARGET or Prefix Delegation."
                else:
                    diag = "ON_DEMAND allocation succeeded without delay."
            elif self.cni_mode == "WARM_IP":
                diag = f"WARM_IP_TARGET maintained warm buffer. Pods scheduled with average latency {avg_latency:.1f}ms ({self.throttled_calls} throttled API calls)."
            else:
                diag = "OPTIMAL: AWS VPC CNI Prefix Delegation achieved zero-delay pod provisioning and minimal EC2 API overhead via /28 prefix blocks."

        return {
            "cni_mode": self.cni_mode,
            "total_pods_requested": len([e for e in events if e["action"] == "SCHEDULE"]),
            "running_pods": len(running_latencies),
            "failed_pods": len(failed_pods),
            "remaining_subnet_ips": self.subnet_ips,
            "metrics": {
                "total_api_calls": self.total_api_calls,
                "throttled_calls": self.throttled_calls,
                "eni_attach_calls": self.eni_attach_calls,
                "avg_provisioning_latency_ms": round(avg_latency, 1),
                "max_provisioning_latency_ms": round(max_latency, 1),
                "p95_provisioning_latency_ms": round(p95_latency, 1)
            },
            "diagnosis": diag
        }

def solve(input_data):
    sim = VPCClusterSimulator(input_data)
    return sim.run_events(input_data.get("events", []))

if __name__ == "__main__":
    raw = sys.stdin.read().strip()
    if raw:
        inp = json.loads(raw)
        res = solve(inp)
        print(json.dumps(res, indent=2))
