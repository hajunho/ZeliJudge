import sys

class RequestThread:
    def __init__(self, thread_id, requires_nested_new):
        self.thread_id = thread_id
        self.requires_nested_new = requires_nested_new
        self.has_parent_conn = False
        self.has_nested_conn = False
        self.state = "INIT"  # INIT, RUNNING, WAITING_PARENT, WAITING_CHILD, FINISHED, TIMED_OUT
        self.wait_time_ms = 0

class HikariPoolSimulator:
    def __init__(self):
        self.pool_size = 10
        self.timeout_ms = 30000
        self.available_conns = 10
        self.threads = {}  # thread_id -> RequestThread
        self.wait_queue = []  # list of thread_ids
        self.timeout_count = 0
        self.deadlock_detected = False

    def config_pool(self, pool_size, timeout_ms):
        self.pool_size = int(pool_size)
        self.timeout_ms = int(timeout_ms)
        self.available_conns = self.pool_size
        self.threads = {}
        self.wait_queue = []
        self.timeout_count = 0
        self.deadlock_detected = False
        return f"CONFIG_POOL_OK pool_size={self.pool_size} timeout={self.timeout_ms}ms"

    def _allocate_available(self):
        logs = []
        # Priority 1: WAITING_CHILD (only needs 1 more connection to finish)
        child_waiters = [t_id for t_id in self.wait_queue if self.threads[t_id].state == "WAITING_CHILD"]
        for t_id in child_waiters:
            if self.available_conns > 0:
                self.available_conns -= 1
                t = self.threads[t_id]
                t.has_nested_conn = True
                t.state = "RUNNING"
                t.wait_time_ms = 0
                self.wait_queue.remove(t_id)
                logs.append(f"UNBLOCKED_NESTED thread={t_id} status=RUNNING available_pool={self.available_conns}")

        # Priority 2: WAITING_PARENT
        parent_waiters = [t_id for t_id in self.wait_queue if self.threads[t_id].state == "WAITING_PARENT"]
        for t_id in parent_waiters:
            if self.available_conns > 0:
                self.available_conns -= 1
                t = self.threads[t_id]
                t.has_parent_conn = True
                t.wait_time_ms = 0
                if t.requires_nested_new:
                    if self.available_conns > 0:
                        self.available_conns -= 1
                        t.has_nested_conn = True
                        t.state = "RUNNING"
                        self.wait_queue.remove(t_id)
                        logs.append(f"UNBLOCKED_RUNNING thread={t_id} parent_conn=ACQUIRED nested_conn=ACQUIRED available_pool={self.available_conns}")
                    else:
                        t.state = "WAITING_CHILD"
                        logs.append(f"UNBLOCKED_PARTIAL thread={t_id} parent_conn=ACQUIRED waiting=NESTED_CONN available_pool=0")
                else:
                    t.state = "RUNNING"
                    self.wait_queue.remove(t_id)
                    logs.append(f"UNBLOCKED_RUNNING thread={t_id} parent_conn=ACQUIRED status=RUNNING available_pool={self.available_conns}")
        return logs

    def start_request(self, thread_id, requires_nested_new_str):
        nested = (requires_nested_new_str.upper() == "TRUE")
        t = RequestThread(thread_id, nested)
        self.threads[thread_id] = t

        if self.available_conns > 0:
            self.available_conns -= 1
            t.has_parent_conn = True
            if not nested:
                t.state = "RUNNING"
                return f"REQUEST_STARTED thread={thread_id} parent_conn=ACQUIRED nested=NONE status=RUNNING available_pool={self.available_conns}"
            else:
                # Needs nested connection!
                if self.available_conns > 0:
                    self.available_conns -= 1
                    t.has_nested_conn = True
                    t.state = "RUNNING"
                    return f"REQUEST_STARTED thread={thread_id} parent_conn=ACQUIRED nested_conn=ACQUIRED status=RUNNING available_pool={self.available_conns}"
                else:
                    t.state = "WAITING_CHILD"
                    self.wait_queue.append(thread_id)
                    return f"REQUEST_WAITING thread={thread_id} parent_conn=ACQUIRED waiting=NESTED_CONN available_pool=0"
        else:
            t.state = "WAITING_PARENT"
            self.wait_queue.append(thread_id)
            return f"REQUEST_WAITING thread={thread_id} waiting=PARENT_CONN available_pool=0"

    def tick(self, ms):
        elapsed = int(ms)
        logs = [f"TICK_OK elapsed={elapsed}ms"]

        # Check timeouts in wait_queue
        timed_out_threads = []
        for t_id in list(self.wait_queue):
            t = self.threads[t_id]
            t.wait_time_ms += elapsed
            if t.wait_time_ms >= self.timeout_ms:
                timed_out_threads.append(t_id)

        for t_id in timed_out_threads:
            t = self.threads[t_id]
            t.state = "TIMED_OUT"
            self.timeout_count += 1
            self.wait_queue.remove(t_id)
            released = 0
            if t.has_parent_conn:
                self.available_conns += 1
                t.has_parent_conn = False
                released += 1
            if t.has_nested_conn:
                self.available_conns += 1
                t.has_nested_conn = False
                released += 1
            logs.append(f"TIMEOUT_FAILED thread={t_id} elapsed={t.wait_time_ms}ms released_conns={released}")

        # If any connections were freed by timeout, allocate them
        alloc_logs = self._allocate_available()
        logs.extend(alloc_logs)

        # Check for deadlock
        active_waiting_child = [t_id for t_id in self.wait_queue if self.threads[t_id].state == "WAITING_CHILD"]
        running = [t_id for t_id, t in self.threads.items() if t.state == "RUNNING"]
        if self.available_conns == 0 and len(active_waiting_child) > 0 and len(running) == 0:
            logs.append(f"STATUS:POOL_DEADLOCK_DETECTED threads_stalled={len(active_waiting_child)} available_pool=0")

        return "\n".join(logs)

    def finish_request(self, thread_id):
        if thread_id not in self.threads:
            return f"ERROR:UNKNOWN_THREAD thread={thread_id}"
        t = self.threads[thread_id]
        if t.state != "RUNNING":
            return f"ERROR:THREAD_NOT_RUNNING thread={thread_id} state={t.state}"

        t.state = "FINISHED"
        released = 0
        if t.has_parent_conn:
            self.available_conns += 1
            t.has_parent_conn = False
            released += 1
        if t.has_nested_conn:
            self.available_conns += 1
            t.has_nested_conn = False
            released += 1

        logs = [f"REQUEST_FINISHED thread={thread_id} released_conns={released} available_pool={self.available_conns}"]
        alloc_logs = self._allocate_available()
        logs.extend(alloc_logs)
        return "\n".join(logs)

    def calculate_safe_pool(self, max_threads, max_conns_per_thread):
        tn = int(max_threads)
        cm = int(max_conns_per_thread)
        recommended = tn * (cm - 1) + 1
        return f"SAFE_POOL_SIZE threads={tn} conns_per_thread={cm} recommended_pool_size={recommended}"

    def stats(self):
        running = sum(1 for t in self.threads.values() if t.state == "RUNNING")
        wc = sum(1 for t in self.threads.values() if t.state == "WAITING_CHILD")
        wp = sum(1 for t in self.threads.values() if t.state == "WAITING_PARENT")
        return (f"STATS pool_total={self.pool_size} pool_available={self.available_conns} "
                f"running_threads={running} waiting_child={wc} waiting_parent={wp} timeouts={self.timeout_count}")

def main():
    sim = HikariPoolSimulator()
    lines = sys.stdin.read().splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        cmd = parts[0].upper()

        if cmd == "CONFIG_POOL":
            print(sim.config_pool(parts[1], parts[2]))
        elif cmd == "START_REQUEST":
            print(sim.start_request(parts[1], parts[2]))
        elif cmd == "TICK":
            print(sim.tick(parts[1]))
        elif cmd == "FINISH_REQUEST":
            print(sim.finish_request(parts[1]))
        elif cmd == "CALCULATE_SAFE_POOL":
            print(sim.calculate_safe_pool(parts[1], parts[2]))
        elif cmd == "STATS":
            print(sim.stats())

if __name__ == '__main__':
    main()
