import sys
import json

class RwSemaphoreEngine:
    def __init__(self, config):
        self.handoff_threshold_us = config.get("handoff_threshold_us", 1000)
        self.readers = 0
        self.writer_locked = False
        self.owner = None
        self.wait_list = []
        self.handoff_active = False
        
        self.stats = {
            "fast_read_hits": 0,
            "fast_write_hits": 0,
            "spin_steals": 0,
            "batched_reader_wakes": 0
        }

    def _check_handoff(self, time_us):
        if self.wait_list:
            head = self.wait_list[0]
            if (time_us - head["wait_start"]) >= self.handoff_threshold_us:
                self.handoff_active = True
            else:
                self.handoff_active = False
        else:
            self.handoff_active = False

    def down_read(self, thread_id, time_us):
        self._check_handoff(time_us)
        if not self.writer_locked and not self.handoff_active and not self.wait_list:
            self.readers += 1
            self.stats["fast_read_hits"] += 1
            return {"status": "ACQUIRED_READ_FAST", "thread_id": thread_id, "readers": self.readers}
        elif not self.writer_locked and not self.handoff_active and self.wait_list and self.wait_list[0]["type"] == "READ":
            self.readers += 1
            self.stats["fast_read_hits"] += 1
            return {"status": "ACQUIRED_READ_FAST", "thread_id": thread_id, "readers": self.readers}
        
        self.wait_list.append({"thread_id": thread_id, "type": "READ", "wait_start": time_us})
        self._check_handoff(time_us)
        return {"status": "WAITING_READ", "thread_id": thread_id, "wait_pos": len(self.wait_list) - 1}

    def down_write(self, thread_id, time_us):
        self._check_handoff(time_us)
        if self.readers == 0 and not self.writer_locked and not self.handoff_active and len(self.wait_list) == 0:
            self.writer_locked = True
            self.owner = thread_id
            self.stats["fast_write_hits"] += 1
            return {"status": "ACQUIRED_WRITE_FAST", "thread_id": thread_id}
        
        self.wait_list.append({"thread_id": thread_id, "type": "WRITE", "wait_start": time_us})
        self._check_handoff(time_us)
        return {"status": "WAITING_WRITE", "thread_id": thread_id, "wait_pos": len(self.wait_list) - 1}

    def try_spin_acquire(self, thread_id, time_us):
        self._check_handoff(time_us)
        if self.readers == 0 and not self.writer_locked:
            if self.handoff_active:
                return {"status": "SPIN_STEAL_REJECTED_HANDOFF", "thread_id": thread_id}
            else:
                self.writer_locked = True
                self.owner = thread_id
                self.stats["spin_steals"] += 1
                return {"status": "SPIN_STEAL_SUCCESS", "thread_id": thread_id}
        return {"status": "SPIN_STEAL_FAILED_BUSY", "thread_id": thread_id}

    def up_read(self, thread_id, time_us):
        if self.readers <= 0:
            return {"status": "ERROR_UNDERFLOW", "thread_id": thread_id}
        
        self.readers -= 1
        woken_writer = None
        
        if self.readers == 0 and self.wait_list:
            head = self.wait_list[0]
            if head["type"] == "WRITE":
                self.wait_list.pop(0)
                self.writer_locked = True
                self.owner = head["thread_id"]
                woken_writer = head["thread_id"]
                self._check_handoff(time_us)

        return {
            "status": "READ_RELEASED",
            "thread_id": thread_id,
            "readers": self.readers,
            "woken_writer": woken_writer
        }

    def up_write(self, thread_id, time_us):
        if not self.writer_locked:
            return {"status": "ERROR_NOT_LOCKED", "thread_id": thread_id}
        
        self.writer_locked = False
        self.owner = None
        woken_type = "NONE"
        woken = []

        if self.wait_list:
            head = self.wait_list[0]
            if head["type"] == "WRITE":
                self.wait_list.pop(0)
                self.writer_locked = True
                self.owner = head["thread_id"]
                woken_type = "WRITE"
                woken = [head["thread_id"]]
            elif head["type"] == "READ":
                woken_type = "READ_BATCH"
                while self.wait_list and self.wait_list[0]["type"] == "READ":
                    r_waiter = self.wait_list.pop(0)
                    self.readers += 1
                    woken.append(r_waiter["thread_id"])
                    self.stats["batched_reader_wakes"] += 1

        self._check_handoff(time_us)
        return {
            "status": "WRITE_RELEASED",
            "thread_id": thread_id,
            "woken_type": woken_type,
            "woken": woken,
            "readers": self.readers
        }

    def update_waiters_time(self, time_us):
        self._check_handoff(time_us)
        if self.handoff_active and self.wait_list:
            head = self.wait_list[0]
            return {
                "status": "HANDOFF_ACTIVATED",
                "head_thread": head["thread_id"],
                "wait_duration_us": time_us - head["wait_start"]
            }
        return {"status": "WAITING_NORMAL", "handoff_active": self.handoff_active}

    def query_stats(self):
        return {
            "readers": self.readers,
            "writer_locked": self.writer_locked,
            "owner": self.owner,
            "waiters_count": len(self.wait_list),
            "handoff_active": self.handoff_active,
            "fast_read_hits": self.stats["fast_read_hits"],
            "fast_write_hits": self.stats["fast_write_hits"],
            "spin_steals": self.stats["spin_steals"],
            "batched_reader_wakes": self.stats["batched_reader_wakes"]
        }

def solve():
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    raw = sys.stdin.read().strip()
    if not raw:
        return

    input_data = json.loads(raw)
    engine = RwSemaphoreEngine(input_data.get("config", {}))
    results = []

    for op in input_data.get("operations", []):
        cmd = op.get("op")
        if cmd == "DOWN_READ":
            res = engine.down_read(op["thread_id"], op["time_us"])
            results.append(res)
        elif cmd == "DOWN_WRITE":
            res = engine.down_write(op["thread_id"], op["time_us"])
            results.append(res)
        elif cmd == "UP_READ":
            res = engine.up_read(op["thread_id"], op["time_us"])
            results.append(res)
        elif cmd == "UP_WRITE":
            res = engine.up_write(op["thread_id"], op["time_us"])
            results.append(res)
        elif cmd == "TRY_SPIN_ACQUIRE":
            res = engine.try_spin_acquire(op["thread_id"], op["time_us"])
            results.append(res)
        elif cmd == "UPDATE_WAITERS_TIME":
            res = engine.update_waiters_time(op["time_us"])
            results.append(res)
        elif cmd == "QUERY_STATS":
            res = engine.query_stats()
            results.append(res)

    out_obj = {"results": results}
    print(json.dumps(out_obj, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    solve()
