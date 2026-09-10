import sys
import json

class KvmSplitIrqchipEngine:
    def __init__(self, num_vcpus=4, split_mode=True):
        self.num_vcpus = num_vcpus
        self.split_mode = split_mode
        self.gsi_routes = {}
        self.vcpus = {}
        for i in range(num_vcpus):
            self.vcpus[i] = {
                "apic_id": i,
                "irr": set(),
                "isr": set(),
                "eoi_exit_bitmap": set()
            }
        self.gsi_levels = {}
        self.stats = {
            "gsi_injections": 0,
            "msi_direct_deliveries": 0,
            "ioapic_eoi_exits": 0,
            "invalid_gsi_drops": 0
        }

    def set_gsi_routing(self, routes):
        self.gsi_routes.clear()
        for v in self.vcpus.values():
            v["eoi_exit_bitmap"].clear()

        for r in routes:
            gsi = r["gsi"]
            if gsi not in self.gsi_routes:
                self.gsi_routes[gsi] = []
            self.gsi_routes[gsi].append({
                "type": r.get("type", "MSI"),
                "dest_id": r.get("dest_id", 0),
                "vector": r.get("vector", 32),
                "delivery_mode": r.get("delivery_mode", "fixed"),
                "level_triggered": r.get("level_triggered", False)
            })
            if self.split_mode and r.get("level_triggered", False):
                dest = r.get("dest_id", 0)
                if dest == 0xff:
                    for v in self.vcpus.values():
                        v["eoi_exit_bitmap"].add(r.get("vector", 32))
                elif dest in self.vcpus:
                    self.vcpus[dest]["eoi_exit_bitmap"].add(r.get("vector", 32))

        return {"status": "ROUTING_TABLE_CONFIGURED", "total_gsis": len(self.gsi_routes)}

    def inject_gsi(self, gsi, level=1):
        self.stats["gsi_injections"] += 1
        if gsi not in self.gsi_routes:
            self.stats["invalid_gsi_drops"] += 1
            return {"status": "EINVAL_UNROUTED_GSI", "gsi": gsi}

        routes = self.gsi_routes[gsi]
        delivered_events = []

        for route in routes:
            rtype = route["type"]
            dest = route["dest_id"]
            vec = route["vector"]
            lvl_trig = route["level_triggered"]

            if lvl_trig:
                old_lvl = self.gsi_levels.get(gsi, 0)
                self.gsi_levels[gsi] = level
                if level == 0:
                    delivered_events.append({
                        "gsi": gsi, "type": rtype, "action": "LINE_DEASSERTED", "level": 0
                    })
                    continue
                elif old_lvl == 1 and level == 1:
                    continue

            target_vcpus = []
            if dest == 0xff:
                target_vcpus = list(range(self.num_vcpus))
            elif dest in self.vcpus:
                target_vcpus = [dest]
            else:
                target_vcpus = [0]

            for v_id in target_vcpus:
                vcpu = self.vcpus[v_id]
                vcpu["irr"].add(vec)
                if rtype == "MSI":
                    self.stats["msi_direct_deliveries"] += 1

                delivered_events.append({
                    "gsi": gsi,
                    "target_vcpu": v_id,
                    "vector": vec,
                    "type": rtype,
                    "level_triggered": lvl_trig
                })

        return {"status": "GSI_INJECTED", "gsi": gsi, "deliveries": delivered_events}

    def vcpu_deliver_interrupt(self, vcpu_id):
        if vcpu_id not in self.vcpus:
            return {"status": "ENOENT_VCPU_NOT_FOUND", "vcpu_id": vcpu_id}
        vcpu = self.vcpus[vcpu_id]
        if not vcpu["irr"]:
            return {"status": "NO_PENDING_INTERRUPT", "vcpu_id": vcpu_id}

        highest_vec = max(vcpu["irr"])
        vcpu["irr"].remove(highest_vec)
        vcpu["isr"].add(highest_vec)

        return {
            "status": "INTERRUPT_SERVICED",
            "vcpu_id": vcpu_id,
            "vector": highest_vec
        }

    def vcpu_eoi(self, vcpu_id, vector):
        if vcpu_id not in self.vcpus:
            return {"status": "ENOENT_VCPU_NOT_FOUND", "vcpu_id": vcpu_id}
        vcpu = self.vcpus[vcpu_id]

        if vector in vcpu["isr"]:
            vcpu["isr"].remove(vector)

        needs_eoi_exit = False
        if self.split_mode and vector in vcpu["eoi_exit_bitmap"]:
            needs_eoi_exit = True
            self.stats["ioapic_eoi_exits"] += 1

        return {
            "status": "EOI_PROCESSED",
            "vcpu_id": vcpu_id,
            "vector": vector,
            "kvm_exit_ioapic_eoi": needs_eoi_exit
        }

    def query_irq_state(self):
        vcpu_states = {}
        for vid in sorted(self.vcpus.keys()):
            vcpu = self.vcpus[vid]
            vcpu_states[vid] = {
                "irr": sorted(list(vcpu["irr"])),
                "isr": sorted(list(vcpu["isr"])),
                "eoi_exit_vectors": sorted(list(vcpu["eoi_exit_bitmap"]))
            }
        return {
            "num_vcpus": self.num_vcpus,
            "split_mode": self.split_mode,
            "configured_gsis": sorted(list(self.gsi_routes.keys())),
            "vcpu_states": vcpu_states,
            "stats": self.stats
        }

def main():
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    raw = sys.stdin.read()
    if not raw.strip():
        return
    input_data = json.loads(raw)

    cfg = input_data.get("config", {})
    num_v = cfg.get("num_vcpus", 4)
    split = cfg.get("split_mode", True)

    engine = KvmSplitIrqchipEngine(num_vcpus=num_v, split_mode=split)
    results = []

    for op in input_data.get("operations", []):
        cmd = op.get("op")
        if cmd == "SET_GSI_ROUTING":
            res = engine.set_gsi_routing(op["routes"])
            results.append(res)
        elif cmd == "INJECT_GSI":
            res = engine.inject_gsi(op["gsi"], op.get("level", 1))
            results.append(res)
        elif cmd == "VCPU_DELIVER_INTERRUPT":
            res = engine.vcpu_deliver_interrupt(op["vcpu_id"])
            results.append(res)
        elif cmd == "VCPU_EOI":
            res = engine.vcpu_eoi(op["vcpu_id"], op["vector"])
            results.append(res)
        elif cmd == "QUERY_IRQ_STATE":
            res = engine.query_irq_state()
            results.append(res)

    out = {"results": results}
    print(json.dumps(out, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
