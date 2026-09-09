import sys
import heapq

class Record:
    def __init__(self, offset, key, cost_ms, arrival_time):
        self.offset = int(offset)
        self.key = key
        self.cost_ms = int(cost_ms)
        self.arrival_time = int(arrival_time)
        self.start_time = None
        self.finish_time = None

class ParallelConsumerEngine:
    def __init__(self, num_workers, max_in_flight):
        self.num_workers = int(num_workers)
        self.max_in_flight = int(max_in_flight)
        self.records = []

    def add_record(self, offset, key, cost_ms, arrival_time):
        self.records.append(Record(offset, key, cost_ms, arrival_time))

    def run(self):
        self.records.sort(key=lambda r: (r.arrival_time, r.offset))

        time = 0
        in_buffer_queue = []
        active_keys = set()
        running_tasks = []
        idle_workers = list(range(self.num_workers))
        heapq.heapify(idle_workers)

        completed_offsets = set()
        execution_order = []
        safe_commit_watermark = 0
        watermark_progression = []

        record_idx = 0
        n_records = len(self.records)

        key_violations = 0
        key_last_finish = {}
        holes_prevented = 0

        while record_idx < n_records or in_buffer_queue or running_tasks:
            next_arrival = self.records[record_idx].arrival_time if record_idx < n_records else float('inf')
            next_completion = running_tasks[0][0] if running_tasks else float('inf')

            if running_tasks and next_completion <= next_arrival:
                time = next_completion
            elif record_idx < n_records:
                time = max(time, next_arrival)
            elif running_tasks:
                time = next_completion
            else:
                break

            batch_completed = []
            while running_tasks and running_tasks[0][0] <= time:
                fin_time, w_id, rec = heapq.heappop(running_tasks)
                batch_completed.append((fin_time, w_id, rec))

            batch_completed.sort(key=lambda x: x[2].offset)

            for fin_time, w_id, rec in batch_completed:
                completed_offsets.add(rec.offset)
                active_keys.remove(rec.key)
                heapq.heappush(idle_workers, w_id)
                execution_order.append((rec.offset, fin_time))

                if rec.key in key_last_finish and rec.start_time < key_last_finish[rec.key]:
                    key_violations += 1
                key_last_finish[rec.key] = fin_time

                if rec.offset > safe_commit_watermark:
                    holes_prevented += 1

                prev_wm = safe_commit_watermark
                while safe_commit_watermark in completed_offsets:
                    safe_commit_watermark += 1
                if safe_commit_watermark != prev_wm:
                    watermark_progression.append((fin_time, safe_commit_watermark))

            while record_idx < n_records and self.records[record_idx].arrival_time <= time:
                in_buffer_queue.append(self.records[record_idx])
                record_idx += 1

            i = 0
            while i < len(in_buffer_queue) and idle_workers and len(running_tasks) < self.max_in_flight:
                rec = in_buffer_queue[i]
                if rec.key not in active_keys:
                    w_id = heapq.heappop(idle_workers)
                    active_keys.add(rec.key)
                    in_buffer_queue.pop(i)
                    rec.start_time = time
                    rec.finish_time = time + rec.cost_ms
                    heapq.heappush(running_tasks, (rec.finish_time, w_id, rec))
                else:
                    i += 1

        seq_time = sum(r.cost_ms for r in self.records)
        par_time = time
        speedup = round(seq_time / par_time, 2) if par_time > 0 else 1.0

        return {
            "execution_order": execution_order,
            "key_violations": key_violations,
            "holes_prevented": holes_prevented,
            "watermark_progression": watermark_progression,
            "sequential_time_ms": seq_time,
            "parallel_time_ms": par_time,
            "speedup_factor": f"{speedup:.2f}x"
        }

def format_output(res):
    lines = []
    exec_str = ",".join([f"{off}@{t}" for off, t in res["execution_order"]])
    lines.append(f"EXECUTION_ORDER: {exec_str}")

    key_status = f"VALID (0 violations)" if res["key_violations"] == 0 else f"VIOLATION ({res['key_violations']} violations)"
    lines.append(f"KEY_ORDER_STATUS: {key_status}")

    lines.append(f"HOLES_PREVENTED: {res['holes_prevented']}")

    wm_str = "->".join([f"({t},{off})" for t, off in res["watermark_progression"]])
    lines.append(f"WATERMARK_PROGRESSION: {wm_str}")

    lines.append(f"BENCHMARK: SEQ={res['sequential_time_ms']}ms PAR={res['parallel_time_ms']}ms SPEEDUP={res['speedup_factor']}")
    return "\n".join(lines)

def solve():
    input_text = sys.stdin.read().strip()
    if not input_text:
        return
    lines = [line.strip() for line in input_text.splitlines() if line.strip()]
    if not lines:
        return

    # Line 1: WORKERS <w> MAX_IN_FLIGHT <m>
    p1 = lines[0].split()
    w_idx = p1.index("WORKERS")
    m_idx = p1.index("MAX_IN_FLIGHT")
    workers = int(p1[w_idx + 1])
    max_in_flight = int(p1[m_idx + 1])

    engine = ParallelConsumerEngine(workers, max_in_flight)

    # Line 2: RECORDS <n>
    p2 = lines[1].split()
    n_records = int(p2[1])

    for i in range(2, 2 + n_records):
        if i >= len(lines):
            break
        if lines[i] == "END":
            break
        parts = lines[i].split()
        off = int(parts[0])
        key = parts[1]
        cost = int(parts[2])
        arrival = int(parts[3])
        engine.add_record(off, key, cost, arrival)

    res = engine.run()
    print(format_output(res))

if __name__ == '__main__':
    solve()
