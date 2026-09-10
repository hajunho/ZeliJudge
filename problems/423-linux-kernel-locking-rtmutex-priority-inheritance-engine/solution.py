import sys
import json

class Task:
    def __init__(self, task_id, normal_prio):
        self.task_id = task_id
        self.normal_prio = normal_prio
        self.effective_prio = normal_prio
        self.held_locks = set()
        self.blocked_on = None

class Mutex:
    def __init__(self, mutex_id):
        self.mutex_id = mutex_id
        self.owner = None
        self.waiters = []

class RTMutexEngine:
    def __init__(self, config=None):
        self.tasks = {}
        self.mutexes = {}
        
        self.pi_boost_count = 0
        self.pi_deboost_count = 0
        self.deadlocks_prevented = 0
        
        self.pi_logs = []
        self.event_logs = []

    def create_task(self, current_time, task_id, prio):
        self.tasks[task_id] = Task(task_id, prio)
        self.event_logs.append({
            "time": current_time,
            "event": "TASK_CREATED",
            "task_id": task_id,
            "prio": prio
        })

    def _get_or_create_mutex(self, mutex_id):
        if mutex_id not in self.mutexes:
            self.mutexes[mutex_id] = Mutex(mutex_id)
        return self.mutexes[mutex_id]

    def _calc_effective_prio(self, task):
        best = task.normal_prio
        for m_id in task.held_locks:
            m = self.mutexes.get(m_id)
            if m and m.waiters:
                for w_id in m.waiters:
                    w = self.tasks.get(w_id)
                    if w and w.effective_prio < best:
                        best = w.effective_prio
        return best

    def _update_task_prio(self, current_time, task_id):
        task = self.tasks[task_id]
        old_eff = task.effective_prio
        new_eff = self._calc_effective_prio(task)
        if new_eff != old_eff:
            task.effective_prio = new_eff
            if new_eff < old_eff:
                self.pi_boost_count += 1
                self.pi_logs.append({
                    "time": current_time,
                    "action": "PI_BOOST",
                    "task_id": task_id,
                    "old_prio": old_eff,
                    "new_prio": new_eff
                })
            else:
                self.pi_deboost_count += 1
                self.pi_logs.append({
                    "time": current_time,
                    "action": "PI_DEBOOST",
                    "task_id": task_id,
                    "old_prio": old_eff,
                    "new_prio": new_eff
                })
            
            if task.blocked_on:
                next_mutex = self.mutexes.get(task.blocked_on)
                if next_mutex and next_mutex.owner:
                    self._propagate_chain(current_time, next_mutex.owner)

    def _propagate_chain(self, current_time, owner_id):
        curr = owner_id
        visited = set()
        while curr and curr not in visited:
            visited.add(curr)
            task = self.tasks[curr]
            old_eff = task.effective_prio
            new_eff = self._calc_effective_prio(task)
            if new_eff != old_eff:
                task.effective_prio = new_eff
                if new_eff < old_eff:
                    self.pi_boost_count += 1
                    self.pi_logs.append({
                        "time": current_time,
                        "action": "PI_BOOST",
                        "task_id": curr,
                        "old_prio": old_eff,
                        "new_prio": new_eff
                    })
                else:
                    self.pi_deboost_count += 1
                    self.pi_logs.append({
                        "time": current_time,
                        "action": "PI_DEBOOST",
                        "task_id": curr,
                        "old_prio": old_eff,
                        "new_prio": new_eff
                    })
                if task.blocked_on:
                    m = self.mutexes.get(task.blocked_on)
                    curr = m.owner if m else None
                else:
                    break
            else:
                break

    def _check_deadlock(self, waiter_id, mutex):
        curr = mutex.owner
        visited = set()
        while curr:
            if curr == waiter_id:
                return True
            if curr in visited:
                break
            visited.add(curr)
            t = self.tasks.get(curr)
            if t and t.blocked_on:
                m = self.mutexes.get(t.blocked_on)
                curr = m.owner if m else None
            else:
                break
        return False

    def lock(self, current_time, task_id, mutex_id):
        task = self.tasks[task_id]
        mutex = self._get_or_create_mutex(mutex_id)
        
        if mutex.owner is None:
            mutex.owner = task_id
            task.held_locks.add(mutex_id)
            self.event_logs.append({
                "time": current_time,
                "event": "LOCK_ACQUIRED_FASTPATH",
                "task_id": task_id,
                "mutex_id": mutex_id
            })
            return True
        elif mutex.owner == task_id:
            return True
        else:
            if self._check_deadlock(task_id, mutex):
                self.deadlocks_prevented += 1
                self.event_logs.append({
                    "time": current_time,
                    "event": "DEADLOCK_DETECTED",
                    "task_id": task_id,
                    "mutex_id": mutex_id,
                    "owner": mutex.owner
                })
                return False
                
            task.blocked_on = mutex_id
            if task_id not in mutex.waiters:
                mutex.waiters.append(task_id)
            self.event_logs.append({
                "time": current_time,
                "event": "LOCK_BLOCKED",
                "task_id": task_id,
                "mutex_id": mutex_id,
                "owner": mutex.owner
            })
            
            self._propagate_chain(current_time, mutex.owner)
            return False

    def unlock(self, current_time, task_id, mutex_id):
        if mutex_id not in self.mutexes:
            return
        mutex = self.mutexes[mutex_id]
        if mutex.owner != task_id:
            return
            
        task = self.tasks[task_id]
        task.held_locks.remove(mutex_id)
        
        self.event_logs.append({
            "time": current_time,
            "event": "LOCK_RELEASED",
            "task_id": task_id,
            "mutex_id": mutex_id
        })
        
        if mutex.waiters:
            mutex.waiters.sort(key=lambda wid: self.tasks[wid].effective_prio)
            top_waiter_id = mutex.waiters.pop(0)
            
            top_waiter = self.tasks[top_waiter_id]
            top_waiter.blocked_on = None
            top_waiter.held_locks.add(mutex_id)
            mutex.owner = top_waiter_id
            
            self.event_logs.append({
                "time": current_time,
                "event": "LOCK_HANDOFF",
                "mutex_id": mutex_id,
                "from_task": task_id,
                "to_task": top_waiter_id
            })
            self._update_task_prio(current_time, top_waiter_id)
        else:
            mutex.owner = None
            
        self._update_task_prio(current_time, task_id)

    def change_prio(self, current_time, task_id, new_prio):
        if task_id not in self.tasks:
            return
        task = self.tasks[task_id]
        old_normal = task.normal_prio
        task.normal_prio = new_prio
        self.event_logs.append({
            "time": current_time,
            "event": "PRIO_CHANGED",
            "task_id": task_id,
            "old_prio": old_normal,
            "new_prio": new_prio
        })
        self._update_task_prio(current_time, task_id)
        if task.blocked_on:
            m = self.mutexes.get(task.blocked_on)
            if m and m.owner:
                self._propagate_chain(current_time, m.owner)

    def run_trace(self, trace):
        for ev in trace:
            t = ev.get("time", 0)
            ev_type = ev.get("type")
            if ev_type == "CREATE_TASK":
                self.create_task(t, ev["task_id"], ev["prio"])
            elif ev_type == "LOCK":
                self.lock(t, ev["task_id"], ev["mutex_id"])
            elif ev_type == "UNLOCK":
                self.unlock(t, ev["task_id"], ev["mutex_id"])
            elif ev_type == "CHANGE_PRIO":
                self.change_prio(t, ev["task_id"], ev["new_prio"])

    def get_result(self):
        tasks_out = {}
        for tid, t in sorted(self.tasks.items()):
            tasks_out[tid] = {
                "normal_prio": t.normal_prio,
                "effective_prio": t.effective_prio,
                "held_locks": sorted(list(t.held_locks)),
                "blocked_on": t.blocked_on
            }
            
        mutexes_out = {}
        for mid, m in sorted(self.mutexes.items()):
            mutexes_out[mid] = {
                "owner": m.owner,
                "waiter_count": len(m.waiters),
                "waiters": list(m.waiters)
            }
            
        return {
            "summary": {
                "pi_boost_count": self.pi_boost_count,
                "pi_deboost_count": self.pi_deboost_count,
                "deadlocks_prevented": self.deadlocks_prevented,
                "total_tasks": len(self.tasks),
                "total_mutexes": len(self.mutexes)
            },
            "tasks": tasks_out,
            "mutexes": mutexes_out,
            "pi_logs": self.pi_logs,
            "event_logs": self.event_logs
        }

def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    
    engine = RTMutexEngine(data.get("config", {}))
    engine.run_trace(data.get("trace", []))
    res = engine.get_result()
    print(json.dumps(res, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
