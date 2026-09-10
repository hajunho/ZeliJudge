import sys
import json

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

class BpfCoreReloEngine:
    def __init__(self, config=None):
        self.config = config or {}
        self.local_btf = {}
        self.target_btf = {}
        self.instructions = []
        self.relocations = []
        self.stats = {
            "total_relos_processed": 0,
            "successful_relos": 0,
            "failed_relos": 0,
            "instructions_patched": 0
        }

    def load_local_btf(self, types):
        self.local_btf = types

    def load_target_btf(self, types):
        self.target_btf = types

    def load_program(self, instructions, relocations):
        self.instructions = [dict(insn) for insn in instructions]
        self.relocations = relocations

    def _resolve_access_path(self, btf, root_type_name, access_str):
        indices = [int(x) for x in access_str.split(":")]
        curr_name = root_type_name
        path_names = []
        total_offset = 0

        for idx in indices:
            tdef = btf.get(curr_name)
            if not tdef:
                return None
            members = tdef.get("members", [])
            if idx >= len(members):
                return None
            m = members[idx]
            path_names.append(m["name"])
            total_offset += m.get("offset", 0)
            curr_name = m.get("type")

        last_idx = indices[-1]
        final_size = members[last_idx].get("size", 0) if last_idx < len(members) else 0

        return {
            "path_names": path_names,
            "total_offset": total_offset,
            "final_type": curr_name,
            "final_size": final_size
        }

    def _match_target_path(self, target_btf, root_type_name, path_names):
        curr_name = root_type_name
        total_offset = 0
        final_size = 0
        final_type = None

        for mname in path_names:
            tdef = target_btf.get(curr_name)
            if not tdef:
                return None
            members = tdef.get("members", [])
            matched = None
            for m in members:
                if m["name"] == mname:
                    matched = m
                    break
            if not matched:
                return None
            total_offset += matched.get("offset", 0)
            final_size = matched.get("size", 0)
            final_type = matched.get("type")
            curr_name = final_type

        return {
            "total_offset": total_offset,
            "final_size": final_size,
            "final_type": final_type
        }

    def run_relocations(self):
        relo_results = []
        for r in self.relocations:
            insn_idx = r["insn_idx"]
            kind = r["kind"]
            root_type = r["type_name"]
            access_str = r.get("access_str", "")

            self.stats["total_relos_processed"] += 1
            insn = self.instructions[insn_idx]

            if kind == "FIELD_BYTE_OFFSET":
                loc = self._resolve_access_path(self.local_btf, root_type, access_str)
                tgt = self._match_target_path(self.target_btf, root_type, loc["path_names"]) if loc else None
                if tgt is not None:
                    old_off = insn.get("off", 0)
                    new_off = tgt["total_offset"]
                    insn["off"] = new_off
                    self.stats["successful_relos"] += 1
                    self.stats["instructions_patched"] += 1
                    relo_results.append({
                        "insn_idx": insn_idx,
                        "kind": kind,
                        "status": "SUCCESS",
                        "old_val": old_off,
                        "new_val": new_off
                    })
                else:
                    self.stats["failed_relos"] += 1
                    relo_results.append({
                        "insn_idx": insn_idx,
                        "kind": kind,
                        "status": "FIELD_NOT_FOUND"
                    })

            elif kind == "FIELD_BYTE_SIZE":
                loc = self._resolve_access_path(self.local_btf, root_type, access_str)
                tgt = self._match_target_path(self.target_btf, root_type, loc["path_names"]) if loc else None
                if tgt is not None:
                    old_imm = insn.get("imm", 0)
                    new_imm = tgt["final_size"]
                    insn["imm"] = new_imm
                    self.stats["successful_relos"] += 1
                    self.stats["instructions_patched"] += 1
                    relo_results.append({
                        "insn_idx": insn_idx,
                        "kind": kind,
                        "status": "SUCCESS",
                        "old_val": old_imm,
                        "new_val": new_imm
                    })
                else:
                    self.stats["failed_relos"] += 1
                    relo_results.append({
                        "insn_idx": insn_idx,
                        "kind": kind,
                        "status": "FIELD_NOT_FOUND"
                    })

            elif kind == "FIELD_EXISTS":
                loc = self._resolve_access_path(self.local_btf, root_type, access_str)
                tgt = self._match_target_path(self.target_btf, root_type, loc["path_names"]) if loc else None
                exists = 1 if tgt is not None else 0
                old_imm = insn.get("imm", 0)
                insn["imm"] = exists
                self.stats["successful_relos"] += 1
                self.stats["instructions_patched"] += 1
                relo_results.append({
                    "insn_idx": insn_idx,
                    "kind": kind,
                    "status": "SUCCESS",
                    "old_val": old_imm,
                    "new_val": exists
                })

            elif kind == "TYPE_EXISTS":
                exists = 1 if root_type in self.target_btf else 0
                old_imm = insn.get("imm", 0)
                insn["imm"] = exists
                self.stats["successful_relos"] += 1
                self.stats["instructions_patched"] += 1
                relo_results.append({
                    "insn_idx": insn_idx,
                    "kind": kind,
                    "status": "SUCCESS",
                    "old_val": old_imm,
                    "new_val": exists
                })

            elif kind == "TYPE_SIZE":
                if root_type in self.target_btf:
                    sz = self.target_btf[root_type].get("size", 0)
                    old_imm = insn.get("imm", 0)
                    insn["imm"] = sz
                    self.stats["successful_relos"] += 1
                    self.stats["instructions_patched"] += 1
                    relo_results.append({
                        "insn_idx": insn_idx,
                        "kind": kind,
                        "status": "SUCCESS",
                        "old_val": old_imm,
                        "new_val": sz
                    })
                else:
                    self.stats["failed_relos"] += 1
                    relo_results.append({
                        "insn_idx": insn_idx,
                        "kind": kind,
                        "status": "TYPE_NOT_FOUND"
                    })

            elif kind == "ENUMVAL_VALUE":
                enum_name = root_type
                val_name = r.get("val_name", "")
                tdef = self.target_btf.get(enum_name, {})
                vals = tdef.get("values", {})
                if val_name in vals:
                    val = vals[val_name]
                    old_imm = insn.get("imm", 0)
                    insn["imm"] = val
                    self.stats["successful_relos"] += 1
                    self.stats["instructions_patched"] += 1
                    relo_results.append({
                        "insn_idx": insn_idx,
                        "kind": kind,
                        "status": "SUCCESS",
                        "old_val": old_imm,
                        "new_val": val
                    })
                else:
                    self.stats["failed_relos"] += 1
                    relo_results.append({
                        "insn_idx": insn_idx,
                        "kind": kind,
                        "status": "ENUMVAL_NOT_FOUND"
                    })

        return relo_results

    def run(self, ops):
        results = []
        for idx, op in enumerate(ops):
            t = op["type"]
            if t == "LOAD_LOCAL_BTF":
                self.load_local_btf(op["types"])
                results.append({
                    "op_index": idx,
                    "type": t,
                    "count": len(op["types"]),
                    "status": "LOADED"
                })
            elif t == "LOAD_TARGET_BTF":
                self.load_target_btf(op["types"])
                results.append({
                    "op_index": idx,
                    "type": t,
                    "count": len(op["types"]),
                    "status": "LOADED"
                })
            elif t == "LOAD_PROGRAM":
                self.load_program(op["instructions"], op["relocations"])
                results.append({
                    "op_index": idx,
                    "type": t,
                    "instructions_count": len(op["instructions"]),
                    "relocations_count": len(op["relocations"]),
                    "status": "LOADED"
                })
            elif t == "RUN_RELOCATIONS":
                relos = self.run_relocations()
                results.append({
                    "op_index": idx,
                    "type": t,
                    "relocations": relos,
                    "patched_instructions": self.instructions
                })

        return {
            "operation_results": results,
            "final_instructions": self.instructions,
            "summary": {
                "total_operations": len(ops),
                "stats": self.stats
            }
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    engine = BpfCoreReloEngine(data.get("config", {}))
    output = engine.run(data.get("operations", []))
    print(json.dumps(output, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
