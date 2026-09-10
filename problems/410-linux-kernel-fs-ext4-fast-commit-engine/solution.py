import sys
import json

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class Ext4FastCommitEngine:
    def __init__(self, config):
        self.fc_journal_capacity_bytes = config.get("fc_journal_capacity_bytes", 65536)
        self.block_size = config.get("block_size", 4096)
        self.jbd2_full_commit_block_overhead = config.get("jbd2_full_commit_block_overhead", 4)
        self.fast_commit_sector_size = config.get("fast_commit_sector_size", 512)
        
        # Filesystem state
        self.inodes = {
            2: {"ino": 2, "parent_ino": 2, "name": "/", "size": 4096, "extents": [], "is_dir": True}
        }
        
        # Transaction & Fast commit state
        self.fc_eligible = True
        self.fc_ineligible_reasons = []
        self.fc_deltas = []
        self.fc_journal_used_bytes = 0
        self.fc_seq = 0
        
        # Statistics
        self.fc_commit_count = 0
        self.jbd2_full_commit_count = 0
        self.total_journal_written_bytes = 0
        self.commit_history = []
        self.event_logs = []

    def _mark_ineligible(self, current_time, reason):
        if self.fc_eligible:
            self.fc_eligible = False
        self.fc_ineligible_reasons.append(reason)
        self.event_logs.append({
            "time": current_time,
            "event": "FC_MARK_INELIGIBLE",
            "reason": reason
        })

    def create_file(self, current_time, parent_ino, ino, name, is_dir=False):
        self.inodes[ino] = {
            "ino": ino,
            "parent_ino": parent_ino,
            "name": name,
            "size": 4096 if is_dir else 0,
            "extents": [],
            "is_dir": is_dir
        }
        delta_size = 16 + len(name.encode("utf-8"))
        delta = {
            "tag": "EXT4_FC_TAG_CREAT",
            "parent_ino": parent_ino,
            "ino": ino,
            "name": name,
            "size_bytes": delta_size
        }
        self.fc_deltas.append(delta)
        self.event_logs.append({
            "time": current_time,
            "event": "CREATE_FILE",
            "ino": ino,
            "name": name,
            "delta_bytes": delta_size
        })

    def append_data(self, current_time, ino, lblk, pblk, length):
        if ino not in self.inodes:
            return
        inode = self.inodes[ino]
        inode["extents"].append({"lblk": lblk, "pblk": pblk, "len": length})
        inode["size"] = max(inode["size"], (lblk + length) * self.block_size)
        
        delta_size = 24
        delta = {
            "tag": "EXT4_FC_TAG_ADD_RANGE",
            "ino": ino,
            "lblk": lblk,
            "pblk": pblk,
            "len": length,
            "size_bytes": delta_size
        }
        self.fc_deltas.append(delta)
        
        inode_delta = {
            "tag": "EXT4_FC_TAG_INODE",
            "ino": ino,
            "size": inode["size"],
            "size_bytes": 32
        }
        self.fc_deltas.append(inode_delta)
        
        self.event_logs.append({
            "time": current_time,
            "event": "APPEND_DATA",
            "ino": ino,
            "lblk": lblk,
            "pblk": pblk,
            "len": length,
            "new_size": inode["size"]
        })

    def truncate_data(self, current_time, ino, lblk, length):
        if ino not in self.inodes:
            return
        inode = self.inodes[ino]
        new_extents = []
        for ext in inode["extents"]:
            e_lblk = ext["lblk"]
            e_len = ext["len"]
            e_end = e_lblk + e_len
            trunc_end = lblk + length
            if e_end <= lblk or e_lblk >= trunc_end:
                new_extents.append(ext)
        inode["extents"] = new_extents
        inode["size"] = lblk * self.block_size
        
        delta = {
            "tag": "EXT4_FC_TAG_DEL_RANGE",
            "ino": ino,
            "lblk": lblk,
            "len": length,
            "size_bytes": 20
        }
        self.fc_deltas.append(delta)
        self.fc_deltas.append({
            "tag": "EXT4_FC_TAG_INODE",
            "ino": ino,
            "size": inode["size"],
            "size_bytes": 32
        })
        self.event_logs.append({
            "time": current_time,
            "event": "TRUNCATE_DATA",
            "ino": ino,
            "lblk": lblk,
            "len": length,
            "new_size": inode["size"]
        })

    def unlink_file(self, current_time, parent_ino, ino, name):
        if ino in self.inodes:
            del self.inodes[ino]
        delta_size = 16 + len(name.encode("utf-8"))
        delta = {
            "tag": "EXT4_FC_TAG_UNLINK",
            "parent_ino": parent_ino,
            "ino": ino,
            "name": name,
            "size_bytes": delta_size
        }
        self.fc_deltas.append(delta)
        self.event_logs.append({
            "time": current_time,
            "event": "UNLINK_FILE",
            "parent_ino": parent_ino,
            "ino": ino,
            "name": name
        })

    def cross_dir_rename(self, current_time, old_parent, new_parent, ino, old_name, new_name):
        if ino in self.inodes:
            self.inodes[ino]["parent_ino"] = new_parent
            self.inodes[ino]["name"] = new_name
        self._mark_ineligible(current_time, "CROSS_DIR_RENAME")
        self.event_logs.append({
            "time": current_time,
            "event": "CROSS_DIR_RENAME",
            "old_parent": old_parent,
            "new_parent": new_parent,
            "ino": ino,
            "old_name": old_name,
            "new_name": new_name
        })

    def set_xattr(self, current_time, ino, name, value):
        self._mark_ineligible(current_time, "XATTR_MODIFIED")
        self.event_logs.append({
            "time": current_time,
            "event": "SET_XATTR",
            "ino": ino,
            "name": name
        })

    def fsync(self, current_time, ino):
        raw_delta_size = sum(d["size_bytes"] for d in self.fc_deltas) + 16
        fc_write_bytes = ((raw_delta_size + self.fast_commit_sector_size - 1) // self.fast_commit_sector_size) * self.fast_commit_sector_size
        if fc_write_bytes == 0:
            fc_write_bytes = self.fast_commit_sector_size
            
        full_commit_bytes = self.jbd2_full_commit_block_overhead * self.block_size
        
        can_fast_commit = (
            self.fc_eligible and 
            (self.fc_journal_used_bytes + fc_write_bytes <= self.fc_journal_capacity_bytes)
        )
        
        if can_fast_commit:
            self.fc_commit_count += 1
            self.fc_seq += 1
            self.fc_journal_used_bytes += fc_write_bytes
            self.total_journal_written_bytes += fc_write_bytes
            
            commit_record = {
                "time": current_time,
                "commit_type": "FAST_COMMIT",
                "fc_seq": self.fc_seq,
                "written_bytes": fc_write_bytes,
                "journal_used_bytes": self.fc_journal_used_bytes,
                "deltas_committed": len(self.fc_deltas)
            }
            self.commit_history.append(commit_record)
            self.event_logs.append({
                "time": current_time,
                "event": "COMMIT_SUCCESS",
                "commit_type": "FAST_COMMIT",
                "written_bytes": fc_write_bytes,
                "fc_seq": self.fc_seq
            })
            self.fc_deltas.clear()
        else:
            reason = self.fc_ineligible_reasons[0] if not self.fc_eligible and self.fc_ineligible_reasons else "FC_AREA_EXHAUSTED"
            self.jbd2_full_commit_count += 1
            self.total_journal_written_bytes += full_commit_bytes
            
            commit_record = {
                "time": current_time,
                "commit_type": "JBD2_FULL_COMMIT",
                "fallback_reason": reason,
                "written_bytes": full_commit_bytes,
                "journal_used_bytes": 0,
                "deltas_committed": len(self.fc_deltas)
            }
            self.commit_history.append(commit_record)
            self.event_logs.append({
                "time": current_time,
                "event": "COMMIT_SUCCESS",
                "commit_type": "JBD2_FULL_COMMIT",
                "fallback_reason": reason,
                "written_bytes": full_commit_bytes
            })
            
            self.fc_eligible = True
            self.fc_ineligible_reasons.clear()
            self.fc_deltas.clear()
            self.fc_journal_used_bytes = 0

    def run_trace(self, trace):
        for ev in trace:
            ev_type = ev.get("type")
            t = ev.get("time", 0)
            if ev_type == "CREATE_FILE":
                self.create_file(t, ev["parent_ino"], ev["ino"], ev["name"], ev.get("is_dir", False))
            elif ev_type == "APPEND_DATA":
                self.append_data(t, ev["ino"], ev["lblk"], ev["pblk"], ev["len"])
            elif ev_type == "TRUNCATE_DATA":
                self.truncate_data(t, ev["ino"], ev["lblk"], ev["len"])
            elif ev_type == "UNLINK_FILE":
                self.unlink_file(t, ev["parent_ino"], ev["ino"], ev["name"])
            elif ev_type == "CROSS_DIR_RENAME":
                self.cross_dir_rename(t, ev["old_parent_ino"], ev["new_parent_ino"], ev["ino"], ev["old_name"], ev["new_name"])
            elif ev_type == "SET_XATTR":
                self.set_xattr(t, ev["ino"], ev["name"], ev.get("value", ""))
            elif ev_type == "FSYNC":
                self.fsync(t, ev["ino"])

    def get_result(self):
        inodes_dict = {str(k): v for k, v in self.inodes.items()}
        return {
            "summary": {
                "fc_commit_count": self.fc_commit_count,
                "jbd2_full_commit_count": self.jbd2_full_commit_count,
                "total_journal_written_bytes": self.total_journal_written_bytes,
                "fc_journal_used_bytes": self.fc_journal_used_bytes,
                "fc_seq": self.fc_seq,
                "current_fc_eligible": self.fc_eligible
            },
            "inodes": inodes_dict,
            "commit_history": self.commit_history,
            "event_logs": self.event_logs
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    trace = data.get("trace", [])
    
    engine = Ext4FastCommitEngine(config)
    engine.run_trace(trace)
    result = engine.get_result()
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
