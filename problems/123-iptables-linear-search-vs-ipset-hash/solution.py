import sys
import json

class PacketFilterSimulator:
    def __init__(self):
        self.reset()

    def reset(self):
        self.mode = "IPTABLES"
        self.rules = [] # list of (target, src_ip)
        self.ipset_entries = set() # set of src_ip

        self.total_packets = 0
        self.accepted_packets = 0
        self.dropped_packets = 0
        self.total_evaluations = 0

    def config(self, mode=None):
        if mode:
            self.mode = mode
        return f"OK mode={self.mode}"

    def add_rule(self, target, src_ip):
        if self.mode == "IPTABLES":
            self.rules.append((target, src_ip))
            idx = len(self.rules) - 1
            return f"RULE_ADDED mode=IPTABLES rule_index={idx} target={target} src={src_ip}"
        else: # IPSET
            self.ipset_entries.add(src_ip)
            return f"IPSET_ENTRY_ADDED mode=IPSET set_size={len(self.ipset_entries)} target={target} src={src_ip}"

    def process_packet(self, src_ip):
        self.total_packets += 1
        evaluations = 0

        if self.mode == "IPTABLES":
            action = "ACCEPTED"
            for target, rule_ip in self.rules:
                evaluations += 1
                if rule_ip == src_ip:
                    action = "DROPPED" if target == "DROP" else "ACCEPTED"
                    break
            self.total_evaluations += evaluations
            if action == "ACCEPTED":
                self.accepted_packets += 1
            else:
                self.dropped_packets += 1
            return f"PACKET_RESULT src={src_ip} action={action} evaluations={evaluations} latency_us={evaluations}"

        else: # IPSET
            evaluations = 1 # O(1) hash lookup
            self.total_evaluations += 1
            if src_ip in self.ipset_entries:
                action = "DROPPED"
                self.dropped_packets += 1
            else:
                action = "ACCEPTED"
                self.accepted_packets += 1
            return f"PACKET_RESULT src={src_ip} action={action} evaluations=1 latency_us=1"

    def benchmark(self, src_ips_json):
        try:
            src_ips = json.loads(src_ips_json)
        except Exception:
            src_ips = []

        batch_packets = len(src_ips)
        batch_accepted = 0
        batch_dropped = 0
        batch_evaluations = 0

        for ip in src_ips:
            self.total_packets += 1
            if self.mode == "IPTABLES":
                action = "ACCEPTED"
                evals = 0
                for target, rule_ip in self.rules:
                    evals += 1
                    if rule_ip == ip:
                        action = "DROPPED" if target == "DROP" else "ACCEPTED"
                        break
                batch_evaluations += evals
                self.total_evaluations += evals
                if action == "ACCEPTED":
                    batch_accepted += 1
                    self.accepted_packets += 1
                else:
                    batch_dropped += 1
                    self.dropped_packets += 1
            else: # IPSET
                batch_evaluations += 1
                self.total_evaluations += 1
                if ip in self.ipset_entries:
                    batch_dropped += 1
                    self.dropped_packets += 1
                else:
                    batch_accepted += 1
                    self.accepted_packets += 1

        avg_evals = batch_evaluations / max(1, batch_packets)
        return f"BENCHMARK_RESULT mode={self.mode} packets={batch_packets} accepted={batch_accepted} dropped={batch_dropped} total_evaluations={batch_evaluations} avg_evaluations={avg_evals:.1f}"

    def stats(self):
        avg_evals = self.total_evaluations / max(1, self.total_packets)
        if self.mode == "IPTABLES":
            return f"STATS mode=IPTABLES rules={len(self.rules)} total_packets={self.total_packets} total_evaluations={self.total_evaluations} avg_evaluations={avg_evals:.1f}"
        else:
            return f"STATS mode=IPSET set_size={len(self.ipset_entries)} total_packets={self.total_packets} total_evaluations={self.total_evaluations} avg_evaluations={avg_evals:.1f}"

def main():
    sim = PacketFilterSimulator()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        parts = line.split(maxsplit=1)
        cmd = parts[0]
        rest = parts[1] if len(parts) > 1 else ""

        if cmd == "CONFIG":
            params = {}
            for p in rest.split():
                if '=' in p:
                    k, v = p.split('=', 1)
                    params[k] = v
            print(sim.config(mode=params.get('mode')))

        elif cmd == "ADD_RULE":
            params = {}
            for p in rest.split():
                if '=' in p:
                    k, v = p.split('=', 1)
                    params[k] = v
            print(sim.add_rule(
                target=params.get('target', 'DROP'),
                src_ip=params.get('src_ip', '')
            ))

        elif cmd == "PACKET":
            params = {}
            for p in rest.split():
                if '=' in p:
                    k, v = p.split('=', 1)
                    params[k] = v
            print(sim.process_packet(src_ip=params.get('src_ip', '')))

        elif cmd == "BENCHMARK":
            src_ips_json = "[]"
            if "src_ips=" in rest:
                idx = rest.index("src_ips=")
                src_ips_json = rest[idx + len("src_ips="):]
            print(sim.benchmark(src_ips_json=src_ips_json))

        elif cmd == "STATS":
            print(sim.stats())

        elif cmd == "RESET":
            sim.reset()
            print("OK mode=IPTABLES rules=0 ipset_size=0")

if __name__ == '__main__':
    main()
