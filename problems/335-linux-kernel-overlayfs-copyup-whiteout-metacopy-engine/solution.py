import sys
import json

def run_overlayfs_engine(data):
    config = data.get("config", {})
    metacopy_enabled = bool(config.get("metacopy_enabled", True))
    
    initial = data.get("initial_layers", {})
    lower_layers = initial.get("lower_layers", [])
    upper_entries_init = initial.get("upper_entries", [])
    operations = data.get("operations", [])

    upper = {}
    for entry in upper_entries_init:
        p = entry["path"]
        upper[p] = dict(entry)

    lowers = []
    for l in lower_layers:
        lid = l["layer_id"]
        entries_dict = {}
        for e in l.get("entries", []):
            entries_dict[e["path"]] = dict(e)
        lowers.append({"layer_id": lid, "entries": entries_dict})

    stats = {
        "full_copyups": 0,
        "metacopy_creations": 0,
        "metacopy_upgrades": 0,
        "whiteouts_created": 0,
        "bytes_copied": 0
    }

    def exists_in_lower(path):
        for l in lowers:
            if path in l["entries"]:
                return True, l["layer_id"], l["entries"][path]
        return False, None, None

    def find_entry(path):
        if path in upper:
            u = upper[path]
            if u.get("is_whiteout"):
                return "whiteout", None, None
            return "upper", "upper", u

        for l in lowers:
            if path in l["entries"]:
                return "lower", l["layer_id"], l["entries"][path]

        return "not_found", None, None

    def get_dir_children(dir_path):
        norm = dir_path.rstrip("/")
        prefix = norm + "/" if norm else "/"
        seen = {}
        whiteouts = set()
        is_opaque = False

        if norm in upper and upper[norm].get("is_opaque", False):
            is_opaque = True

        for p, ent in upper.items():
            if p != norm and p.startswith(prefix):
                rel = p[len(prefix):]
                if "/" not in rel:
                    if ent.get("is_whiteout", False):
                        whiteouts.add(rel)
                    else:
                        seen[rel] = {
                            "name": rel,
                            "type": ent["type"],
                            "layer": "upper"
                        }

        if not is_opaque:
            for l in lowers:
                for p, ent in l["entries"].items():
                    if p != norm and p.startswith(prefix):
                        rel = p[len(prefix):]
                        if "/" not in rel:
                            if rel not in whiteouts and rel not in seen:
                                seen[rel] = {
                                    "name": rel,
                                    "type": ent["type"],
                                    "layer": l["layer_id"]
                                }
        return sorted(seen.keys()), seen, is_opaque

    op_results = []

    for op_item in operations:
        op = op_item["op"]
        path = op_item["path"]

        if op == "lookup":
            loc_type, layer_id, entry = find_entry(path)
            if loc_type in ("not_found", "whiteout"):
                op_results.append({
                    "op": "lookup",
                    "path": path,
                    "status": "ENOENT",
                    "found": False
                })
            elif loc_type == "upper":
                is_meta = entry.get("is_metacopy", False)
                dtype = "metacopy_file" if is_meta else entry["type"]
                op_results.append({
                    "op": "lookup",
                    "path": path,
                    "status": "SUCCESS",
                    "found": True,
                    "location": "upper",
                    "type": dtype,
                    "size": entry.get("size", 0),
                    "mode": entry.get("mode", ""),
                    "uid": entry.get("uid", 0),
                    "gid": entry.get("gid", 0),
                    "is_metacopy": is_meta
                })
            else:
                op_results.append({
                    "op": "lookup",
                    "path": path,
                    "status": "SUCCESS",
                    "found": True,
                    "location": layer_id,
                    "type": entry["type"],
                    "size": entry.get("size", 0),
                    "mode": entry.get("mode", ""),
                    "uid": entry.get("uid", 0),
                    "gid": entry.get("gid", 0),
                    "is_metacopy": False
                })

        elif op == "stat":
            loc_type, layer_id, entry = find_entry(path)
            if loc_type in ("not_found", "whiteout"):
                op_results.append({"op": "stat", "path": path, "status": "ENOENT"})
            else:
                is_meta = entry.get("is_metacopy", False)
                data_layer = entry.get("data_layer", layer_id)
                op_results.append({
                    "op": "stat",
                    "path": path,
                    "status": "SUCCESS",
                    "type": entry["type"],
                    "size": entry.get("size", 0),
                    "mode": entry.get("mode", ""),
                    "uid": entry.get("uid", 0),
                    "gid": entry.get("gid", 0),
                    "content_hash": entry.get("content_hash", ""),
                    "is_metacopy": is_meta,
                    "location": layer_id,
                    "data_origin_layer": data_layer
                })

        elif op == "read":
            loc_type, layer_id, entry = find_entry(path)
            if loc_type in ("not_found", "whiteout"):
                op_results.append({"op": "read", "path": path, "status": "ENOENT"})
            elif entry["type"] != "file":
                op_results.append({"op": "read", "path": path, "status": "EISDIR"})
            else:
                data_layer = entry.get("data_layer", layer_id)
                op_results.append({
                    "op": "read",
                    "path": path,
                    "status": "SUCCESS",
                    "size": entry.get("size", 0),
                    "content_hash": entry.get("content_hash", ""),
                    "read_from_layer": data_layer
                })

        elif op in ("chmod", "chown"):
            loc_type, layer_id, entry = find_entry(path)
            if loc_type in ("not_found", "whiteout"):
                op_results.append({"op": op, "path": path, "status": "ENOENT"})
            elif loc_type == "upper":
                if op == "chmod":
                    entry["mode"] = op_item["mode"]
                else:
                    if "uid" in op_item: entry["uid"] = op_item["uid"]
                    if "gid" in op_item: entry["gid"] = op_item["gid"]
                op_results.append({
                    "op": op,
                    "path": path,
                    "status": "SUCCESS",
                    "action": "modified_in_place",
                    "is_metacopy": entry.get("is_metacopy", False)
                })
            else:
                in_lower, low_layer, low_entry = exists_in_lower(path)
                new_mode = op_item.get("mode", low_entry.get("mode", ""))
                new_uid = op_item.get("uid", low_entry.get("uid", 0))
                new_gid = op_item.get("gid", low_entry.get("gid", 0))

                if metacopy_enabled and low_entry["type"] == "file":
                    upper[path] = {
                        "path": path,
                        "type": "file",
                        "size": low_entry.get("size", 0),
                        "mode": new_mode,
                        "uid": new_uid,
                        "gid": new_gid,
                        "content_hash": low_entry.get("content_hash", ""),
                        "is_metacopy": True,
                        "data_layer": low_layer
                    }
                    stats["metacopy_creations"] += 1
                    op_results.append({
                        "op": op,
                        "path": path,
                        "status": "SUCCESS",
                        "action": "metacopy_created",
                        "bytes_copied": 0
                    })
                else:
                    copied_bytes = low_entry.get("size", 0) if low_entry["type"] == "file" else 0
                    upper[path] = {
                        "path": path,
                        "type": low_entry["type"],
                        "size": copied_bytes,
                        "mode": new_mode,
                        "uid": new_uid,
                        "gid": new_gid,
                        "content_hash": low_entry.get("content_hash", ""),
                        "is_metacopy": False,
                        "data_layer": "upper" if low_entry["type"] == "file" else low_layer
                    }
                    stats["full_copyups"] += 1
                    stats["bytes_copied"] += copied_bytes
                    op_results.append({
                        "op": op,
                        "path": path,
                        "status": "SUCCESS",
                        "action": "full_copyup",
                        "bytes_copied": copied_bytes
                    })

        elif op == "write":
            loc_type, layer_id, entry = find_entry(path)
            new_size = op_item.get("size", 0)
            new_hash = op_item.get("content_hash", "")
            
            if loc_type in ("not_found", "whiteout"):
                upper[path] = {
                    "path": path,
                    "type": "file",
                    "size": new_size,
                    "mode": op_item.get("mode", "0644"),
                    "uid": op_item.get("uid", 0),
                    "gid": op_item.get("gid", 0),
                    "content_hash": new_hash,
                    "is_metacopy": False,
                    "data_layer": "upper"
                }
                op_results.append({
                    "op": "write",
                    "path": path,
                    "status": "SUCCESS",
                    "action": "created_in_upper",
                    "bytes_copied": 0
                })
            elif loc_type == "upper":
                if entry.get("is_metacopy", False):
                    orig_size = entry.get("size", 0)
                    stats["metacopy_upgrades"] += 1
                    stats["bytes_copied"] += orig_size
                    entry["is_metacopy"] = False
                    entry["data_layer"] = "upper"
                    entry["size"] = new_size
                    entry["content_hash"] = new_hash
                    op_results.append({
                        "op": "write",
                        "path": path,
                        "status": "SUCCESS",
                        "action": "metacopy_upgraded_to_full",
                        "bytes_copied": orig_size
                    })
                else:
                    entry["size"] = new_size
                    entry["content_hash"] = new_hash
                    op_results.append({
                        "op": "write",
                        "path": path,
                        "status": "SUCCESS",
                        "action": "written_in_place",
                        "bytes_copied": 0
                    })
            else:
                low_size = entry.get("size", 0)
                stats["full_copyups"] += 1
                stats["bytes_copied"] += low_size
                upper[path] = {
                    "path": path,
                    "type": "file",
                    "size": new_size,
                    "mode": entry.get("mode", "0644"),
                    "uid": entry.get("uid", 0),
                    "gid": entry.get("gid", 0),
                    "content_hash": new_hash,
                    "is_metacopy": False,
                    "data_layer": "upper"
                }
                op_results.append({
                    "op": "write",
                    "path": path,
                    "status": "SUCCESS",
                    "action": "full_copyup_and_write",
                    "bytes_copied": low_size
                })

        elif op == "unlink":
            loc_type, layer_id, entry = find_entry(path)
            if loc_type in ("not_found", "whiteout"):
                op_results.append({"op": "unlink", "path": path, "status": "ENOENT"})
            elif entry["type"] != "file":
                op_results.append({"op": "unlink", "path": path, "status": "EISDIR"})
            else:
                has_lower, _, _ = exists_in_lower(path)
                if has_lower:
                    upper[path] = {
                        "path": path,
                        "type": "chr",
                        "is_whiteout": True,
                        "rdev": [0, 0]
                    }
                    stats["whiteouts_created"] += 1
                    op_results.append({
                        "op": "unlink",
                        "path": path,
                        "status": "SUCCESS",
                        "action": "whiteout_created"
                    })
                else:
                    del upper[path]
                    op_results.append({
                        "op": "unlink",
                        "path": path,
                        "status": "SUCCESS",
                        "action": "deleted_from_upper"
                    })

        elif op == "rmdir":
            loc_type, layer_id, entry = find_entry(path)
            if loc_type in ("not_found", "whiteout"):
                op_results.append({"op": "rmdir", "path": path, "status": "ENOENT"})
            elif entry["type"] != "dir":
                op_results.append({"op": "rmdir", "path": path, "status": "ENOTDIR"})
            else:
                child_names, _, _ = get_dir_children(path)
                if len(child_names) > 0:
                    op_results.append({"op": "rmdir", "path": path, "status": "ENOTEMPTY"})
                else:
                    has_lower, _, _ = exists_in_lower(path)
                    if has_lower:
                        upper[path] = {
                            "path": path,
                            "type": "chr",
                            "is_whiteout": True,
                            "rdev": [0, 0]
                        }
                        stats["whiteouts_created"] += 1
                        op_results.append({
                            "op": "rmdir",
                            "path": path,
                            "status": "SUCCESS",
                            "action": "whiteout_created"
                        })
                    else:
                        if path in upper:
                            del upper[path]
                        op_results.append({
                            "op": "rmdir",
                            "path": path,
                            "status": "SUCCESS",
                            "action": "deleted_from_upper"
                        })

        elif op == "mkdir":
            loc_type, layer_id, entry = find_entry(path)
            is_opaque = bool(op_item.get("opaque", False))
            mode = op_item.get("mode", "0755")
            uid = op_item.get("uid", 0)
            gid = op_item.get("gid", 0)

            if loc_type == "whiteout":
                upper[path] = {
                    "path": path,
                    "type": "dir",
                    "mode": mode,
                    "uid": uid,
                    "gid": gid,
                    "is_opaque": is_opaque
                }
                op_results.append({
                    "op": "mkdir",
                    "path": path,
                    "status": "SUCCESS",
                    "action": "whiteout_overwritten",
                    "is_opaque": is_opaque
                })
            elif loc_type in ("upper", "lower"):
                op_results.append({"op": "mkdir", "path": path, "status": "EEXIST"})
            else:
                upper[path] = {
                    "path": path,
                    "type": "dir",
                    "mode": mode,
                    "uid": uid,
                    "gid": gid,
                    "is_opaque": is_opaque
                }
                op_results.append({
                    "op": "mkdir",
                    "path": path,
                    "status": "SUCCESS",
                    "action": "created_in_upper",
                    "is_opaque": is_opaque
                })

        elif op == "readdir":
            norm_path = path.rstrip("/")
            loc_type, layer_id, entry = find_entry(norm_path if norm_path else "/")
            if loc_type in ("not_found", "whiteout"):
                op_results.append({"op": "readdir", "path": path, "status": "ENOENT"})
            elif entry["type"] != "dir":
                op_results.append({"op": "readdir", "path": path, "status": "ENOTDIR"})
            else:
                names, entries_map, is_opaque_dir = get_dir_children(norm_path)
                items = [entries_map[k] for k in names]
                op_results.append({
                    "op": "readdir",
                    "path": path,
                    "status": "SUCCESS",
                    "count": len(items),
                    "entries": items,
                    "is_opaque": is_opaque_dir
                })

    return {
        "operations": op_results,
        "summary_metrics": stats,
        "upper_layer_state": {
            "entry_count": len(upper),
            "whiteout_count": sum(1 for e in upper.values() if e.get("is_whiteout", False)),
            "metacopy_count": sum(1 for e in upper.values() if e.get("is_metacopy", False))
        }
    }

def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    result = run_overlayfs_engine(data)
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
