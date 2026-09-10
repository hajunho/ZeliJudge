import sys
import json

class KprobeEngine:
    def __init__(self, ssol_base=0x7fff0000, slot_size=64, max_slots=16):
        self.code_mem = {}
        self.orig_insns = {}
        self.blacklist = []
        self.ssol_base = ssol_base
        self.slot_size = slot_size
        self.max_slots = max_slots
        self.free_slots = list(range(max_slots))
        self.probes = {}
        self.addr_to_probe = {}
        self.regs = {
            "rax": 0, "rbx": 0, "rcx": 0, "rdx": 0,
            "rip": 0, "flags": {"zf": False, "cf": False}
        }
        self.stats = {
            "probes_registered": 0,
            "probes_unregistered": 0,
            "probe_hits": 0,
            "ssol_fixups": 0
        }

    def load_code(self, instructions, start_rip=None, init_regs=None):
        self.code_mem.clear()
        self.orig_insns.clear()
        for insn in instructions:
            self.code_mem[insn["addr"]] = dict(insn)
        if init_regs:
            for r, v in init_regs.items():
                if r == "flags":
                    self.regs["flags"].update(v)
                else:
                    self.regs[r] = v
        if start_rip is not None:
            self.regs["rip"] = start_rip
        elif instructions:
            self.regs["rip"] = instructions[0]["addr"]
        return {"status": "CODE_LOADED", "insn_count": len(instructions), "entry_rip": self.regs["rip"]}

    def set_blacklist(self, ranges):
        self.blacklist = [(r["start"], r["end"]) for r in ranges]
        return {"status": "BLACKLIST_CONFIGURED", "ranges_count": len(self.blacklist)}

    def is_blacklisted(self, addr):
        for start, end in self.blacklist:
            if start <= addr < end:
                return True
        return False

    def is_valid_insn_boundary(self, addr):
        return addr in self.code_mem

    def register_kprobe(self, probe_id, addr, pre_handler=None, post_handler=None):
        if probe_id in self.probes:
            return {"status": "EEXIST_PROBE_ID", "probe_id": probe_id}
        if addr in self.addr_to_probe:
            return {"status": "EBUSY_ALREADY_PROBED", "addr": addr}
        if self.is_blacklisted(addr):
            return {"status": "EINVAL_BLACKLISTED", "addr": addr}
        if not self.is_valid_insn_boundary(addr):
            return {"status": "EINVAL_NOT_INSN_BOUNDARY", "addr": addr}
        if not self.free_slots:
            return {"status": "ENOSPC_SSOL_FULL"}

        orig_insn = dict(self.code_mem[addr])
        slot_idx = self.free_slots.pop(0)
        slot_addr = self.ssol_base + slot_idx * self.slot_size

        slot_insn = dict(orig_insn)
        slot_insn["addr"] = slot_addr
        fixup_applied = False

        if orig_insn.get("is_rip_relative", False):
            target_addr = orig_insn["operands"]["target_addr"]
            new_disp = target_addr - (slot_addr + orig_insn["len"])
            slot_insn["operands"] = dict(orig_insn["operands"])
            slot_insn["operands"]["disp"] = new_disp
            fixup_applied = True
            self.stats["ssol_fixups"] += 1

        resume_addr = addr + orig_insn["len"]

        probe_entry = {
            "probe_id": probe_id,
            "addr": addr,
            "slot_idx": slot_idx,
            "slot_addr": slot_addr,
            "slot_insn": slot_insn,
            "resume_addr": resume_addr,
            "pre_handler": pre_handler,
            "post_handler": post_handler,
            "hits": 0,
            "fixup_applied": fixup_applied
        }

        self.probes[probe_id] = probe_entry
        self.addr_to_probe[addr] = probe_id
        self.orig_insns[addr] = orig_insn

        int3_insn = {
            "addr": addr,
            "opcode": "INT3",
            "len": 1,
            "operands": {}
        }
        self.code_mem[addr] = int3_insn
        self.stats["probes_registered"] += 1

        return {
            "status": "KPROBE_REGISTERED",
            "probe_id": probe_id,
            "addr": addr,
            "slot_addr": slot_addr,
            "fixup_applied": fixup_applied
        }

    def unregister_kprobe(self, probe_id):
        if probe_id not in self.probes:
            return {"status": "ENOENT_PROBE_NOT_FOUND", "probe_id": probe_id}

        probe = self.probes.pop(probe_id)
        addr = probe["addr"]
        slot_idx = probe["slot_idx"]

        self.code_mem[addr] = self.orig_insns.pop(addr)
        del self.addr_to_probe[addr]

        self.free_slots.append(slot_idx)
        self.free_slots.sort()
        self.stats["probes_unregistered"] += 1

        return {
            "status": "KPROBE_UNREGISTERED",
            "probe_id": probe_id,
            "addr": addr,
            "freed_slot": slot_idx
        }

    def _execute_single_insn(self, insn):
        opcode = insn["opcode"]
        ops = insn.get("operands", {})
        length = insn["len"]
        next_rip = self.regs["rip"] + length

        if opcode == "MOV_REG_IMM":
            self.regs[ops["dst"]] = ops["src"]
        elif opcode == "MOV_REG_REG":
            self.regs[ops["dst"]] = self.regs[ops["src"]]
        elif opcode == "ADD_REG_IMM":
            self.regs[ops["dst"]] += ops["src"]
        elif opcode == "ADD_REG_REG":
            self.regs[ops["dst"]] += self.regs[ops["src"]]
        elif opcode == "SUB_REG_IMM":
            self.regs[ops["dst"]] -= ops["src"]
            self.regs["flags"]["zf"] = (self.regs[ops["dst"]] == 0)
        elif opcode == "CMP_REG_IMM":
            val = self.regs[ops["dst"]] - ops["src"]
            self.regs["flags"]["zf"] = (val == 0)
        elif opcode == "JMP_REL32":
            next_rip = ops["target_addr"]
        elif opcode == "JE_REL32":
            if self.regs["flags"]["zf"]:
                next_rip = ops["target_addr"]
        elif opcode == "NOP":
            pass
        elif opcode == "RET":
            next_rip = None

        return next_rip

    def step(self):
        rip = self.regs["rip"]
        if rip not in self.code_mem:
            return {"status": "SIGSEGV_INVALID_RIP", "rip": rip}

        insn = self.code_mem[rip]
        if insn["opcode"] == "INT3":
            probe_id = self.addr_to_probe[rip]
            probe = self.probes[probe_id]
            probe["hits"] += 1
            self.stats["probe_hits"] += 1

            pre_log = None
            if probe["pre_handler"]:
                if "set_reg" in probe["pre_handler"]:
                    for r, v in probe["pre_handler"]["set_reg"].items():
                        self.regs[r] = v
                pre_log = probe["pre_handler"].get("tag", "PRE_OK")

            slot_insn = probe["slot_insn"]
            self.regs["rip"] = probe["slot_addr"]

            branch_target = self._execute_single_insn(slot_insn)

            post_log = None
            if probe["post_handler"]:
                post_log = probe["post_handler"].get("tag", "POST_OK")

            if slot_insn["opcode"] in ["JMP_REL32", "JE_REL32"] and branch_target != (probe["slot_addr"] + slot_insn["len"]):
                next_rip = branch_target
            elif slot_insn["opcode"] == "RET":
                next_rip = None
            else:
                next_rip = probe["resume_addr"]

            self.regs["rip"] = next_rip

            return {
                "event": "KPROBE_HIT",
                "probe_id": probe_id,
                "addr": rip,
                "slot_addr": probe["slot_addr"],
                "pre_log": pre_log,
                "post_log": post_log,
                "next_rip": next_rip,
                "regs": dict(self.regs)
            }
        else:
            next_rip = self._execute_single_insn(insn)
            self.regs["rip"] = next_rip
            return {
                "event": "INSN_EXEC",
                "rip": rip,
                "opcode": insn["opcode"],
                "next_rip": next_rip,
                "regs": dict(self.regs)
            }

    def run_until_ret(self, max_steps=50):
        steps = 0
        events = []
        while steps < max_steps and self.regs["rip"] is not None:
            res = self.step()
            events.append(res)
            steps += 1
            if res.get("status") == "SIGSEGV_INVALID_RIP" or self.regs["rip"] is None:
                break
        return {"total_steps": steps, "events": events, "final_regs": dict(self.regs)}

    def query_state(self):
        active = {}
        for pid in sorted(self.probes.keys()):
            p = self.probes[pid]
            active[pid] = {
                "addr": p["addr"],
                "slot_addr": p["slot_addr"],
                "hits": p["hits"],
                "fixup_applied": p["fixup_applied"]
            }
        return {
            "active_probes": active,
            "free_slots_count": len(self.free_slots),
            "regs": dict(self.regs),
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

    ssol_cfg = input_data.get("ssol_config", {})
    base = ssol_cfg.get("base", 0x7fff0000)
    slot_size = ssol_cfg.get("slot_size", 64)
    max_slots = ssol_cfg.get("max_slots", 16)

    engine = KprobeEngine(ssol_base=base, slot_size=slot_size, max_slots=max_slots)
    results = []

    for op in input_data.get("operations", []):
        cmd = op.get("op")
        if cmd == "LOAD_CODE":
            res = engine.load_code(op["instructions"], op.get("start_rip"), op.get("init_regs"))
            results.append(res)
        elif cmd == "SET_BLACKLIST":
            res = engine.set_blacklist(op["ranges"])
            results.append(res)
        elif cmd == "REGISTER_KPROBE":
            res = engine.register_kprobe(op["probe_id"], op["addr"], op.get("pre_handler"), op.get("post_handler"))
            results.append(res)
        elif cmd == "UNREGISTER_KPROBE":
            res = engine.unregister_kprobe(op["probe_id"])
            results.append(res)
        elif cmd == "STEP":
            res = engine.step()
            results.append(res)
        elif cmd == "RUN_UNTIL_RET":
            res = engine.run_until_ret(op.get("max_steps", 50))
            results.append(res)
        elif cmd == "QUERY_STATE":
            res = engine.query_state()
            results.append(res)

    out = {"results": results}
    print(json.dumps(out, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
