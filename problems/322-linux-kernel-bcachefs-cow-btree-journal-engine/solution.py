import sys
import os
import json
import copy

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

class LinuxBcachefsEngine:
    def __init__(self, config: dict):
        self.config = copy.deepcopy(config)
        self.bucket_size_kb = int(self.config.get("bucket_size_kb", 512))
        self.total_buckets = int(self.config.get("total_buckets", 16))
        self.journal_capacity = int(self.config.get("journal_capacity", 64))

        self.buckets = []
        for bid in range(self.total_buckets):
            self.buckets.append({
                "bucket_id": bid,
                "generation": 0,
                "free_kb": self.bucket_size_kb,
                "dirty_kb": 0,
                "is_full": False
            })

        self.btree_extents = {}
        self.snapshots = {0: {"parent": None, "name": "root"}}
        self.next_snapshot_id = 1

        self.journal = []
        self.journal_seq = 0
        self.flushed_journal_seq = 0

        self.event_log = []
        self.history = []
        self.stats = {
            "cow_writes": 0,
            "extent_splits": 0,
            "bucket_allocations": 0,
            "snapshots_created": 0,
            "journal_commits": 0,
            "journal_replays": 0,
            "reclaimed_buckets": 0
        }

    def log(self, msg: str):
        self.event_log.append(msg)

    def _allocate_space(self, size_kb: int) -> dict:
        for b in self.buckets:
            if not b["is_full"] and b["free_kb"] >= size_kb:
                alloc_offset = self.bucket_size_kb - b["free_kb"]
                b["free_kb"] -= size_kb
                b["dirty_kb"] += size_kb
                if b["free_kb"] == 0:
                    b["is_full"] = True
                self.stats["bucket_allocations"] += 1
                return {
                    "bucket_id": b["bucket_id"],
                    "bucket_offset_kb": alloc_offset,
                    "generation": b["generation"],
                    "size_kb": size_kb
                }
        return None

    def _append_journal(self, op: str, payload: dict) -> int:
        self.journal_seq += 1
        entry = {
            "seq": self.journal_seq,
            "op": op,
            "payload": payload
        }
        self.journal.append(entry)
        if len(self.journal) > self.journal_capacity:
            self.journal.pop(0)
        self.stats["journal_commits"] += 1
        return self.journal_seq

    def create_snapshot(self, parent_id: int, snapshot_name: str) -> dict:
        if parent_id not in self.snapshots:
            return {"op": "CREATE_SNAPSHOT", "error": f"Parent snapshot {parent_id} not found"}

        snap_id = self.next_snapshot_id
        self.next_snapshot_id += 1
        self.snapshots[snap_id] = {
            "parent": parent_id,
            "name": snapshot_name
        }
        self.stats["snapshots_created"] += 1

        seq = self._append_journal("CREATE_SNAPSHOT", {
            "snapshot_id": snap_id,
            "parent_id": parent_id,
            "name": snapshot_name
        })

        self.log(f"CREATE_SNAPSHOT: id={snap_id} parent={parent_id} name='{snapshot_name}' seq={seq}")
        res = {
            "op": "CREATE_SNAPSHOT",
            "snapshot_id": snap_id,
            "parent_id": parent_id,
            "snapshot_name": snapshot_name,
            "journal_seq": seq
        }
        self.history.append(res)
        return res

    def write_extent(self, inode: int, offset_kb: int, size_kb: int, snapshot_id: int, data_hash: str) -> dict:
        if snapshot_id not in self.snapshots:
            return {"op": "WRITE_EXTENT", "error": f"Snapshot {snapshot_id} not found"}

        ptr = self._allocate_space(size_kb)
        if not ptr:
            return {"op": "WRITE_EXTENT", "error": "ENOSPC", "message": "No space left on device"}

        seq = self._append_journal("WRITE_EXTENT", {
            "inode": inode,
            "offset_kb": offset_kb,
            "size_kb": size_kb,
            "snapshot_id": snapshot_id,
            "ptr": ptr,
            "data_hash": data_hash
        })

        bpos_key = f"{inode}:{offset_kb}:{snapshot_id}"
        old_extent = self.btree_extents.get(bpos_key)
        if old_extent:
            self.stats["extent_splits"] += 1
            old_bid = old_extent["ptr"]["bucket_id"]
            self.buckets[old_bid]["dirty_kb"] = max(0, self.buckets[old_bid]["dirty_kb"] - old_extent["size_kb"])

        self.btree_extents[bpos_key] = {
            "inode": inode,
            "offset_kb": offset_kb,
            "size_kb": size_kb,
            "snapshot_id": snapshot_id,
            "ptr": ptr,
            "data_hash": data_hash,
            "journal_seq": seq
        }
        self.stats["cow_writes"] += 1

        self.log(f"WRITE_EXTENT: bpos=({inode},{offset_kb},{snapshot_id}) size={size_kb}KB bucket={ptr['bucket_id']} seq={seq}")
        res = {
            "op": "WRITE_EXTENT",
            "inode": inode,
            "offset_kb": offset_kb,
            "size_kb": size_kb,
            "snapshot_id": snapshot_id,
            "allocated_ptr": ptr,
            "journal_seq": seq
        }
        self.history.append(res)
        return res

    def read_extent(self, inode: int, offset_kb: int, snapshot_id: int) -> dict:
        if snapshot_id not in self.snapshots:
            return {"op": "READ_EXTENT", "error": f"Snapshot {snapshot_id} not found"}

        curr_snap = snapshot_id
        resolved_extent = None
        visited_snaps = []

        while curr_snap is not None:
            visited_snaps.append(curr_snap)
            bpos_key = f"{inode}:{offset_kb}:{curr_snap}"
            if bpos_key in self.btree_extents:
                resolved_extent = self.btree_extents[bpos_key]
                break
            curr_snap = self.snapshots[curr_snap]["parent"]

        if resolved_extent:
            res = {
                "op": "READ_EXTENT",
                "status": "FOUND",
                "inode": inode,
                "offset_kb": offset_kb,
                "requested_snapshot": snapshot_id,
                "resolved_snapshot": resolved_extent["snapshot_id"],
                "ancestor_hops": len(visited_snaps) - 1,
                "data_hash": resolved_extent["data_hash"],
                "ptr": resolved_extent["ptr"]
            }
        else:
            res = {
                "op": "READ_EXTENT",
                "status": "NOT_FOUND",
                "inode": inode,
                "offset_kb": offset_kb,
                "requested_snapshot": snapshot_id,
                "visited_ancestors": visited_snaps
            }
        self.history.append(res)
        return res

    def flush_journal(self) -> dict:
        self.flushed_journal_seq = self.journal_seq
        self.log(f"JOURNAL_FLUSH: flushed_seq={self.flushed_journal_seq}")
        res = {
            "op": "FLUSH_JOURNAL",
            "flushed_seq": self.flushed_journal_seq,
            "active_journal_entries": len(self.journal)
        }
        self.history.append(res)
        return res

    def crash_and_recover(self, uncommitted_crash: bool = True) -> dict:
        replayed_count = 0
        if uncommitted_crash:
            self.stats["journal_replays"] += 1
            for entry in self.journal:
                if entry["seq"] > self.flushed_journal_seq:
                    replayed_count += 1
                    op = entry["op"]
                    payload = entry["payload"]
                    if op == "WRITE_EXTENT":
                        bpos_key = f"{payload['inode']}:{payload['offset_kb']}:{payload['snapshot_id']}"
                        self.btree_extents[bpos_key] = {
                            "inode": payload["inode"],
                            "offset_kb": payload["offset_kb"],
                            "size_kb": payload["size_kb"],
                            "snapshot_id": payload["snapshot_id"],
                            "ptr": payload["ptr"],
                            "data_hash": payload["data_hash"],
                            "journal_seq": entry["seq"]
                        }
                    elif op == "CREATE_SNAPSHOT":
                        self.snapshots[payload["snapshot_id"]] = {
                            "parent": payload["parent_id"],
                            "name": payload["name"]
                        }
            self.flushed_journal_seq = self.journal_seq

        self.log(f"CRASH_RECOVERY: replayed_entries={replayed_count} new_flushed_seq={self.flushed_journal_seq}")
        res = {
            "op": "CRASH_AND_RECOVER",
            "replayed_entries": replayed_count,
            "recovered_journal_seq": self.flushed_journal_seq,
            "total_extents": len(self.btree_extents)
        }
        self.history.append(res)
        return res

    def get_state(self) -> dict:
        return {
            "op": "GET_STATE",
            "total_extents": len(self.btree_extents),
            "snapshots_count": len(self.snapshots),
            "journal_seq": self.journal_seq,
            "flushed_journal_seq": self.flushed_journal_seq,
            "buckets_summary": [
                {
                    "id": b["bucket_id"],
                    "free_kb": b["free_kb"],
                    "dirty_kb": b["dirty_kb"],
                    "gen": b["generation"]
                }
                for b in self.buckets[:4]
            ]
        }

    def get_final_summary(self) -> dict:
        total_used_kb = sum(self.bucket_size_kb - b["free_kb"] for b in self.buckets)
        total_dirty_kb = sum(b["dirty_kb"] for b in self.buckets)
        return {
            "total_extents": len(self.btree_extents),
            "total_snapshots": len(self.snapshots),
            "journal_seq": self.journal_seq,
            "flushed_journal_seq": self.flushed_journal_seq,
            "total_used_kb": total_used_kb,
            "total_dirty_kb": total_dirty_kb,
            "stats": self.stats,
            "event_count": len(self.event_log)
        }

