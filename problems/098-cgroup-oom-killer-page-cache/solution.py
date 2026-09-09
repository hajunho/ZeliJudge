import sys

class Process:
    def __init__(self, pid, name, heap_limit_mb):
        self.pid = str(pid)
        self.name = name
        self.heap_limit_mb = int(heap_limit_mb)
        self.anon_mb = 0
        self.file_clean_mb = 0
        self.file_dirty_mb = 0
        self.kernel_mb = 0
        self.status = "RUNNING"  # RUNNING, KILLED

    @property
    def total_memory(self):
        return self.anon_mb + self.file_clean_mb + self.file_dirty_mb + self.kernel_mb

class CGroup:
    def __init__(self, name, memory_high_mb, memory_max_mb):
        self.name = name
        self.memory_high_mb = int(memory_high_mb)
        self.memory_max_mb = int(memory_max_mb)
        self.processes = {}  # pid -> Process
        self.killed_processes = []

    @property
    def current_anon(self):
        return sum(p.anon_mb for p in self.processes.values() if p.status == "RUNNING")

    @property
    def current_file_clean(self):
        return sum(p.file_clean_mb for p in self.processes.values() if p.status == "RUNNING")

    @property
    def current_file_dirty(self):
        return sum(p.file_dirty_mb for p in self.processes.values() if p.status == "RUNNING")

    @property
    def current_file(self):
        return self.current_file_clean + self.current_file_dirty

    @property
    def current_kernel(self):
        return sum(p.kernel_mb for p in self.processes.values() if p.status == "RUNNING")

    @property
    def memory_current(self):
        return self.current_anon + self.current_file + self.current_kernel

    def direct_reclaim(self, needed_mb):
        # Reclaim from file_clean_mb across running processes
        available = self.current_file_clean
        reclaim_amount = min(available, needed_mb)
        if reclaim_amount <= 0:
            return 0

        remaining = reclaim_amount
        # Deduct from running processes with clean page cache
        for p in sorted(self.processes.values(), key=lambda x: x.file_clean_mb, reverse=True):
            if remaining <= 0:
                break
            if p.status == "RUNNING" and p.file_clean_mb > 0:
                deduct = min(p.file_clean_mb, remaining)
                p.file_clean_mb -= deduct
                remaining -= deduct

        return reclaim_amount

    def trigger_oom_killer(self, triggered_usage):
        # Select victim: running process with largest anon_mb (or total memory)
        running = [p for p in self.processes.values() if p.status == "RUNNING"]
        if not running:
            return None

        # Sort by anon_mb descending, then total_memory descending, then pid
        victim = sorted(running, key=lambda p: (p.anon_mb, p.total_memory, p.pid), reverse=True)[0]
        victim.status = "KILLED"
        self.killed_processes.append(victim)
        # Release all memory of victim
        victim.anon_mb = 0
        victim.file_clean_mb = 0
        victim.file_dirty_mb = 0
        victim.kernel_mb = 0

        return victim

