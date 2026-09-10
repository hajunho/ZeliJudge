import sys
import json

PERIOD_US = 1024
HALF_LIFE_PERIODS = 32
DECAY_Y = 0.5 ** (1.0 / HALF_LIFE_PERIODS)
MAX_SUM = 47742.0

class SchedEntity:
    def __init__(self, task_id, weight=1024):
        self.task_id = task_id
        self.weight = weight
        self.state = "SLEEPING"
        self.last_update_time = 0
        self.util_sum = 0.0
        self.load_sum = 0.0
        self.runnable_sum = 0.0
        self.cpu = 0

    def decay_and_accumulate(self, current_time):
        delta = current_time - self.last_update_time
        if delta <= 0:
            return
        
        periods = delta // PERIOD_US
        remainder = delta % PERIOD_US
        decay = DECAY_Y ** periods
        
        self.util_sum = self.util_sum * decay
        self.load_sum = self.load_sum * decay
        self.runnable_sum = self.runnable_sum * decay
        
        if periods > 0:
            geom_sum = 1024.0 * (1.0 - decay) / (1.0 - DECAY_Y)
        else:
            geom_sum = 0.0
        new_active_time = geom_sum + remainder
        
        if self.state == "RUNNING":
            self.util_sum += new_active_time
            self.load_sum += new_active_time
            self.runnable_sum += new_active_time
        elif self.state == "RUNNABLE":
            self.load_sum += new_active_time
            self.runnable_sum += new_active_time
            
        self.last_update_time = current_time

    @property
    def util_avg(self):
        return min(1024.0, round((self.util_sum / MAX_SUM) * 1024.0, 2))

    @property
    def load_avg(self):
        return round((self.load_sum / MAX_SUM) * (self.weight / 1024.0) * 1024.0, 2)

    @property
    def runnable_avg(self):
        return min(1024.0, round((self.runnable_sum / MAX_SUM) * 1024.0, 2))

def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)
    
    num_cpus = input_data.get("num_cpus", 2)
    operations = input_data.get("operations", [])
    
    tasks = {}
    current_time = 0
    op_log = []
    
    stats = {
        "task_creations": 0,
        "state_transitions": 0,
        "migrations": 0,
        "schedutil_freq_updates": 0
    }
    
    for op in operations:
        t = op.get("time", current_time)
        current_time = t
        
        for tid, task in tasks.items():
            task.decay_and_accumulate(current_time)
            
        op_type = op.get("op")
        
        if op_type == "CREATE_TASK":
            stats["task_creations"] += 1
            tid = op["task_id"]
            weight = op.get("weight", 1024)
            cpu = op.get("cpu", 0)
            ent = SchedEntity(tid, weight)
            ent.cpu = cpu
            ent.last_update_time = current_time
            tasks[tid] = ent
            op_log.append({
                "time": current_time,
                "op": "CREATE_TASK",
                "task_id": tid,
                "cpu": cpu,
                "weight": weight
            })
            
        elif op_type == "SET_STATE":
            stats["state_transitions"] += 1
            tid = op["task_id"]
            new_state = op["new_state"]
            task = tasks[tid]
            old_state = task.state
            task.state = new_state
            op_log.append({
                "time": current_time,
                "op": "SET_STATE",
                "task_id": tid,
                "old_state": old_state,
                "new_state": new_state,
                "util_avg": task.util_avg,
                "load_avg": task.load_avg
            })
            
        elif op_type == "MIGRATE_TASK":
            stats["migrations"] += 1
            tid = op["task_id"]
            target_cpu = op["target_cpu"]
            task = tasks[tid]
            old_cpu = task.cpu
            task.cpu = target_cpu
            op_log.append({
                "time": current_time,
                "op": "MIGRATE_TASK",
                "task_id": tid,
                "from_cpu": old_cpu,
                "to_cpu": target_cpu,
                "util_avg": task.util_avg,
                "load_avg": task.load_avg
            })
            
        elif op_type == "ADVANCE_TIME":
            op_log.append({
                "time": current_time,
                "op": "ADVANCE_TIME"
            })
            
    cpu_aggregates = {}
    for c in range(num_cpus):
        cpu_tasks = [t for t in tasks.values() if t.cpu == c]
        cpu_util = round(min(1024.0, sum(t.util_avg for t in cpu_tasks)), 2)
        cpu_load = round(sum(t.load_avg for t in cpu_tasks), 2)
        schedutil_cap = min(1024.0, round(cpu_util * 1.25, 2))
        cpu_aggregates[f"cpu_{c}"] = {
            "task_count": len(cpu_tasks),
            "total_util_avg": cpu_util,
            "total_load_avg": cpu_load,
            "schedutil_target_cap": schedutil_cap
        }
        
    task_summaries = {}
    for tid, t in tasks.items():
        task_summaries[tid] = {
            "cpu": t.cpu,
            "state": t.state,
            "weight": t.weight,
            "util_avg": t.util_avg,
            "load_avg": t.load_avg,
            "runnable_avg": t.runnable_avg
        }

    res = {
        "num_cpus": num_cpus,
        "final_time_us": current_time,
        "cpu_aggregates": cpu_aggregates,
        "task_summaries": task_summaries,
        "stats": stats,
        "op_log": op_log
    }
    
    sys.stdout.write(json.dumps(res, separators=(',', ':'), ensure_ascii=False))

if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    solve()