def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    eng = LinuxBcachefsEngine(data["config"])
    results = []
    for op in data.get("operations", []):
        cmd = op["op"]
        if cmd == "WRITE_EXTENT":
            res = eng.write_extent(
                inode=int(op["inode"]),
                offset_kb=int(op["offset_kb"]),
                size_kb=int(op["size_kb"]),
                snapshot_id=int(op.get("snapshot_id", 0)),
                data_hash=op.get("data_hash", "hash_default")
            )
            results.append(res)
        elif cmd == "READ_EXTENT":
            res = eng.read_extent(
                inode=int(op["inode"]),
                offset_kb=int(op["offset_kb"]),
                snapshot_id=int(op.get("snapshot_id", 0))
            )
            results.append(res)
        elif cmd == "CREATE_SNAPSHOT":
            res = eng.create_snapshot(
                parent_id=int(op.get("parent_id", 0)),
                snapshot_name=op.get("snapshot_name", "unnamed_snap")
            )
            results.append(res)
        elif cmd == "FLUSH_JOURNAL":
            res = eng.flush_journal()
            results.append(res)
        elif cmd == "CRASH_AND_RECOVER":
            res = eng.crash_and_recover(
                uncommitted_crash=bool(op.get("uncommitted_crash", True))
            )
            results.append(res)
        elif cmd == "GET_STATE":
            res = eng.get_state()
            results.append(res)

    output = {
        "results": results,
        "final_summary": eng.get_final_summary()
    }
    print(json.dumps(output, ensure_ascii=False))

if __name__ == "__main__":
    solve()
