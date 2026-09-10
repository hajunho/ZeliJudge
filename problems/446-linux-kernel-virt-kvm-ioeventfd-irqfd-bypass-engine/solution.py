import sys
import json

class KvmEventfdEngine:
    def __init__(self, vm_config):
        self.max_gsi = vm_config.get("max_gsi", 1024)
        self.apicv_enabled = vm_config.get("apicv_enabled", False)
        self.vcpus = {}
        for vc in vm_config.get("vcpus", []):
            self.vcpus[vc["vcpu_id"]] = {
                "apic_id": vc["apic_id"],
                "pir": set(),
                "irr": set(),
                "on": False
            }
        
        self.gsi_routes = {}
        self.ioeventfds = []
        self.irqfds = {}
        self.ioapic_pins = {}
        self.eventfd_signals = {}
        
        self.stats = {
            "ioeventfd_fastpath_hits": 0,
            "userspace_exits": 0,
            "irqfd_injections": 0,
            "apicv_posted_count": 0,
            "resample_events": 0
        }

    def _signal_eventfd(self, fd_id, count=1):
        self.eventfd_signals[fd_id] = self.eventfd_signals.get(fd_id, 0) + count

    def set_gsi_routing(self, routes):
        count = 0
        for r in routes:
            gsi = r["gsi"]
            self.gsi_routes[gsi] = r
            if r.get("type") == "IRQCHIP":
                pin = r.get("pin", gsi)
                if pin not in self.ioapic_pins:
                    self.ioapic_pins[pin] = {"level": 0, "vector": r.get("vector", 0), "resample_fds": set()}
                else:
                    self.ioapic_pins[pin]["vector"] = r.get("vector", 0)
            count += 1
        return {"status": "ROUTES_UPDATED", "routes_count": count}

    def register_ioeventfd(self, fd_id, bus, addr, length, flags, datamatch=None):
        has_datamatch = "DATAMATCH" in flags
        for entry in self.ioeventfds:
            if (entry["bus"] == bus and entry["addr"] == addr and entry["len"] == length and
                entry["has_datamatch"] == has_datamatch and entry["datamatch"] == datamatch):
                return {"status": "ERROR_ALREADY_EXISTS", "fd_id": fd_id}
        
        item = {
            "fd_id": fd_id,
            "bus": bus,
            "addr": addr,
            "len": length,
            "has_datamatch": has_datamatch,
            "datamatch": datamatch if has_datamatch else None
        }
        self.ioeventfds.append(item)
        if fd_id not in self.eventfd_signals:
            self.eventfd_signals[fd_id] = 0
        return {"status": "IOEVENTFD_REGISTERED", "fd_id": fd_id}

    def unregister_ioeventfd(self, fd_id, bus, addr, length, flags, datamatch=None):
        has_datamatch = "DATAMATCH" in flags
        idx_to_remove = -1
        for i, entry in enumerate(self.ioeventfds):
            if (entry["fd_id"] == fd_id and entry["bus"] == bus and entry["addr"] == addr and
                entry["len"] == length and entry["has_datamatch"] == has_datamatch and entry["datamatch"] == datamatch):
                idx_to_remove = i
                break
        if idx_to_remove != -1:
            self.ioeventfds.pop(idx_to_remove)
            return {"status": "IOEVENTFD_DEASSIGNED", "fd_id": fd_id}
        return {"status": "ERROR_NOT_FOUND", "fd_id": fd_id}

    def register_irqfd(self, fd_id, gsi, flags, resample_fd_id=None):
        if fd_id in self.irqfds:
            return {"status": "ERROR_ALREADY_EXISTS", "fd_id": fd_id}
        is_resample = "RESAMPLE" in flags
        self.irqfds[fd_id] = {
            "fd_id": fd_id,
            "gsi": gsi,
            "resample": is_resample,
            "resample_fd_id": resample_fd_id if is_resample else None
        }
        if fd_id not in self.eventfd_signals:
            self.eventfd_signals[fd_id] = 0
        if is_resample and resample_fd_id and resample_fd_id not in self.eventfd_signals:
            self.eventfd_signals[resample_fd_id] = 0
        return {"status": "IRQFD_REGISTERED", "fd_id": fd_id, "gsi": gsi}

    def unregister_irqfd(self, fd_id, gsi):
        if fd_id in self.irqfds and self.irqfds[fd_id]["gsi"] == gsi:
            del self.irqfds[fd_id]
            return {"status": "IRQFD_DEASSIGNED", "fd_id": fd_id, "gsi": gsi}
        return {"status": "ERROR_NOT_FOUND", "fd_id": fd_id}

    def guest_io_access(self, vcpu_id, bus, access_type, addr, length, val):
        if access_type == "WRITE":
            for entry in self.ioeventfds:
                if entry["bus"] == bus and entry["addr"] == addr and entry["len"] == length:
                    if entry["has_datamatch"]:
                        if entry["datamatch"] == val:
                            self._signal_eventfd(entry["fd_id"], 1)
                            self.stats["ioeventfd_fastpath_hits"] += 1
                            return {
                                "status": "HANDLED_IN_KERNEL",
                                "bypassed_userspace": True,
                                "signaled_fd": entry["fd_id"],
                                "val": val
                            }
                    else:
                        self._signal_eventfd(entry["fd_id"], 1)
                        self.stats["ioeventfd_fastpath_hits"] += 1
                        return {
                            "status": "HANDLED_IN_KERNEL",
                            "bypassed_userspace": True,
                            "signaled_fd": entry["fd_id"],
                            "val": val
                        }

        self.stats["userspace_exits"] += 1
        return {
            "status": "KVM_EXIT_IO",
            "bypassed_userspace": False,
            "exit_reason": bus,
            "access_type": access_type,
            "addr": addr,
            "len": length,
            "val": val
        }

    def signal_irqfd(self, fd_id, count=1):
        if fd_id not in self.irqfds:
            return {"status": "ERROR_UNKNOWN_IRQFD", "fd_id": fd_id}
        
        info = self.irqfds[fd_id]
        gsi = info["gsi"]
        self._signal_eventfd(fd_id, count)
        
        if gsi not in self.gsi_routes:
            return {"status": "UNROUTED_GSI", "fd_id": fd_id, "gsi": gsi}
        
        route = self.gsi_routes[gsi]
        route_type = route.get("type", "MSI")
        self.stats["irqfd_injections"] += 1
        
        if route_type == "MSI":
            dest_apic = route.get("dest_apic_id", 0)
            vector = route.get("vector", 0)
            
            target_vcpu = None
            for v_id, v_data in self.vcpus.items():
                if v_data["apic_id"] == dest_apic:
                    target_vcpu = v_id
                    break
            
            if target_vcpu is None:
                target_vcpu = 0
            
            vcpu_obj = self.vcpus.get(target_vcpu)
            if self.apicv_enabled:
                if vcpu_obj:
                    vcpu_obj["pir"].add(vector)
                    vcpu_obj["on"] = True
                self.stats["apicv_posted_count"] += 1
                return {
                    "status": "INJECTED",
                    "gsi": gsi,
                    "type": "MSI",
                    "target_vcpu": target_vcpu,
                    "vector": vector,
                    "method": "APICV_POSTED_INTR"
                }
            else:
                if vcpu_obj:
                    vcpu_obj["irr"].add(vector)
                return {
                    "status": "INJECTED",
                    "gsi": gsi,
                    "type": "MSI",
                    "target_vcpu": target_vcpu,
                    "vector": vector,
                    "method": "LAPIC_IRR_INJECT"
                }
        
        elif route_type == "IRQCHIP":
            pin = route.get("pin", gsi)
            vector = route.get("vector", 0)
            if pin not in self.ioapic_pins:
                self.ioapic_pins[pin] = {"level": 0, "vector": vector, "resample_fds": set()}
            
            self.ioapic_pins[pin]["level"] = 1
            if info["resample"] and info["resample_fd_id"]:
                self.ioapic_pins[pin]["resample_fds"].add(info["resample_fd_id"])
            
            return {
                "status": "LINE_ASSERTED",
                "gsi": gsi,
                "type": "IRQCHIP",
                "pin": pin,
                "vector": vector
            }
        
        return {"status": "UNKNOWN_ROUTE_TYPE", "gsi": gsi}

    def guest_eoi(self, vcpu_id, vector):
        resampled_fds = []
        for pin, pin_data in self.ioapic_pins.items():
            if pin_data.get("vector") == vector and pin_data["level"] == 1:
                pin_data["level"] = 0
                for r_fd in sorted(list(pin_data["resample_fds"])):
                    self._signal_eventfd(r_fd, 1)
                    resampled_fds.append(r_fd)
                    self.stats["resample_events"] += 1
                pin_data["resample_fds"].clear()
        
        if vcpu_id in self.vcpus:
            self.vcpus[vcpu_id]["irr"].discard(vector)
            self.vcpus[vcpu_id]["pir"].discard(vector)
        
        return {
            "status": "EOI_HANDLED",
            "vcpu_id": vcpu_id,
            "vector": vector,
            "resampled_fds": resampled_fds
        }

    def query_stats(self):
        return {
            "ioeventfd_fastpath_hits": self.stats["ioeventfd_fastpath_hits"],
            "userspace_exits": self.stats["userspace_exits"],
            "irqfd_injections": self.stats["irqfd_injections"],
            "apicv_posted_count": self.stats["apicv_posted_count"],
            "resample_events": self.stats["resample_events"],
            "active_ioeventfds": len(self.ioeventfds),
            "active_irqfds": len(self.irqfds),
            "eventfd_signals": dict(sorted(self.eventfd_signals.items()))
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
    vm_config = input_data.get("vm_config", {})
    engine = KvmEventfdEngine(vm_config)
    results = []
    
    for op in input_data.get("operations", []):
        cmd = op.get("op")
        if cmd == "SET_GSI_ROUTING":
            res = engine.set_gsi_routing(op.get("routes", []))
            results.append(res)
        elif cmd == "REGISTER_IOEVENTFD":
            res = engine.register_ioeventfd(
                op["fd_id"], op["bus"], op["addr"], op["len"], op.get("flags", []), op.get("datamatch")
            )
            results.append(res)
        elif cmd == "UNREGISTER_IOEVENTFD":
            res = engine.unregister_ioeventfd(
                op["fd_id"], op["bus"], op["addr"], op["len"], op.get("flags", []), op.get("datamatch")
            )
            results.append(res)
        elif cmd == "REGISTER_IRQFD":
            res = engine.register_irqfd(
                op["fd_id"], op["gsi"], op.get("flags", []), op.get("resample_fd_id")
            )
            results.append(res)
        elif cmd == "UNREGISTER_IRQFD":
            res = engine.unregister_irqfd(op["fd_id"], op["gsi"])
            results.append(res)
        elif cmd == "GUEST_IO_ACCESS":
            res = engine.guest_io_access(
                op["vcpu_id"], op["bus"], op["type"], op["addr"], op["len"], op.get("val", 0)
            )
            results.append(res)
        elif cmd == "SIGNAL_IRQFD":
            res = engine.signal_irqfd(op["fd_id"], op.get("count", 1))
            results.append(res)
        elif cmd == "GUEST_EOI":
            res = engine.guest_eoi(op["vcpu_id"], op["vector"])
            results.append(res)
        elif cmd == "QUERY_STATS":
            res = engine.query_stats()
            results.append(res)
            
    out_obj = {"results": results}
    print(json.dumps(out_obj, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    solve()
