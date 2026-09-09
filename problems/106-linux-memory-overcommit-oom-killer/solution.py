import sys

class Process:
    def __init__(self, pid, name, oom_score_adj):
        self.pid = pid
        self.name = name
        self.oom_score_adj = oom_score_adj
        self.vma_pages = 0
        self.rss_pages = 0
        self.alive = True

    def calculate_oom_score(self, total_ram):
        if not self.alive:
            return -1
        if self.oom_score_adj == -1000:
            return -1000  # 면제
        base = (self.rss_pages * 1000) // total_ram if total_ram > 0 else 0
        score = base + self.oom_score_adj
        return max(0, min(1000, score))

class KernelMemorySimulator:
    def __init__(self, ram, swap, mode, ratio):
        self.total_ram = ram
        self.swap = swap
        self.mode = mode
        self.ratio = ratio
        self.commit_limit = swap + (ram * ratio) // 100
        self.total_committed = 0
        self.total_resident = 0
        self.processes = {}

    def spawn_process(self, pid, name, adj):
        p = Process(pid, name, adj)
        self.processes[pid] = p
        return f"SPAWN_PROCESS pid={pid} name={name} adj={adj}"

    def set_oom_score_adj(self, pid, new_adj):
        p = self.processes[pid]
        old_adj = p.oom_score_adj
        p.oom_score_adj = new_adj
        return f"SET_ADJ pid={pid} name={p.name} old_adj={old_adj} new_adj={new_adj}"

    def malloc(self, pid, pages):
        p = self.processes[pid]
        if not p.alive:
            return [f"ERROR pid={pid} reason=PROCESS_NOT_ALIVE"]
            
        if self.mode == 2:
            if self.total_committed + pages > self.commit_limit:
                return [f"MALLOC_FAILED pid={pid} requested={pages} reason=ENOMEM_COMMIT_LIMIT_EXCEEDED commit_limit={self.commit_limit} total_committed={self.total_committed}"]
        elif self.mode == 0:
            if self.total_committed + pages > (self.total_ram + self.swap):
                return [f"MALLOC_FAILED pid={pid} requested={pages} reason=ENOMEM_HEURISTIC_EXCEEDED"]

        p.vma_pages += pages
        self.total_committed += pages
        return [f"MALLOC_OK pid={pid} pages={pages} vma={p.vma_pages} total_committed={self.total_committed}"]

    def touch_pages(self, pid, pages):
        outputs = []
        p = self.processes[pid]
        if not p.alive:
            outputs.append(f"ERROR pid={pid} reason=PROCESS_NOT_ALIVE")
            return outputs

        if p.rss_pages + pages > p.vma_pages:
            outputs.append(f"ERROR pid={pid} reason=TOUCH_EXCEEDS_VMA requested={pages} vma={p.vma_pages} current_rss={p.rss_pages}")
            return outputs

        while True:
            available_ram = self.total_ram - self.total_resident
            if pages <= available_ram:
                p.rss_pages += pages
                self.total_resident += pages
                outputs.append(f"TOUCH_OK pid={pid} touched={pages} current_rss={p.rss_pages} total_rss={self.total_resident}")
                break
            else:
                # OOM Killer 발동
                outputs.append(f"OOM_KILLER_INVOKED available_ram={available_ram} requested={pages}")
                candidates = []
                for target_pid, proc in self.processes.items():
                    if proc.alive:
                        score = proc.calculate_oom_score(self.total_ram)
                        if score != -1000:
                            candidates.append((score, target_pid, proc))

                if not candidates:
                    outputs.append("KERNEL_PANIC reason=OUT_OF_MEMORY_NO_KILLABLE_PROCESS")
                    break

                # 점수 내림차순, PID 내림차순
                candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
                victim_score, victim_pid, victim = candidates[0]

                victim.alive = False
                freed_rss = victim.rss_pages
                freed_vma = victim.vma_pages
                self.total_resident -= freed_rss
                self.total_committed -= freed_vma

                outputs.append(f"OOM_KILL victim_pid={victim.pid} name={victim.name} rss_pages={freed_rss} oom_score={victim_score}")

                if victim.pid == pid:
                    outputs.append(f"TOUCH_ABORTED pid={pid} reason=PROCESS_KILLED_BY_OOM")
                    break

        return outputs

    def stats(self):
        lines = [f"STATS total_ram={self.total_ram} total_rss={self.total_resident} total_committed={self.total_committed} commit_limit={self.commit_limit}"]
        for pid in sorted(self.processes.keys()):
            p = self.processes[pid]
            if p.alive:
                score = p.calculate_oom_score(self.total_ram)
                score_str = "IMMUNE" if score == -1000 else str(score)
                lines.append(f"PROC pid={p.pid} name={p.name} vma={p.vma_pages} rss={p.rss_pages} adj={p.oom_score_adj} oom_score={score_str} status=ALIVE")
            else:
                lines.append(f"PROC pid={p.pid} name={p.name} status=DEAD")
        return lines

def main():
    kernel = None
    lines = sys.stdin.read().splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        cmd = parts[0]
        
        if cmd == "INIT_KERNEL":
            ram = int(parts[1])
            swap = int(parts[2])
            mode = int(parts[3])
            ratio = int(parts[4])
            kernel = KernelMemorySimulator(ram, swap, mode, ratio)
            print(f"INIT_KERNEL ram={ram} swap={swap} mode={mode} ratio={ratio}% commit_limit={kernel.commit_limit}")
            
        elif cmd == "SPAWN_PROCESS":
            pid = int(parts[1])
            name = parts[2]
            adj = int(parts[3])
            print(kernel.spawn_process(pid, name, adj))
            
        elif cmd == "SET_OOM_SCORE_ADJ":
            pid = int(parts[1])
            adj = int(parts[2])
            print(kernel.set_oom_score_adj(pid, adj))
            
        elif cmd == "MALLOC":
            pid = int(parts[1])
            pages = int(parts[2])
            for out in kernel.malloc(pid, pages):
                print(out)
                
        elif cmd == "TOUCH_PAGES":
            pid = int(parts[1])
            pages = int(parts[2])
            for out in kernel.touch_pages(pid, pages):
                print(out)
                
        elif cmd == "STATS":
            for s in kernel.stats():
                print(s)

if __name__ == "__main__":
    main()
