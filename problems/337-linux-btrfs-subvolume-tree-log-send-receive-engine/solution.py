import sys
import json
import copy

def run_btrfs_engine(data):
    fs_config = data.get("filesystem_config", {})
    curr_gen = int(fs_config.get("initial_generation", 100))
    
    subvols = {}
    init_subvols = data.get("initial_subvolumes", [])
    for s in init_subvols:
        sid = s["subvol_id"]
        subvols[sid] = {
            "subvol_id": sid,
            "name": s["name"],
            "generation": int(s.get("generation", curr_gen)),
            "is_readonly": bool(s.get("is_readonly", False)),
            "parent_uuid": s.get("parent_uuid", None),
            "files": {f["path"]: copy.deepcopy(f) for f in s.get("files", [])}
        }

    tree_log = {}

    stats = {
        "snapshots_created": 0,
        "cow_extents_allocated": 0,
        "fsync_log_items_written": 0,
        "tree_log_replays": 0,
        "transaction_commits": 0,
        "send_streams_generated": 0,
        "bytes_sent": 0
    }

    operations = data.get("operations", [])
    op_results = []

    for op_item in operations:
        op = op_item["op"]

        if op == "create_subvol":
            sid = op_item["subvol_id"]
            name = op_item["name"]
            if sid in subvols:
                op_results.append({"op": op, "subvol_id": sid, "status": "EEXIST"})
            else:
                subvols[sid] = {
                    "subvol_id": sid,
                    "name": name,
                    "generation": curr_gen,
                    "is_readonly": False,
                    "parent_uuid": None,
                    "files": {}
                }
                op_results.append({
                    "op": op,
                    "subvol_id": sid,
                    "name": name,
                    "status": "SUCCESS",
                    "generation": curr_gen
                })

        elif op == "create_snapshot":
            src_id = op_item["source_subvol_id"]
            tgt_id = op_item["target_subvol_id"]
            tgt_name = op_item["target_name"]
            ro = bool(op_item.get("readonly", False))

            if src_id not in subvols:
                op_results.append({"op": op, "status": "ENOENT", "error": f"Source subvol {src_id} not found"})
            elif tgt_id in subvols:
                op_results.append({"op": op, "status": "EEXIST", "error": f"Target subvol {tgt_id} exists"})
            else:
                src = subvols[src_id]
                new_files = {}
                for p, f in src["files"].items():
                    new_files[p] = copy.deepcopy(f)

                subvols[tgt_id] = {
                    "subvol_id": tgt_id,
                    "name": tgt_name,
                    "generation": curr_gen,
                    "is_readonly": ro,
                    "parent_uuid": f"uuid_subvol_{src_id}",
                    "files": new_files
                }
                stats["snapshots_created"] += 1
                op_results.append({
                    "op": op,
                    "source_subvol_id": src_id,
                    "target_subvol_id": tgt_id,
                    "status": "SUCCESS",
                    "is_readonly": ro,
                    "files_shared_cow": len(new_files),
                    "generation": curr_gen
                })

        elif op == "write_file":
            sid = op_item["subvol_id"]
            path = op_item["path"]
            offset = int(op_item.get("offset", 0))
            length = int(op_item.get("length", 4096))
            data_hash = op_item.get("data_hash", "ext_hash")

            if sid not in subvols:
                op_results.append({"op": op, "status": "ENOENT", "error": f"Subvol {sid} not found"})
                continue
            sv = subvols[sid]
            if sv["is_readonly"]:
                op_results.append({"op": op, "status": "EROFS", "error": "Subvolume is read-only"})
                continue

            if path not in sv["files"]:
                sv["files"][path] = {
                    "path": path,
                    "size": offset + length,
                    "generation": curr_gen,
                    "extents": []
                }
            
            f = sv["files"][path]
            new_ext = {
                "offset": offset,
                "length": length,
                "generation": curr_gen,
                "data_hash": data_hash
            }
            f["extents"].append(new_ext)
            f["size"] = max(f["size"], offset + length)
            f["generation"] = curr_gen
            stats["cow_extents_allocated"] += 1

            op_results.append({
                "op": op,
                "subvol_id": sid,
                "path": path,
                "status": "SUCCESS",
                "extent_allocated": new_ext,
                "new_size": f["size"],
                "generation": curr_gen
            })

        elif op == "fsync_file":
            sid = op_item["subvol_id"]
            path = op_item["path"]

            if sid not in subvols or path not in subvols[sid]["files"]:
                op_results.append({"op": op, "status": "ENOENT"})
                continue

            f = subvols[sid]["files"][path]
            if sid not in tree_log:
                tree_log[sid] = {}
            
            tree_log[sid][path] = copy.deepcopy(f)
            stats["fsync_log_items_written"] += 1

            op_results.append({
                "op": op,
                "subvol_id": sid,
                "path": path,
                "status": "SUCCESS",
                "tree_log_persisted": True,
                "logged_extents_count": len(f["extents"])
            })

        elif op == "commit_transaction":
            curr_gen += 1
            stats["transaction_commits"] += 1
            cleared_logs = sum(len(items) for items in tree_log.values())
            tree_log.clear()

            op_results.append({
                "op": op,
                "status": "SUCCESS",
                "new_generation": curr_gen,
                "discarded_tree_log_items": cleared_logs
            })

        elif op == "simulate_crash_and_replay":
            replayed_count = 0
            for sid, items in tree_log.items():
                if sid in subvols:
                    for p, logged_f in items.items():
                        subvols[sid]["files"][p] = copy.deepcopy(logged_f)
                        replayed_count += 1
            stats["tree_log_replays"] += replayed_count
            tree_log.clear()

            op_results.append({
                "op": op,
                "status": "SUCCESS",
                "replayed_inodes": replayed_count
            })

        elif op == "btrfs_send":
            parent_id = op_item.get("parent_subvol_id", None)
            target_id = op_item["target_subvol_id"]

            if target_id not in subvols:
                op_results.append({"op": op, "status": "ENOENT", "error": f"Target subvol {target_id} not found"})
                continue
            tgt = subvols[target_id]
            if not tgt["is_readonly"]:
                op_results.append({"op": op, "status": "EINVAL", "error": "btrfs send requires read-only subvolume"})
                continue

            commands = []
            bytes_stream = 0

            if parent_id is not None and parent_id in subvols:
                commands.append({
                    "cmd": "BTRFS_SEND_CMD_SNAPSHOT",
                    "subvol_name": tgt["name"],
                    "parent_uuid": f"uuid_subvol_{parent_id}"
                })
                parent_files = subvols[parent_id]["files"]
            else:
                commands.append({
                    "cmd": "BTRFS_SEND_CMD_SUBVOL",
                    "subvol_name": tgt["name"]
                })
                parent_files = {}

            for p, f in tgt["files"].items():
                if p not in parent_files:
                    commands.append({"cmd": "BTRFS_SEND_CMD_MKFILE", "path": p})
                    for ext in f["extents"]:
                        commands.append({
                            "cmd": "BTRFS_SEND_CMD_WRITE",
                            "path": p,
                            "offset": ext["offset"],
                            "length": ext["length"],
                            "data_hash": ext["data_hash"]
                        })
                        bytes_stream += ext["length"]
                else:
                    p_exts = parent_files[p]["extents"]
                    if f["extents"] != p_exts:
                        for ext in f["extents"]:
                            if ext in p_exts:
                                commands.append({
                                    "cmd": "BTRFS_SEND_CMD_CLONE",
                                    "path": p,
                                    "offset": ext["offset"],
                                    "length": ext["length"],
                                    "clone_path": p
                                })
                            else:
                                commands.append({
                                    "cmd": "BTRFS_SEND_CMD_WRITE",
                                    "path": p,
                                    "offset": ext["offset"],
                                    "length": ext["length"],
                                    "data_hash": ext["data_hash"]
                                })
                                bytes_stream += ext["length"]

            for p in parent_files:
                if p not in tgt["files"]:
                    commands.append({"cmd": "BTRFS_SEND_CMD_UNLINK", "path": p})

            stats["send_streams_generated"] += 1
            stats["bytes_sent"] += bytes_stream

            op_results.append({
                "op": op,
                "target_subvol_id": target_id,
                "parent_subvol_id": parent_id,
                "status": "SUCCESS",
                "command_count": len(commands),
                "stream_commands": commands,
                "stream_data_bytes": bytes_stream
            })

        elif op == "btrfs_receive":
            stream_cmds = op_item.get("stream_commands", [])
            dest_id = op_item["dest_subvol_id"]
            dest_name = op_item["dest_name"]

            rec_subvol = {
                "subvol_id": dest_id,
                "name": dest_name,
                "generation": curr_gen,
                "is_readonly": True,
                "files": {}
            }

            for cmd_obj in stream_cmds:
                c = cmd_obj["cmd"]
                if c in ("BTRFS_SEND_CMD_SUBVOL", "BTRFS_SEND_CMD_SNAPSHOT"):
                    pass
                elif c == "BTRFS_SEND_CMD_MKFILE":
                    p = cmd_obj["path"]
                    rec_subvol["files"][p] = {"path": p, "size": 0, "extents": []}
                elif c == "BTRFS_SEND_CMD_WRITE":
                    p = cmd_obj["path"]
                    if p not in rec_subvol["files"]:
                        rec_subvol["files"][p] = {"path": p, "size": 0, "extents": []}
                    ext = {
                        "offset": cmd_obj["offset"],
                        "length": cmd_obj["length"],
                        "data_hash": cmd_obj["data_hash"]
                    }
                    rec_subvol["files"][p]["extents"].append(ext)
                    rec_subvol["files"][p]["size"] = max(rec_subvol["files"][p]["size"], ext["offset"] + ext["length"])
                elif c == "BTRFS_SEND_CMD_CLONE":
                    p = cmd_obj["path"]
                    ext = {
                        "offset": cmd_obj["offset"],
                        "length": cmd_obj["length"],
                        "data_hash": "cloned"
                    }
                    rec_subvol["files"][p]["extents"].append(ext)
                    rec_subvol["files"][p]["size"] = max(rec_subvol["files"][p]["size"], ext["offset"] + ext["length"])
                elif c == "BTRFS_SEND_CMD_UNLINK":
                    p = cmd_obj["path"]
                    if p in rec_subvol["files"]:
                        del rec_subvol["files"][p]

            subvols[dest_id] = rec_subvol
            op_results.append({
                "op": op,
                "dest_subvol_id": dest_id,
                "dest_name": dest_name,
                "status": "SUCCESS",
                "reconstructed_files": len(rec_subvol["files"])
            })

    return {
        "operations": op_results,
        "btrfs_subsystem_metrics": stats,
        "filesystem_state": {
            "current_generation": curr_gen,
            "total_subvolumes": len(subvols),
            "active_tree_log_inodes": sum(len(items) for items in tree_log.values())
        }
    }

def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    result = run_btrfs_engine(data)
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
