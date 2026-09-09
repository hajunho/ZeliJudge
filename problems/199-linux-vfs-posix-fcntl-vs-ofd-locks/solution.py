import sys
import json
from typing import Dict, List, Any

class VfsFileLockSimulator:
    def __init__(self, data: Dict[str, Any]):
        cfg = data.get("system", {})
        self.lock_mode = cfg.get("lock_mode", "LINUX_OFD_LOCKS")
        # Supported: "LINUX_OFD_LOCKS", "POSIX_FCNTL_LOCKS", "BSD_FLOCK"

        # Open file descriptors: fd -> {"pid": int, "thread_id": str, "path": str, "inode": str, "file_obj_id": int}
        self.fds: Dict[int, Dict[str, Any]] = {}
        self.next_fd = 3
        self.next_file_obj = 100

        # Active kernel locks:
        # If POSIX_FCNTL_LOCKS: key = (pid, inode, start, end), val = {"type": str, "holder_fd": int}
        # If LINUX_OFD_LOCKS: key = (file_obj_id, start, end), val = {"type": str, "holder_fd": int, "pid": int}
        # If BSD_FLOCK: key = (inode), val = {"type": str, "file_obj_id": int}
        self.active_locks: List[Dict[str, Any]] = []

        # Metrics
        self.total_lock_requests = 0
        self.locks_granted = 0
        self.locks_denied = 0
        self.silent_lock_drops = 0
        self.concurrent_write_conflicts = 0
        self.database_corruptions = 0
        self.event_timeline: List[Dict[str, Any]] = []

    def open_file(self, pid: int, thread_id: str, path: str, t: float) -> int:
        fd = self.next_fd
        self.next_fd += 1
        file_obj = self.next_file_obj
        self.next_file_obj += 1
        inode = f"inode:{path}"

        self.fds[fd] = {
            "pid": pid,
            "thread_id": thread_id,
            "path": path,
            "inode": inode,
            "file_obj_id": file_obj
        }
        self.event_timeline.append({
            "wallclock_ms": t,
            "op": "OPEN",
            "pid": pid,
            "thread_id": thread_id,
            "fd": fd,
            "path": path
        })
        return fd

    def ranges_overlap(self, s1: int, l1: int, s2: int, l2: int) -> bool:
        e1 = s1 + l1 - 1
        e2 = s2 + l2 - 1
        return max(s1, s2) <= min(e1, e2)

    def lock_file(self, pid: int, thread_id: str, fd: int, start: int, length: int, lock_type: str, t: float) -> bool:
        self.total_lock_requests += 1
        f_info = self.fds.get(fd)
        if not f_info:
            self.locks_denied += 1
            return False

        inode = f_info["inode"]
        file_obj = f_info["file_obj_id"]

        if self.lock_mode == "BSD_FLOCK":
            start = 0
            length = 0x7FFFFFFF
            for lk in self.active_locks:
                if lk["inode"] == inode and lk["file_obj_id"] != file_obj:
                    self.locks_denied += 1
                    self.event_timeline.append({
                        "wallclock_ms": t,
                        "op": "LOCK",
                        "status": "DENIED",
                        "fd": fd,
                        "reason": "FLOCK_WHOLE_FILE_BUSY"
                    })
                    return False
            self.active_locks.append({
                "mode": "FLOCK",
                "inode": inode,
                "file_obj_id": file_obj,
                "fd": fd,
                "pid": pid,
                "start": start,
                "length": length,
                "type": lock_type
            })
            self.locks_granted += 1
            self.event_timeline.append({"wallclock_ms": t, "op": "LOCK", "status": "GRANTED", "fd": fd})
            return True

        elif self.lock_mode == "POSIX_FCNTL_LOCKS":
            for lk in self.active_locks:
                if lk["inode"] == inode and lk["pid"] != pid:
                    if self.ranges_overlap(start, length, lk["start"], lk["length"]):
                        self.locks_denied += 1
                        self.event_timeline.append({
                            "wallclock_ms": t,
                            "op": "LOCK",
                            "status": "DENIED",
                            "fd": fd,
                            "reason": "POSIX_OVERLAPPING_OTHER_PID"
                        })
                        return False
            self.active_locks.append({
                "mode": "POSIX",
                "inode": inode,
                "pid": pid,
                "fd": fd,
                "start": start,
                "length": length,
                "type": lock_type
            })
            self.locks_granted += 1
            self.event_timeline.append({"wallclock_ms": t, "op": "LOCK", "status": "GRANTED", "fd": fd, "range": [start, length]})
            return True

        elif self.lock_mode == "LINUX_OFD_LOCKS":
            for lk in self.active_locks:
                if lk["inode"] == inode and lk["file_obj_id"] != file_obj:
                    if self.ranges_overlap(start, length, lk["start"], lk["length"]):
                        self.locks_denied += 1
                        self.event_timeline.append({
                            "wallclock_ms": t,
                            "op": "LOCK",
                            "status": "DENIED",
                            "fd": fd,
                            "reason": "OFD_OVERLAPPING_DIFFERENT_FILE_DESC"
                        })
                        return False
            self.active_locks.append({
                "mode": "OFD",
                "inode": inode,
                "file_obj_id": file_obj,
                "fd": fd,
                "pid": pid,
                "start": start,
                "length": length,
                "type": lock_type
            })
            self.locks_granted += 1
            self.event_timeline.append({"wallclock_ms": t, "op": "LOCK", "status": "GRANTED", "fd": fd, "range": [start, length]})
            return True

        return False

    def close_file(self, pid: int, thread_id: str, fd: int, t: float):
        f_info = self.fds.get(fd)
        if not f_info:
            return

        inode = f_info["inode"]
        file_obj = f_info["file_obj_id"]

        if self.lock_mode == "POSIX_FCNTL_LOCKS":
            # CRITICAL POSIX FLAW: Closing ANY fd drops ALL locks for (pid, inode)!
            remaining_locks = []
            for lk in self.active_locks:
                if lk["inode"] == inode and lk["pid"] == pid:
                    if lk["fd"] != fd:
                        self.silent_lock_drops += 1
                        self.event_timeline.append({
                            "wallclock_ms": t,
                            "op": "SILENT_LOCK_DROP_EVENT",
                            "victim_fd": lk["fd"],
                            "closed_fd": fd,
                            "range": [lk["start"], lk["length"]],
                            "desc": "Closing unrelated fd silently stripped POSIX lock from victim fd!"
                        })
                else:
                    remaining_locks.append(lk)
            self.active_locks = remaining_locks

        elif self.lock_mode in ("LINUX_OFD_LOCKS", "BSD_FLOCK"):
            self.active_locks = [lk for lk in self.active_locks if lk.get("file_obj_id") != file_obj]

        del self.fds[fd]
        self.event_timeline.append({"wallclock_ms": t, "op": "CLOSE", "fd": fd})

    def write_file(self, pid: int, thread_id: str, fd: int, start: int, length: int, payload: str, t: float):
        f_info = self.fds.get(fd)
        if not f_info:
            return

        inode = f_info["inode"]
        file_obj = f_info["file_obj_id"]

        has_valid_lock = False
        for lk in self.active_locks:
            if lk["inode"] == inode:
                if self.lock_mode == "POSIX_FCNTL_LOCKS":
                    if lk["pid"] == pid and self.ranges_overlap(start, length, lk["start"], lk["length"]):
                        has_valid_lock = True
                        break
                elif self.lock_mode == "LINUX_OFD_LOCKS":
                    if lk["file_obj_id"] == file_obj and self.ranges_overlap(start, length, lk["start"], lk["length"]):
                        has_valid_lock = True
                        break
                elif self.lock_mode == "BSD_FLOCK":
                    if lk["file_obj_id"] == file_obj:
                        has_valid_lock = True
                        break

        if not has_valid_lock:
            self.concurrent_write_conflicts += 1
            self.database_corruptions += 1
            self.event_timeline.append({
                "wallclock_ms": t,
                "op": "WRITE",
                "status": "UNPROTECTED_CORRUPTED_WRITE",
                "fd": fd,
                "range": [start, length],
                "reason": "Lock was silently dropped or never acquired!"
            })
        else:
            self.event_timeline.append({
                "wallclock_ms": t,
                "op": "WRITE",
                "status": "SAFE_LOCKED_WRITE",
                "fd": fd,
                "range": [start, length]
            })

    def run(self, workload: List[Dict[str, Any]]) -> Dict[str, Any]:
        for item in workload:
            t = float(item.get("wallclock_ms", 0.0))
            op = item.get("op")
            pid = int(item.get("pid", 1001))
            tid = item.get("thread_id", "t1")

            if op == "OPEN":
                self.open_file(pid, tid, item["path"], t)
            elif op == "LOCK":
                fd = int(item["fd"])
                start = int(item.get("start", 0))
                length = int(item.get("length", 4096))
                ltype = item.get("type", "EXCLUSIVE")
                self.lock_file(pid, tid, fd, start, length, ltype, t)
            elif op == "CLOSE":
                fd = int(item["fd"])
                self.close_file(pid, tid, fd, t)
            elif op == "WRITE":
                fd = int(item["fd"])
                start = int(item.get("start", 0))
                length = int(item.get("length", 4096))
                payload = item.get("payload", "DATA")
                self.write_file(pid, tid, fd, start, length, payload, t)

        if self.database_corruptions > 0 or self.silent_lock_drops > 0:
            verdict = "DATABASE_CORRUPTION_POSIX_SILENT_LOCK_DROP"
            status = "FAILED"
        elif self.lock_mode == "BSD_FLOCK" and self.locks_denied >= 2:
            verdict = "FLOCK_COARSE_GRAINED_SERIALIZATION_BOTTLENECK"
            status = "FAILED"
        else:
            verdict = "OPTIMAL_OFD_LOCK_RECORD_CONCURRENCY"
            status = "SUCCESS"

        return {
            "status": status,
            "summary": {
                "lock_mode": self.lock_mode,
                "total_lock_requests": self.total_lock_requests,
                "locks_granted": self.locks_granted,
                "locks_denied": self.locks_denied,
                "silent_lock_drops": self.silent_lock_drops,
                "database_corruptions": self.database_corruptions
            },
            "metrics": {
                "total_lock_requests": self.total_lock_requests,
                "locks_granted": self.locks_granted,
                "locks_denied": self.locks_denied,
                "silent_lock_drops": self.silent_lock_drops,
                "concurrent_write_conflicts": self.concurrent_write_conflicts,
                "database_corruptions": self.database_corruptions,
                "active_locks_remaining": len(self.active_locks),
                "verdict": verdict
            },
            "sample_events": self.event_timeline[:15]
        }

def solve():
    raw_data = sys.stdin.read().strip()
    if not raw_data:
        return
    input_data = json.loads(raw_data)
    simulator = VfsFileLockSimulator(input_data)
    workload = input_data.get("workload", [])
    output = simulator.run(workload)
    print(json.dumps(output, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    solve()
