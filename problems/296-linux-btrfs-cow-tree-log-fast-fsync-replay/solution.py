# -*- coding: utf-8 -*-
"""
ZeliJudge Pro Track Problem #296: Linux Btrfs Copy-on-Write (CoW) Tree-Log Fast fsync & Crash Replay
https://github.com/hajunho/ZeliJudge
"""

import sys
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

class BtrfsEngine:
    def __init__(self, config):
        self.transid = 1
        self.log_transid = 0
        
        self.committed_tree = {}
        self.memory_tree = {}
        self.log_tree = {}
        self.has_log_tree = False
        
        self.stats = {
            "fast_fsync_log_count": 0,
            "full_trans_commit_count": 0,
            "replayed_extents_count": 0,
            "recovered_files_count": 0,
            "unfsynced_lost_extents": 0
        }
        self.event_log = []

    def init_file(self, inode_id, size=0):
        file_obj = {"size": size, "extents": []}
        self.committed_tree[inode_id] = {
            "size": size, "extents": []
        }
        self.memory_tree[inode_id] = {
            "size": size, "extents": []
        }

    def write_extent(self, time_us, inode_id, offset, length, disk_block):
        if inode_id not in self.memory_tree:
            self.init_file(inode_id)
        f = self.memory_tree[inode_id]
        f["extents"].append({"offset": offset, "len": length, "disk_block": disk_block})
        f["size"] = max(f["size"], offset + length)
        self.event_log.append({
            "time_us": time_us, "event": "WRITE", "inode_id": inode_id,
            "offset": offset, "len": length, "block": disk_block
        })

    def truncate_file(self, time_us, inode_id, new_size):
        if inode_id not in self.memory_tree:
            self.init_file(inode_id)
        f = self.memory_tree[inode_id]
        f["size"] = new_size
        # Trim extents beyond new_size
        valid_extents = []
        for ext in f["extents"]:
            if ext["offset"] < new_size:
                if ext["offset"] + ext["len"] > new_size:
                    ext["len"] = new_size - ext["offset"]
                valid_extents.append(ext)
        f["extents"] = valid_extents
        self.event_log.append({
            "time_us": time_us, "event": "TRUNCATE", "inode_id": inode_id, "new_size": new_size
        })

    def fsync_file(self, time_us, inode_id, force_full_commit=False):
        if force_full_commit:
            self.commit_transaction(time_us)
            self.event_log.append({
                "time_us": time_us, "event": "FSYNC_FALLBACK_FULL_COMMIT", "inode_id": inode_id
            })
            return "FULL_TRANSACTION_COMMIT"

        self.stats["fast_fsync_log_count"] += 1
        self.has_log_tree = True
        self.log_transid = self.transid

        if inode_id in self.memory_tree:
            self.log_tree[inode_id] = {
                "size": self.memory_tree[inode_id]["size"],
                "extents": [dict(e) for e in self.memory_tree[inode_id]["extents"]]
            }

        self.event_log.append({
            "time_us": time_us, "event": "FAST_FSYNC_TREE_LOG", "inode_id": inode_id,
            "log_transid": self.log_transid
        })
        return "FAST_TREE_LOG_SYNC"

    def commit_transaction(self, time_us=0.0):
        self.stats["full_trans_commit_count"] += 1
        for inode_id, f in self.memory_tree.items():
            self.committed_tree[inode_id] = {
                "size": f["size"],
                "extents": [dict(e) for e in f["extents"]]
            }
        self.log_tree = {}
        self.has_log_tree = False
        self.transid += 1
        self.log_transid = 0
        self.event_log.append({
            "time_us": time_us, "event": "TRANSACTION_COMMIT", "new_transid": self.transid
        })

    def crash_and_replay(self, time_us=0.0):
        # Count un-fsynced lost extents in memory
        for inode_id, f in self.memory_tree.items():
            comm = self.committed_tree.get(inode_id, {"extents": []})
            logged = self.log_tree.get(inode_id, {"extents": []})
            diff = len(f["extents"]) - max(len(comm["extents"]), len(logged["extents"]))
            if diff > 0:
                self.stats["unfsynced_lost_extents"] += diff

        # Memory wiped!
        self.memory_tree = {}
        for inode_id, f in self.committed_tree.items():
            self.memory_tree[inode_id] = {
                "size": f["size"],
                "extents": [dict(e) for e in f["extents"]]
            }

        # Replay Tree Log
        replay_status = "NO_VALID_LOG_TREE"
        if self.has_log_tree and self.log_transid == self.transid:
            replay_status = "REPLAY_SUCCESSFUL"
            for inode_id, log_f in self.log_tree.items():
                self.stats["recovered_files_count"] += 1
                self.stats["replayed_extents_count"] += len(log_f["extents"])
                self.committed_tree[inode_id] = {
                    "size": log_f["size"],
                    "extents": [dict(e) for e in log_f["extents"]]
                }
                self.memory_tree[inode_id] = {
                    "size": log_f["size"],
                    "extents": [dict(e) for e in log_f["extents"]]
                }
            self.log_tree = {}
            self.has_log_tree = False

        self.event_log.append({
            "time_us": time_us, "event": "CRASH_AND_REPLAY", "status": replay_status
        })
        return replay_status

def simulate_btrfs(data):
    config = data.get("config", {})
    initial_files = data.get("initial_files", [])
    events = data.get("events", [])

    fs = BtrfsEngine(config)

    for f in initial_files:
        fs.init_file(f["inode_id"], f.get("size", 0))

    for ev in events:
        ev_type = ev.get("type")
        time_us = ev.get("time_us", 0.0)

        if ev_type == "WRITE":
            fs.write_extent(time_us, ev.get("inode_id"), ev.get("offset", 0), ev.get("len", 4096), ev.get("block"))
        elif ev_type == "TRUNCATE":
            fs.truncate_file(time_us, ev.get("inode_id"), ev.get("new_size", 0))
        elif ev_type == "FSYNC":
            fs.fsync_file(time_us, ev.get("inode_id"), ev.get("force_full_commit", False))
        elif ev_type == "COMMIT_TRANSACTION":
            fs.commit_transaction(time_us)
        elif ev_type == "CRASH":
            fs.crash_and_replay(time_us)

    # Compile final committed state
    committed_state = {}
    for inode_id in sorted(fs.committed_tree.keys()):
        f = fs.committed_tree[inode_id]
        committed_state[f"inode_{inode_id}"] = {
            "size": f["size"],
            "extents_count": len(f["extents"]),
            "extents": f["extents"]
        }

    status = "HEALTHY_CONSISTENT"
    anomalies = []
    if fs.stats["unfsynced_lost_extents"] > 0:
        status = "CRASH_ROLLBACK_OCCURRED"
        anomalies.append("UNFSYNCED_EXTENTS_DISCARDED")

    return {
        "metrics": fs.stats,
        "current_transid": fs.transid,
        "committed_files": committed_state,
        "diagnostics": {
            "status": status,
            "anomalies": anomalies
        },
        "event_log_sample": fs.event_log[:15]
    }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    result = simulate_btrfs(data)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))

if __name__ == "__main__":
    main()
