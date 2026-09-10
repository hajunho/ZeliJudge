import sys
import json

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def find_type_by_name(btf, name, kind=None):
    for tid, tobj in btf.items():
        if tobj.get("name") == name:
            if kind is None or tobj.get("kind") == kind:
                return tid, tobj
    return None, None

def resolve_target_path(target_btf, root_type_name, path):
    tid, tobj = find_type_by_name(target_btf, root_type_name, "STRUCT")
    if not tid:
        return {"exists": False}
        
    curr_tid = str(tid)
    total_byte_offset = 0
    curr_member = None
    
    for step in path:
        if curr_tid not in target_btf:
            return {"exists": False}
        curr_tobj = target_btf[curr_tid]
        
        while curr_tobj.get("kind") in ("PTR", "TYPEDEF", "VOLATILE", "CONST"):
            curr_tid = str(curr_tobj.get("type_id"))
            if curr_tid not in target_btf:
                return {"exists": False}
            curr_tobj = target_btf[curr_tid]
            
        if curr_tobj.get("kind") != "STRUCT":
            return {"exists": False}
            
        members = curr_tobj.get("members", [])
        found = None
        if isinstance(step, int):
            if 0 <= step < len(members):
                found = members[step]
        else:
            for m in members:
                if m.get("name") == step:
                    found = m
                    break
                    
        if not found:
            return {"exists": False}
            
        total_byte_offset += found.get("offset", 0)
        curr_member = found
        curr_tid = str(found.get("type_id"))
        
    final_tobj = target_btf.get(curr_tid, {})
    while final_tobj.get("kind") in ("TYPEDEF", "VOLATILE", "CONST"):
        curr_tid = str(final_tobj.get("type_id"))
        final_tobj = target_btf.get(curr_tid, {})
        
    byte_size = final_tobj.get("size", 0)
    bit_offset = curr_member.get("bit_offset", 0)
    bit_size = curr_member.get("bit_size", 0)
    
    return {
        "exists": True,
        "byte_offset": total_byte_offset,
        "byte_size": byte_size,
        "bit_offset": bit_offset,
        "bit_size": bit_size,
        "final_type_id": curr_tid,
        "final_type_kind": final_tobj.get("kind", "")
    }

