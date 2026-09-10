# -*- coding: utf-8 -*-
import sys
import json
from copy import deepcopy

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

class RegType:
    NOT_INIT = "NOT_INIT"
    SCALAR = "SCALAR"
    PTR_TO_PACKET = "PTR_TO_PACKET"
    PTR_TO_PACKET_END = "PTR_TO_PACKET_END"
    PTR_TO_STACK = "PTR_TO_STACK"

class RegisterState:
    def __init__(self, rtype=RegType.NOT_INIT, umin=0, umax=0xFFFFFFFF, off=0, pkt_range=0):
        self.type = rtype
        self.umin = umin
        self.umax = umax
        self.off = off
        self.pkt_range = pkt_range  # bytes proven safe to read from packet start

    def to_dict(self):
        d = {"type": self.type}
        if self.type == RegType.SCALAR:
            d["umin"] = self.umin
            d["umax"] = self.umax
        elif self.type == RegType.PTR_TO_PACKET:
            d["off"] = self.off
            d["pkt_range"] = self.pkt_range
        elif self.type in (RegType.PTR_TO_PACKET_END, RegType.PTR_TO_STACK):
            d["off"] = self.off
        return d

    def is_subsumed_by(self, old):
        """Returns True if self (current state) is as strict as or safer than old (cached state)."""
        if self.type != old.type:
            return False
        if self.type == RegType.NOT_INIT:
            return True
        if self.type == RegType.SCALAR:
            return self.umin >= old.umin and self.umax <= old.umax
        if self.type == RegType.PTR_TO_PACKET:
            return self.off == old.off and self.pkt_range >= old.pkt_range
        if self.type in (RegType.PTR_TO_PACKET_END, RegType.PTR_TO_STACK):
            return self.off == old.off
        return True

def clone_regs(regs):
    return [RegisterState(r.type, r.umin, r.umax, r.off, r.pkt_range) for r in regs]

