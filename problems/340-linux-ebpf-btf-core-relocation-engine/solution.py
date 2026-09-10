# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #340: Linux Kernel eBPF CO-RE BTF Relocation Engine.
"""
import sys
import json

sys.stdout.reconfigure(encoding="utf-8")

class EbpfBtfCoreRelocationEngine:
    def __init__(self, target_btf):
        self.target_btf = target_btf
        self.name_to_ids = {}
        for tid, tinfo in target_btf.get("types", {}).items():
            tname = tinfo.get("name", "")
            if tname:
                self.name_to_ids.setdefault(tname, []).append(int(tid))

    def _strip_flavor(self, name):
        idx = name.find("___")
        return name[:idx] if idx != -1 else name

    def _find_target_type(self, src_type_name):
        base_name = self._strip_flavor(src_type_name)
        candidates = []
        if base_name in self.name_to_ids:
            candidates.extend(self.name_to_ids[base_name])
        for tname, ids in self.name_to_ids.items():
            if tname.startswith(base_name + "___"):
                candidates.extend(ids)
        return candidates

    def resolve_field_path(self, src_btf, src_type_id, access_str, target_type_id):
        indices = [int(x) for x in access_str.split(":")]
        curr_src_tid = src_type_id
        path_member_names = []
        
        for idx in indices[1:]:
            curr_src_type = src_btf["types"][str(curr_src_tid)]
            members = curr_src_type.get("members", [])
            if idx >= len(members):
                return None, None, False
            mem = members[idx]
            path_member_names.append(mem["name"])
            curr_src_tid = mem["type_id"]

        curr_tgt_tid = target_type_id
        accum_offset = 0
        last_member = None

        for mname in path_member_names:
            curr_tgt_type = self.target_btf["types"][str(curr_tgt_tid)]
            found = False
            for mem in curr_tgt_type.get("members", []):
                if mem["name"] == mname:
                    accum_offset += mem["offset_bytes"]
                    curr_tgt_tid = mem["type_id"]
                    last_member = mem
                    found = True
                    break
            if not found:
                return None, None, False

        size = last_member.get("size", 0) if last_member else 0
        return accum_offset, size, True

    def relocate(self, program_data):
        src_btf = program_data["source_btf"]
        instructions = [dict(insn) for insn in program_data["instructions"]]
        relocations = program_data.get("relocations", [])
        
        relo_results = []
        success_count = 0
        
        for r in relocations:
            insn_idx = r["insn_idx"]
            src_tid = r["type_id"]
            access_str = r.get("access_str", "0")
            kind = r["kind"]
            
            src_type = src_btf["types"].get(str(src_tid))
            if not src_type:
                relo_results.append({"insn_idx": insn_idx, "kind": kind, "status": "SRC_TYPE_NOT_FOUND"})
                continue
            
            src_name = src_type.get("name", "")
            target_tids = self._find_target_type(src_name)
            
            if kind == "TYPE_EXISTS":
                val = 1 if len(target_tids) > 0 else 0
                instructions[insn_idx]["imm"] = val
                success_count += 1
                relo_results.append({"insn_idx": insn_idx, "kind": kind, "resolved_value": val, "status": "RESOLVED"})
                continue
                
            if not target_tids:
                relo_results.append({"insn_idx": insn_idx, "kind": kind, "status": "TARGET_TYPE_NOT_FOUND"})
                continue
                
            target_tid = target_tids[0]
            target_type = self.target_btf["types"][str(target_tid)]
            
            if kind == "TYPE_SIZE":
                val = target_type.get("size", 0)
                instructions[insn_idx]["imm"] = val
                success_count += 1
                relo_results.append({"insn_idx": insn_idx, "kind": kind, "resolved_value": val, "status": "RESOLVED"})
                continue
                
            offset, size, exists = self.resolve_field_path(src_btf, src_tid, access_str, target_tid)
            
            if kind == "FIELD_EXISTS":
                val = 1 if exists else 0
                instructions[insn_idx]["imm"] = val
                success_count += 1
                relo_results.append({"insn_idx": insn_idx, "kind": kind, "resolved_value": val, "status": "RESOLVED"})
            elif kind == "FIELD_BYTE_OFFSET":
                if not exists:
                    relo_results.append({"insn_idx": insn_idx, "kind": kind, "status": "FIELD_NOT_FOUND"})
                else:
                    instructions[insn_idx]["off"] = offset
                    success_count += 1
                    relo_results.append({"insn_idx": insn_idx, "kind": kind, "resolved_offset": offset, "status": "RESOLVED"})
            elif kind == "FIELD_BYTE_SIZE":
                if not exists:
                    relo_results.append({"insn_idx": insn_idx, "kind": kind, "status": "FIELD_NOT_FOUND"})
                else:
                    instructions[insn_idx]["imm"] = size
                    success_count += 1
                    relo_results.append({"insn_idx": insn_idx, "kind": kind, "resolved_size": size, "status": "RESOLVED"})
            else:
                relo_results.append({"insn_idx": insn_idx, "kind": kind, "status": "UNKNOWN_KIND"})

        return {
            "patched_instructions": instructions,
            "relocation_log": relo_results,
            "summary": {
                "total_relocations": len(relocations),
                "successful_relocations": success_count,
                "status": "SUCCESS" if success_count == len(relocations) else "PARTIAL_OR_FAILED"
            }
        }

def solve():
    raw_data = sys.stdin.read().strip()
    if not raw_data:
        return
    data = json.loads(raw_data)
    engine = EbpfBtfCoreRelocationEngine(data["target_btf"])
    result = engine.relocate(data["program"])
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    solve()
