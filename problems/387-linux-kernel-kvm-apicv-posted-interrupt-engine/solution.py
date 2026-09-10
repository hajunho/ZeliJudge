# -*- coding: utf-8 -*-
"""
ZeliJudge Pro #387: Linux Kernel KVM APICv & Posted-Interrupt Processing (PIR/PID) Engine
Implementation in Python 3.
"""
import sys
import json

class ApicvEngine:
    def __init__(self, config):
        self.num_vcpus = config.get("num_vcpus", 4)
        self.vcpus = {}
        for i in range(self.num_vcpus):
            self.vcpus[i] = {
                "id": i,
                "pcpu": i,
                "state": "GUEST_RUNNING",
                "pid": {
                    "pir": [0] * 8,
                    "on": 0,
                    "sn": 0,
                    "nv": 0xf2,
                    "wakeup_nv": 0xf3
                },
                "vapic": {
                    "irr": [0] * 8,
                    "isr": [0] * 8,
                    "tpr": 0
                }
            }

        self.events = []
        self.direct_deliveries = 0
        self.wakeup_ipis = 0
        self.suppressed_notifications = 0
        self.vm_exits_avoided = 0

    def _set_bit(self, arr, bit):
        word = bit // 32
        offset = bit % 32
        arr[word] |= (1 << offset)

    def _clear_bit(self, arr, bit):
        word = bit // 32
        offset = bit % 32
        arr[word] &= ~(1 << offset)

    def _test_bit(self, arr, bit):
        word = bit // 32
        offset = bit % 32
        return (arr[word] & (1 << offset)) != 0

    def _highest_bit(self, arr):
        for w in range(7, -1, -1):
            if arr[w] != 0:
                for b in range(31, -1, -1):
                    if (arr[w] & (1 << b)) != 0:
                        return w * 32 + b
        return -1

    def run_commands(self, commands):
        for cmd in commands:
            op = cmd.get("op")
            if op == "POST_INTR":
                self._handle_post_intr(cmd)
            elif op == "SET_STATE":
                self._handle_set_state(cmd)
            elif op == "SET_SN":
                self._handle_set_sn(cmd)
            elif op == "SET_TPR":
                self._handle_set_tpr(cmd)
            elif op == "GUEST_STEP":
                self._handle_guest_step(cmd)
            elif op == "GUEST_EOI":
                self._handle_guest_eoi(cmd)

    def _handle_post_intr(self, cmd):
        target_id = cmd["target_vcpu"]
        vector = cmd["vector"]
        vcpu = self.vcpus[target_id]
        pid = vcpu["pid"]

        self._set_bit(pid["pir"], vector)

        if pid["sn"] == 1:
            self.suppressed_notifications += 1
            self.events.append({
                "op": "POST_INTR",
                "target_vcpu": target_id,
                "vector": vector,
                "status": "POSTED_SUPPRESSED",
                "reason": "SN flag set"
            })
            return

        was_on = pid["on"]
        pid["on"] = 1

        if was_on == 1:
            self.events.append({
                "op": "POST_INTR",
                "target_vcpu": target_id,
                "vector": vector,
                "status": "POSTED_COALESCED",
                "reason": "ON already set"
            })
            return

        if vcpu["state"] == "GUEST_RUNNING":
            self._sync_pir_to_irr(vcpu)
            pid["on"] = 0
            self.direct_deliveries += 1
            self.vm_exits_avoided += 1
            self.events.append({
                "op": "POST_INTR",
                "target_vcpu": target_id,
                "vector": vector,
                "status": "DELIVERED_ZERO_EXIT",
                "nv": hex(pid["nv"])
            })
        elif vcpu["state"] == "GUEST_BLOCKED":
            self.wakeup_ipis += 1
            vcpu["state"] = "GUEST_RUNNING"
            self._sync_pir_to_irr(vcpu)
            pid["on"] = 0
            self.events.append({
                "op": "POST_INTR",
                "target_vcpu": target_id,
                "vector": vector,
                "status": "WAKEUP_FROM_BLOCK",
                "nv": hex(pid["wakeup_nv"])
            })
        else:
            self.events.append({
                "op": "POST_INTR",
                "target_vcpu": target_id,
                "vector": vector,
                "status": "QUEUED_IN_PIR_HOST_ROOT"
            })

    def _sync_pir_to_irr(self, vcpu):
        for i in range(8):
            vcpu["vapic"]["irr"][i] |= vcpu["pid"]["pir"][i]
            vcpu["pid"]["pir"][i] = 0

    def _handle_set_state(self, cmd):
        vid = cmd["vcpu_id"]
        new_state = cmd["state"]
        old_state = self.vcpus[vid]["state"]
        self.vcpus[vid]["state"] = new_state
        if old_state == "HOST_ROOT" and new_state == "GUEST_RUNNING":
            self._sync_pir_to_irr(self.vcpus[vid])
            self.vcpus[vid]["pid"]["on"] = 0

        self.events.append({
            "op": "SET_STATE",
            "vcpu_id": vid,
            "old_state": old_state,
            "new_state": new_state
        })

    def _handle_set_sn(self, cmd):
        vid = cmd["vcpu_id"]
        sn = cmd["sn"]
        self.vcpus[vid]["pid"]["sn"] = sn
        if sn == 0 and self.vcpus[vid]["state"] == "GUEST_RUNNING":
            has_pending = any(self.vcpus[vid]["pid"]["pir"])
            if has_pending:
                self._sync_pir_to_irr(self.vcpus[vid])
                self.direct_deliveries += 1
                self.vm_exits_avoided += 1

        self.events.append({
            "op": "SET_SN",
            "vcpu_id": vid,
            "sn": sn
        })

    def _handle_set_tpr(self, cmd):
        vid = cmd["vcpu_id"]
        tpr = cmd["tpr"]
        self.vcpus[vid]["vapic"]["tpr"] = tpr
        self.events.append({
            "op": "SET_TPR",
            "vcpu_id": vid,
            "tpr": tpr
        })

    def _handle_guest_step(self, cmd):
        vid = cmd["vcpu_id"]
        vcpu = self.vcpus[vid]
        vapic = vcpu["vapic"]

        highest_irr = self._highest_bit(vapic["irr"])
        highest_isr = self._highest_bit(vapic["isr"])
        ppr = max(vapic["tpr"], highest_isr if highest_isr != -1 else 0)

        if highest_irr > ppr:
            self._clear_bit(vapic["irr"], highest_irr)
            self._set_bit(vapic["isr"], highest_irr)
            self.events.append({
                "op": "GUEST_STEP",
                "vcpu_id": vid,
                "status": "DISPATCH_INTERRUPT",
                "vector": highest_irr
            })
        else:
            self.events.append({
                "op": "GUEST_STEP",
                "vcpu_id": vid,
                "status": "NO_DISPATCH",
                "highest_irr": highest_irr,
                "ppr": ppr
            })

    def _handle_guest_eoi(self, cmd):
        vid = cmd["vcpu_id"]
        vapic = self.vcpus[vid]["vapic"]
        highest_isr = self._highest_bit(vapic["isr"])
        if highest_isr != -1:
            self._clear_bit(vapic["isr"], highest_isr)
            self.events.append({
                "op": "GUEST_EOI",
                "vcpu_id": vid,
                "cleared_vector": highest_isr,
                "status": "SUCCESS"
            })
        else:
            self.events.append({
                "op": "GUEST_EOI",
                "vcpu_id": vid,
                "status": "SPURIOUS_EOI"
            })

    def get_result(self):
        vcpu_states = {}
        for vid, v in self.vcpus.items():
            vcpu_states[vid] = {
                "state": v["state"],
                "highest_irr": self._highest_bit(v["vapic"]["irr"]),
                "highest_isr": self._highest_bit(v["vapic"]["isr"]),
                "tpr": v["vapic"]["tpr"],
                "pid_on": v["pid"]["on"],
                "pid_sn": v["pid"]["sn"]
            }

        return {
            "vcpus": vcpu_states,
            "direct_deliveries": self.direct_deliveries,
            "wakeup_ipis": self.wakeup_ipis,
            "suppressed_notifications": self.suppressed_notifications,
            "vm_exits_avoided": self.vm_exits_avoided,
            "events": self.events
        }

def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    commands = data.get("commands", [])

    engine = ApicvEngine(config)
    engine.run_commands(commands)
    result = engine.get_result()

    sys.stdout.write(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