class MemorySubsystem:
    def __init__(self):
        self.cgroups = {}  # name -> CGroup
        self.proc_to_cgroup = {}  # pid -> CGroup

    def config_cgroup(self, name, memory_high_mb, memory_max_mb):
        cg = CGroup(name, memory_high_mb, memory_max_mb)
        self.cgroups[name] = cg
        return f"CGROUP_CONFIG_OK name={name} memory_high={memory_high_mb}MB memory_max={memory_max_mb}MB"

    def spawn_process(self, cgroup_name, pid, name, heap_limit_mb):
        if cgroup_name not in self.cgroups:
            return f"ERROR:UNKNOWN_CGROUP cgroup={cgroup_name}"
        cg = self.cgroups[cgroup_name]
        proc = Process(pid, name, heap_limit_mb)
        cg.processes[str(pid)] = proc
        self.proc_to_cgroup[str(pid)] = cg
        return f"SPAWN_OK pid={pid} name={name} cgroup={cgroup_name}"

    def alloc_anon(self, pid, amount_mb):
        pid = str(pid)
        if pid not in self.proc_to_cgroup:
            return f"ERROR:PROCESS_NOT_FOUND pid={pid}"
        cg = self.proc_to_cgroup[pid]
        proc = cg.processes[pid]
        if proc.status != "RUNNING":
            return f"ERROR:PROCESS_NOT_RUNNING pid={pid}"

        amount = int(amount_mb)

        # Check JVM internal heap limit first
        if proc.anon_mb + amount > proc.heap_limit_mb:
            return f"ERROR:JAVA_OOM_EXCEPTION pid={pid} heap_used={proc.anon_mb}MB limit={proc.heap_limit_mb}MB"

        # Check CGroup memory_max
        future_total = cg.memory_current + amount
        if future_total > cg.memory_max_mb:
            needed = future_total - cg.memory_max_mb
            reclaimed = cg.direct_reclaim(needed)
            if future_total - reclaimed > cg.memory_max_mb:
                # OOM Killer triggers!
                victim = cg.trigger_oom_killer(future_total - reclaimed)
                return f"OOM_KILLER_TRIGGERED cgroup={cg.name} memory_current={future_total - reclaimed}MB memory_max={cg.memory_max_mb}MB victim_pid={victim.pid} victim_name={victim.name} exit_code=137"

        # Allocation succeeded
        proc.anon_mb += amount
        curr = cg.memory_current
        if curr > cg.memory_high_mb:
            return f"ALLOC_ANON_OK pid={pid} anon={proc.anon_mb}MB memory_current={curr}MB [THROTTLED_HIGH_WATERMARK limit={cg.memory_high_mb}MB]"
        return f"ALLOC_ANON_OK pid={pid} anon={proc.anon_mb}MB memory_current={curr}MB"

    def file_io(self, pid, clean_mb, dirty_mb):
        pid = str(pid)
        if pid not in self.proc_to_cgroup:
            return f"ERROR:PROCESS_NOT_FOUND pid={pid}"
        cg = self.proc_to_cgroup[pid]
        proc = cg.processes[pid]
        if proc.status != "RUNNING":
            return f"ERROR:PROCESS_NOT_RUNNING pid={pid}"

        clean = int(clean_mb)
        dirty = int(dirty_mb)
        added = clean + dirty

        future_total = cg.memory_current + added
        if future_total > cg.memory_max_mb:
            needed = future_total - cg.memory_max_mb
            reclaimed = cg.direct_reclaim(needed)
            if future_total - reclaimed > cg.memory_max_mb:
                victim = cg.trigger_oom_killer(future_total - reclaimed)
                return f"OOM_KILLER_TRIGGERED cgroup={cg.name} memory_current={future_total - reclaimed}MB memory_max={cg.memory_max_mb}MB victim_pid={victim.pid} victim_name={victim.name} exit_code=137"

        proc.file_clean_mb += clean
        proc.file_dirty_mb += dirty
        total_file = proc.file_clean_mb + proc.file_dirty_mb
        curr = cg.memory_current
        return f"FILE_IO_OK pid={pid} page_cache={total_file}MB clean={proc.file_clean_mb}MB dirty={proc.file_dirty_mb}MB memory_current={curr}MB"

    def sync_disk(self, pid):
        pid = str(pid)
        if pid not in self.proc_to_cgroup:
            return f"ERROR:PROCESS_NOT_FOUND pid={pid}"
        cg = self.proc_to_cgroup[pid]
        proc = cg.processes[pid]
        if proc.status != "RUNNING":
            return f"ERROR:PROCESS_NOT_RUNNING pid={pid}"

        flushed = proc.file_dirty_mb
        proc.file_clean_mb += flushed
        proc.file_dirty_mb = 0
        return f"SYNC_OK pid={pid} flushed={flushed}MB clean_now={proc.file_clean_mb}MB"

    def drop_caches(self, cgroup_name):
        if cgroup_name not in self.cgroups:
            return f"ERROR:UNKNOWN_CGROUP cgroup={cgroup_name}"
        cg = self.cgroups[cgroup_name]
        reclaimed = cg.current_file_clean
        for p in cg.processes.values():
            if p.status == "RUNNING":
                p.file_clean_mb = 0
        return f"DROP_CACHES_OK cgroup={cgroup_name} reclaimed={reclaimed}MB memory_current={cg.memory_current}MB"

    def stats(self, cgroup_name):
        if cgroup_name not in self.cgroups:
            return f"ERROR:UNKNOWN_CGROUP cgroup={cgroup_name}"
        cg = self.cgroups[cgroup_name]
        running_cnt = sum(1 for p in cg.processes.values() if p.status == "RUNNING")
        killed_cnt = len(cg.killed_processes)
        return (f"STATS cgroup={cg.name} memory_current={cg.memory_current}MB "
                f"(anon={cg.current_anon}MB file={cg.current_file}MB dirty={cg.current_file_dirty}MB) "
                f"max={cg.memory_max_mb}MB high={cg.memory_high_mb}MB "
                f"running_procs={running_cnt} killed_procs={killed_cnt}")

def main():
    subsystem = MemorySubsystem()
    lines = sys.stdin.read().splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        cmd = parts[0].upper()

        if cmd == "CONFIG_CGROUP":
            name = parts[1]
            high = parts[2]
            max_m = parts[3]
            print(subsystem.config_cgroup(name, high, max_m))
        elif cmd == "SPAWN_PROCESS":
            cg = parts[1]
            pid = parts[2]
            pname = parts[3]
            limit = parts[4]
            print(subsystem.spawn_process(cg, pid, pname, limit))
        elif cmd == "ALLOC_ANON":
            pid = parts[1]
            amt = parts[2]
            print(subsystem.alloc_anon(pid, amt))
        elif cmd == "FILE_IO":
            pid = parts[1]
            clean = parts[2]
            dirty = parts[3]
            print(subsystem.file_io(pid, clean, dirty))
        elif cmd == "SYNC_DISK":
            pid = parts[1]
            print(subsystem.sync_disk(pid))
        elif cmd == "DROP_CACHES":
            cg = parts[1]
            print(subsystem.drop_caches(cg))
        elif cmd == "STATS":
            cg = parts[1]
            print(subsystem.stats(cg))

if __name__ == '__main__':
    main()