def solve(data):
    target_btf = data.get("target_btf", {})
    instructions = [dict(insn) for insn in data.get("instructions", [])]
    relocations = data.get("relocations", [])
    
    insn_map = {insn["insn_idx"]: insn for insn in instructions}
    
    relo_details = []
    success_count = 0
    fail_count = 0
    
    for r in relocations:
        i_idx = r.get("insn_idx")
        kind = r.get("kind")
        root_name = r.get("root_type_name", "")
        path = r.get("access_path", [])
        allow_missing = r.get("allow_missing", False)
        
        target_insn = insn_map.get(i_idx)
        if not target_insn:
            fail_count += 1
            relo_details.append({
                "insn_idx": i_idx,
                "kind": kind,
                "status": "FAILED_INSN_NOT_FOUND"
            })
            continue
            
        if kind == "TYPE_EXISTS":
            tid, _ = find_type_by_name(target_btf, root_name)
            val = 1 if tid else 0
            orig = target_insn.get("imm", 0)
            target_insn["imm"] = val
            success_count += 1
            relo_details.append({
                "insn_idx": i_idx,
                "kind": kind,
                "root_type": root_name,
                "status": "SUCCESS",
                "original_val": orig,
                "relocated_val": val,
                "patched_field": "imm"
            })
        elif kind == "TYPE_SIZE":
            tid, tobj = find_type_by_name(target_btf, root_name)
            if tid:
                val = tobj.get("size", 0)
                orig = target_insn.get("imm", 0)
                target_insn["imm"] = val
                success_count += 1
                relo_details.append({
                    "insn_idx": i_idx,
                    "kind": kind,
                    "root_type": root_name,
                    "status": "SUCCESS",
                    "original_val": orig,
                    "relocated_val": val,
                    "patched_field": "imm"
                })
            else:
                if allow_missing:
                    orig = target_insn.get("imm", 0)
                    target_insn["imm"] = 0
                    success_count += 1
                    relo_details.append({
                        "insn_idx": i_idx, "kind": kind, "root_type": root_name,
                        "status": "SUCCESS_ZERO_FALLBACK", "original_val": orig,
                        "relocated_val": 0, "patched_field": "imm"
                    })
                else:
                    fail_count += 1
                    relo_details.append({
                        "insn_idx": i_idx, "kind": kind, "root_type": root_name,
                        "status": "FAILED_TYPE_NOT_FOUND"
                    })
        elif kind in ("FIELD_BYTE_OFFSET", "FIELD_BYTE_SIZE", "FIELD_EXISTS", "FIELD_BIT_OFFSET", "FIELD_BIT_SIZE"):
            res = resolve_target_path(target_btf, root_name, path)
            exists = res["exists"]
            
            if kind == "FIELD_EXISTS":
                val = 1 if exists else 0
                orig = target_insn.get("imm", 0)
                target_insn["imm"] = val
                success_count += 1
                relo_details.append({
                    "insn_idx": i_idx,
                    "kind": kind,
                    "root_type": root_name,
                    "access_path": path,
                    "status": "SUCCESS",
                    "original_val": orig,
                    "relocated_val": val,
                    "patched_field": "imm"
                })
            elif not exists:
                if allow_missing:
                    patched_f = "off" if target_insn.get("op") in ("LDX", "STX", "LD", "ST") else "imm"
                    orig = target_insn.get(patched_f, 0)
                    target_insn[patched_f] = 0
                    success_count += 1
                    relo_details.append({
                        "insn_idx": i_idx, "kind": kind, "root_type": root_name, "access_path": path,
                        "status": "SUCCESS_ZERO_FALLBACK", "original_val": orig,
                        "relocated_val": 0, "patched_field": patched_f
                    })
                else:
                    fail_count += 1
                    relo_details.append({
                        "insn_idx": i_idx, "kind": kind, "root_type": root_name, "access_path": path,
                        "status": "FAILED_FIELD_NOT_FOUND"
                    })
            else:
                if kind == "FIELD_BYTE_OFFSET":
                    val = res["byte_offset"]
                    if target_insn.get("op") in ("LDX", "STX", "LD", "ST"):
                        orig = target_insn.get("off", 0)
                        target_insn["off"] = val
                        patched_f = "off"
                    else:
                        orig = target_insn.get("imm", 0)
                        target_insn["imm"] = val
                        patched_f = "imm"
                elif kind == "FIELD_BYTE_SIZE":
                    val = res["byte_size"]
                    orig = target_insn.get("imm", 0)
                    target_insn["imm"] = val
                    patched_f = "imm"
                elif kind == "FIELD_BIT_OFFSET":
                    val = res["bit_offset"]
                    orig = target_insn.get("imm", 0)
                    target_insn["imm"] = val
                    patched_f = "imm"
                elif kind == "FIELD_BIT_SIZE":
                    val = res["bit_size"]
                    orig = target_insn.get("imm", 0)
                    target_insn["imm"] = val
                    patched_f = "imm"
                    
                success_count += 1
                relo_details.append({
                    "insn_idx": i_idx,
                    "kind": kind,
                    "root_type": root_name,
                    "access_path": path,
                    "status": "SUCCESS",
                    "original_val": orig,
                    "relocated_val": val,
                    "patched_field": patched_f
                })
                
    return {
        "relocation_summary": {
            "total_relocations": len(relocations),
            "successful_relocations": success_count,
            "failed_relocations": fail_count
        },
        "relocation_details": relo_details,
        "patched_instructions": instructions
    }

def main():
    raw = sys.stdin.read()
    if not raw.strip():
        return
    data = json.loads(raw)
    res = solve(data)
    print(json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    main()
