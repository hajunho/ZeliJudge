import sys
import json

class QRWLock:
    def __init__(self, lock_id):
        self.lock_id = lock_id
        self.writer_locked = False
        self.writer_waiting = False
        self.reader_count = 0
        
        self.active_readers = set()
        self.active_writer = None
        self.waiting_writer = None
        
        self.writer_queue = []
        self.reader_queue = []

class QRWLockEngine:
    def __init__(self, config=None):
        self.locks = {}
        
        self.read_fastpath_count = 0
        self.read_blocked_count = 0
        self.write_fastpath_count = 0
        self.write_barriers_set = 0
        self.writer_starvations_prevented = 0
        
        self.lock_logs = []
        self.event_logs = []

    def _get_lock(self, lock_id):
        if lock_id not in self.locks:
            self.locks[lock_id] = QRWLock(lock_id)
        return self.locks[lock_id]

    def read_lock(self, current_time, lock_id, task_id):
        l = self._get_lock(lock_id)
        
        if not l.writer_locked and not l.writer_waiting and l.waiting_writer is None:
            l.reader_count += 1
            l.active_readers.add(task_id)
            self.read_fastpath_count += 1
            self.event_logs.append({
                "time": current_time,
                "event": "READ_LOCK_FASTPATH",
                "lock_id": lock_id,
                "task_id": task_id,
                "reader_count": l.reader_count
            })
            return True
        else:
            l.reader_queue.append(task_id)
            self.read_blocked_count += 1
            self.event_logs.append({
                "time": current_time,
                "event": "READ_LOCK_BLOCKED",
                "lock_id": lock_id,
                "task_id": task_id,
                "reason": "WRITER_PENDING_OR_LOCKED"
            })
            return False

    def read_unlock(self, current_time, lock_id, task_id):
        if lock_id not in self.locks:
            return
        l = self.locks[lock_id]
        if task_id not in l.active_readers:
            return
            
        l.active_readers.remove(task_id)
        l.reader_count -= 1
        self.event_logs.append({
            "time": current_time,
            "event": "READ_UNLOCK_SUCCESS",
            "lock_id": lock_id,
            "task_id": task_id,
            "remaining_readers": l.reader_count
        })
        
        if l.reader_count == 0 and l.waiting_writer:
            w_id = l.waiting_writer
            l.waiting_writer = None
            l.writer_waiting = False
            l.writer_locked = True
            l.active_writer = w_id
            self.writer_starvations_prevented += 1
            self.lock_logs.append({
                "time": current_time,
                "action": "WRITER_HANDOFF_FROM_READERS",
                "lock_id": lock_id,
                "writer_id": w_id
            })
            self.event_logs.append({
                "time": current_time,
                "event": "WRITER_ACQUIRED_AFTER_READERS_DRAIN",
                "lock_id": lock_id,
                "writer_id": w_id
            })

    def write_lock(self, current_time, lock_id, task_id):
        l = self._get_lock(lock_id)
        
        if not l.writer_locked and not l.writer_waiting and l.reader_count == 0 and l.waiting_writer is None:
            l.writer_locked = True
            l.active_writer = task_id
            self.write_fastpath_count += 1
            self.event_logs.append({
                "time": current_time,
                "event": "WRITE_LOCK_FASTPATH",
                "lock_id": lock_id,
                "task_id": task_id
            })
            return True
        else:
            if not l.writer_waiting and l.waiting_writer is None:
                l.writer_waiting = True
                l.waiting_writer = task_id
                self.write_barriers_set += 1
                self.lock_logs.append({
                    "time": current_time,
                    "action": "WRITE_BARRIER_SET",
                    "lock_id": lock_id,
                    "waiting_writer": task_id,
                    "active_readers": l.reader_count
                })
                self.event_logs.append({
                    "time": current_time,
                    "event": "WRITE_LOCK_WAITING_SET_BARRIER",
                    "lock_id": lock_id,
                    "task_id": task_id
                })
                return False
            else:
                l.writer_queue.append(task_id)
                self.event_logs.append({
                    "time": current_time,
                    "event": "WRITE_LOCK_QUEUED_MCS",
                    "lock_id": lock_id,
                    "task_id": task_id
                })
                return False

    def write_unlock(self, current_time, lock_id, task_id):
        if lock_id not in self.locks:
            return
        l = self.locks[lock_id]
        if l.active_writer != task_id:
            return
            
        l.writer_locked = False
        l.active_writer = None
        self.event_logs.append({
            "time": current_time,
            "event": "WRITE_UNLOCK_SUCCESS",
            "lock_id": lock_id,
            "task_id": task_id
        })
        
        if l.writer_queue:
            next_writer = l.writer_queue.pop(0)
            l.writer_locked = True
            l.active_writer = next_writer
            self.lock_logs.append({
                "time": current_time,
                "action": "WRITER_HANDOFF_MCS",
                "lock_id": lock_id,
                "next_writer": next_writer
            })
            self.event_logs.append({
                "time": current_time,
                "event": "WRITER_ACQUIRED_FROM_MCS",
                "lock_id": lock_id,
                "writer_id": next_writer
            })
        elif l.reader_queue:
            woken_count = len(l.reader_queue)
            while l.reader_queue:
                r_id = l.reader_queue.pop(0)
                l.reader_count += 1
                l.active_readers.add(r_id)
            self.lock_logs.append({
                "time": current_time,
                "action": "READERS_BATCH_UNBLOCKED",
                "lock_id": lock_id,
                "count": woken_count
            })
            self.event_logs.append({
                "time": current_time,
                "event": "READERS_WOKEN_UP",
                "lock_id": lock_id,
                "count": woken_count
            })

    def run_trace(self, trace):
        for ev in trace:
            t = ev.get("time", 0)
            ev_type = ev.get("type")
            if ev_type == "READ_LOCK":
                self.read_lock(t, ev["lock_id"], ev["task_id"])
            elif ev_type == "READ_UNLOCK":
                self.read_unlock(t, ev["lock_id"], ev["task_id"])
            elif ev_type == "WRITE_LOCK":
                self.write_lock(t, ev["lock_id"], ev["task_id"])
            elif ev_type == "WRITE_UNLOCK":
                self.write_unlock(t, ev["lock_id"], ev["task_id"])

    def get_result(self):
        locks_out = {}
        for lid, l in sorted(self.locks.items()):
            locks_out[lid] = {
                "writer_locked": l.writer_locked,
                "writer_waiting": l.writer_waiting,
                "reader_count": l.reader_count,
                "active_readers": sorted(list(l.active_readers)),
                "active_writer": l.active_writer,
                "waiting_writer": l.waiting_writer,
                "queued_writers": list(l.writer_queue),
                "queued_readers": list(l.reader_queue)
            }
            
        return {
            "summary": {
                "read_fastpath_count": self.read_fastpath_count,
                "read_blocked_count": self.read_blocked_count,
                "write_fastpath_count": self.write_fastpath_count,
                "write_barriers_set": self.write_barriers_set,
                "writer_starvations_prevented": self.writer_starvations_prevented,
                "total_locks": len(self.locks)
            },
            "locks": locks_out,
            "lock_logs": self.lock_logs,
            "event_logs": self.event_logs
        }

def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    
    engine = QRWLockEngine(data.get("config", {}))
    engine.run_trace(data.get("trace", []))
    res = engine.get_result()
    print(json.dumps(res, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