class BPFVerifier:
    def __init__(self, config=None):
        config = config or {}
        self.max_insns = config.get("max_insns", 2000)
        self.explored_states = {}  # pc -> list of [RegisterState * 11] (verified safe states)
        self.insns_processed = 0
        self.branches_pruned = 0
        self.paths_explored = 0

    def verify(self, instructions):
        # R1: PTR_TO_PACKET (ctx.data, off=0, pkt_range=0)
        # R2: PTR_TO_PACKET_END (ctx.data_end)
        # R10: PTR_TO_STACK (frame pointer, off=0)
        # R0, R3-R9: NOT_INIT
        init_regs = [RegisterState(RegType.NOT_INIT) for _ in range(11)]
        init_regs[1] = RegisterState(RegType.PTR_TO_PACKET, off=0, pkt_range=0)
        init_regs[2] = RegisterState(RegType.PTR_TO_PACKET_END, off=0)
        init_regs[10] = RegisterState(RegType.PTR_TO_STACK, off=0)

        # Worklist DFS: (pc, regs, path_history)
        stack = [(0, init_regs, [])]
        num_insns = len(instructions)

        while stack:
            pc, regs, path_hist = stack.pop()
            self.paths_explored += 1

            path_ended = False
            while pc < num_insns:
                self.insns_processed += 1
                if self.insns_processed > self.max_insns:
                    return {
                        "verified": False,
                        "rejection_reason": "INSTRUCTION_LIMIT_EXCEEDED",
                        "failing_pc": pc,
                        "insns_processed": self.insns_processed,
                        "branches_pruned": self.branches_pruned
                    }

                # Check branch pruning if this PC has cached verified states
                if pc in self.explored_states:
                    pruned = False
                    for cached_regs in self.explored_states[pc]:
                        all_subsumed = True
                        for r_idx in range(11):
                            if not regs[r_idx].is_subsumed_by(cached_regs[r_idx]):
                                all_subsumed = False
                                break
                        if all_subsumed:
                            self.branches_pruned += 1
                            pruned = True
                            break
                    if pruned:
                        path_ended = True
                        break

                path_hist.append((pc, clone_regs(regs)))

                insn = instructions[pc]
                op = insn.get("op")
                dst = insn.get("dst")
                src = insn.get("src")
                imm = insn.get("imm", 0)
                off = insn.get("off", 0)
                size = insn.get("size", 4)

                if op == "MOV":
                    if src is not None:
                        if regs[src].type == RegType.NOT_INIT:
                            return {
                                "verified": False,
                                "rejection_reason": f"READ_UNINITIALIZED_REG_R{src}",
                                "failing_pc": pc,
                                "insns_processed": self.insns_processed,
                                "branches_pruned": self.branches_pruned
                            }
                        regs[dst] = RegisterState(regs[src].type, regs[src].umin, regs[src].umax, regs[src].off, regs[src].pkt_range)
                    else:
                        regs[dst] = RegisterState(RegType.SCALAR, umin=imm, umax=imm)
                    pc += 1

                elif op == "ADD":
                    if regs[dst].type == RegType.NOT_INIT:
                        return {
                            "verified": False,
                            "rejection_reason": f"READ_UNINITIALIZED_REG_R{dst}",
                            "failing_pc": pc,
                            "insns_processed": self.insns_processed,
                            "branches_pruned": self.branches_pruned
                        }
                    if src is not None:
                        if regs[src].type == RegType.NOT_INIT:
                            return {
                                "verified": False,
                                "rejection_reason": f"READ_UNINITIALIZED_REG_R{src}",
                                "failing_pc": pc,
                                "insns_processed": self.insns_processed,
                                "branches_pruned": self.branches_pruned
                            }
                        if regs[dst].type == RegType.SCALAR and regs[src].type == RegType.SCALAR:
                            regs[dst].umin += regs[src].umin
                            regs[dst].umax += regs[src].umax
                        elif regs[dst].type == RegType.PTR_TO_PACKET and regs[src].type == RegType.SCALAR:
                            if regs[src].umin == regs[src].umax:
                                regs[dst].off += regs[src].umin
                            else:
                                return {
                                    "verified": False,
                                    "rejection_reason": f"VARIABLE_OFFSET_POINTER_ARITHMETIC_UNSUPPORTED_R{src}",
                                    "failing_pc": pc,
                                    "insns_processed": self.insns_processed,
                                    "branches_pruned": self.branches_pruned
                                }
                        else:
                            return {
                                "verified": False,
                                "rejection_reason": f"ILLEGAL_POINTER_ARITHMETIC_R{dst}_R{src}",
                                "failing_pc": pc,
                                "insns_processed": self.insns_processed,
                                "branches_pruned": self.branches_pruned
                            }
                    else:
                        if regs[dst].type == RegType.SCALAR:
                            regs[dst].umin += imm
                            regs[dst].umax += imm
                        elif regs[dst].type == RegType.PTR_TO_PACKET:
                            regs[dst].off += imm
                        else:
                            return {
                                "verified": False,
                                "rejection_reason": f"ILLEGAL_ADD_TO_PTR_R{dst}",
                                "failing_pc": pc,
                                "insns_processed": self.insns_processed,
                                "branches_pruned": self.branches_pruned
                            }
                    pc += 1

                elif op == "SUB":
                    if regs[dst].type == RegType.NOT_INIT:
                        return {
                            "verified": False,
                            "rejection_reason": f"READ_UNINITIALIZED_REG_R{dst}",
                            "failing_pc": pc,
                            "insns_processed": self.insns_processed,
                            "branches_pruned": self.branches_pruned
                        }
                    if regs[dst].type != RegType.SCALAR:
                        return {
                            "verified": False,
                            "rejection_reason": f"ILLEGAL_SUB_NON_SCALAR_R{dst}",
                            "failing_pc": pc,
                            "insns_processed": self.insns_processed,
                            "branches_pruned": self.branches_pruned
                        }
                    if src is not None:
                        if regs[src].type != RegType.SCALAR:
                            return {
                                "verified": False,
                                "rejection_reason": f"ILLEGAL_SUB_SRC_R{src}",
                                "failing_pc": pc,
                                "insns_processed": self.insns_processed,
                                "branches_pruned": self.branches_pruned
                            }
                        regs[dst].umin = max(0, regs[dst].umin - regs[src].umax)
                        regs[dst].umax = max(0, regs[dst].umax - regs[src].umin)
                    else:
                        regs[dst].umin = max(0, regs[dst].umin - imm)
                        regs[dst].umax = max(0, regs[dst].umax - imm)
                    pc += 1

                elif op == "CHECK_PKT_LEN":
                    if regs[dst].type != RegType.PTR_TO_PACKET:
                        return {
                            "verified": False,
                            "rejection_reason": f"BOUNDS_CHECK_ON_NON_PACKET_PTR_R{dst}",
                            "failing_pc": pc,
                            "insns_processed": self.insns_processed,
                            "branches_pruned": self.branches_pruned
                        }
                    regs[dst].pkt_range = max(regs[dst].pkt_range, regs[dst].off + imm)
                    pc += 1

                elif op == "LDX":
                    if regs[src].type == RegType.NOT_INIT:
                        return {
                            "verified": False,
                            "rejection_reason": f"READ_UNINITIALIZED_REG_R{src}",
                            "failing_pc": pc,
                            "insns_processed": self.insns_processed,
                            "branches_pruned": self.branches_pruned
                        }
                    if regs[src].type != RegType.PTR_TO_PACKET:
                        return {
                            "verified": False,
                            "rejection_reason": f"MEM_ACCESS_NOT_PACKET_PTR_R{src}",
                            "failing_pc": pc,
                            "insns_processed": self.insns_processed,
                            "branches_pruned": self.branches_pruned
                        }
                    req_bound = regs[src].off + off + size
                    if req_bound > regs[src].pkt_range:
                        return {
                            "verified": False,
                            "rejection_reason": f"OUT_OF_BOUNDS_PACKET_READ_REQ_{req_bound}_PROVEN_{regs[src].pkt_range}",
                            "failing_pc": pc,
                            "insns_processed": self.insns_processed,
                            "branches_pruned": self.branches_pruned
                        }
                    max_val = (1 << (size * 8)) - 1
                    regs[dst] = RegisterState(RegType.SCALAR, umin=0, umax=max_val)
                    pc += 1

                elif op == "JGT":
                    if regs[dst].type == RegType.NOT_INIT:
                        return {
                            "verified": False,
                            "rejection_reason": f"READ_UNINITIALIZED_REG_R{dst}",
                            "failing_pc": pc,
                            "insns_processed": self.insns_processed,
                            "branches_pruned": self.branches_pruned
                        }
                    target_pc = pc + 1 + off
                    if target_pc < 0 or target_pc >= num_insns:
                        return {
                            "verified": False,
                            "rejection_reason": f"JUMP_TARGET_OUT_OF_BOUNDS_{target_pc}",
                            "failing_pc": pc,
                            "insns_processed": self.insns_processed,
                            "branches_pruned": self.branches_pruned
                        }

                    branch_regs = clone_regs(regs)
                    branch_regs[dst].umin = max(branch_regs[dst].umin, imm + 1)
                    if branch_regs[dst].umin <= branch_regs[dst].umax:
                        stack.append((target_pc, branch_regs, list(path_hist)))

                    regs[dst].umax = min(regs[dst].umax, imm)
                    if regs[dst].umin > regs[dst].umax:
                        path_ended = True
                        break
                    pc += 1

                elif op == "JEQ":
                    if regs[dst].type == RegType.NOT_INIT:
                        return {
                            "verified": False,
                            "rejection_reason": f"READ_UNINITIALIZED_REG_R{dst}",
                            "failing_pc": pc,
                            "insns_processed": self.insns_processed,
                            "branches_pruned": self.branches_pruned
                        }
                    target_pc = pc + 1 + off
                    if target_pc < 0 or target_pc >= num_insns:
                        return {
                            "verified": False,
                            "rejection_reason": f"JUMP_TARGET_OUT_OF_BOUNDS_{target_pc}",
                            "failing_pc": pc,
                            "insns_processed": self.insns_processed,
                            "branches_pruned": self.branches_pruned
                        }

                    branch_regs = clone_regs(regs)
                    branch_regs[dst].umin = max(branch_regs[dst].umin, imm)
                    branch_regs[dst].umax = min(branch_regs[dst].umax, imm)
                    if branch_regs[dst].umin <= branch_regs[dst].umax:
                        stack.append((target_pc, branch_regs, list(path_hist)))

                    if regs[dst].umin == imm and regs[dst].umax == imm:
                        path_ended = True
                        break
                    pc += 1

                elif op == "JA":
                    target_pc = pc + 1 + off
                    if target_pc < 0 or target_pc >= num_insns:
                        return {
                            "verified": False,
                            "rejection_reason": f"JUMP_TARGET_OUT_OF_BOUNDS_{target_pc}",
                            "failing_pc": pc,
                            "insns_processed": self.insns_processed,
                            "branches_pruned": self.branches_pruned
                        }
                    pc = target_pc

                elif op == "EXIT":
                    if regs[0].type == RegType.NOT_INIT:
                        return {
                            "verified": False,
                            "rejection_reason": "EXIT_WITHOUT_RETURN_VAL_IN_R0",
                            "failing_pc": pc,
                            "insns_processed": self.insns_processed,
                            "branches_pruned": self.branches_pruned
                        }
                    for hist_pc, hist_regs in path_hist:
                        if hist_pc not in self.explored_states:
                            self.explored_states[hist_pc] = []
                        self.explored_states[hist_pc].append(hist_regs)
                    path_ended = True
                    break

                else:
                    return {
                        "verified": False,
                        "rejection_reason": f"UNKNOWN_OPCODE_{op}",
                        "failing_pc": pc,
                        "insns_processed": self.insns_processed,
                        "branches_pruned": self.branches_pruned
                    }

            if not path_ended and pc >= num_insns:
                return {
                    "verified": False,
                    "rejection_reason": "PROGRAM_FELL_OFF_END_WITHOUT_EXIT",
                    "failing_pc": num_insns - 1,
                    "insns_processed": self.insns_processed,
                    "branches_pruned": self.branches_pruned
                }

        return {
            "verified": True,
            "insns_processed": self.insns_processed,
            "branches_pruned": self.branches_pruned,
            "paths_explored": self.paths_explored,
            "status": "PROGRAM_VERIFIED_SAFE"
        }

def main():
    raw_data = sys.stdin.read().strip()
    if not raw_data:
        return
    input_data = json.loads(raw_data)
    config = input_data.get("config", {})
    instructions = input_data.get("instructions", [])
    verifier = BPFVerifier(config)
    res = verifier.verify(instructions)
    print(json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    main()
