import sys
from collections import deque

class FIFOEngine:
    def __init__(self, num_frames: int, fault_penalty: int, window_size: int, threshold_pct: float):
        self.num_frames = num_frames
        self.penalty = fault_penalty
        self.window_size = window_size
        self.threshold_pct = threshold_pct

        self.frames = []
        self.fifo_queue = deque()
        self.total_accesses = 0
        self.hits = 0
        self.faults = 0
        self.total_cost = 0
        self.history = []  # 1 for fault, 0 for hit

    def access(self, page_id: str):
        self.total_accesses += 1
        if page_id in self.frames:
            self.hits += 1
            self.total_cost += 1
            self.history.append(0)
        else:
            self.faults += 1
            self.total_cost += self.penalty
            self.history.append(1)
            if len(self.frames) < self.num_frames:
                self.frames.append(page_id)
                self.fifo_queue.append(page_id)
            else:
                victim = self.fifo_queue.popleft()
                idx = self.frames.index(victim)
                self.frames[idx] = page_id
                self.fifo_queue.append(page_id)

    def is_thrashing(self) -> bool:
        if len(self.history) < self.window_size:
            return False
        recent = self.history[-self.window_size:]
        fault_rate = (sum(recent) / len(recent)) * 100.0
        return fault_rate >= self.threshold_pct

class ClockEngine:
    def __init__(self, num_frames: int, fault_penalty: int, window_size: int, threshold_pct: float):
        self.num_frames = num_frames
        self.penalty = fault_penalty
        self.window_size = window_size
        self.threshold_pct = threshold_pct

        self.frames = [None] * num_frames
        self.ref_bits = [0] * num_frames
        self.hand = 0

        self.total_accesses = 0
        self.hits = 0
        self.faults = 0
        self.total_cost = 0
        self.history = []

    def access(self, page_id: str):
        self.total_accesses += 1
        if page_id in self.frames:
            self.hits += 1
            self.total_cost += 1
            self.history.append(0)
            idx = self.frames.index(page_id)
            self.ref_bits[idx] = 1
        else:
            self.faults += 1
            self.total_cost += self.penalty
            self.history.append(1)

            while True:
                if self.frames[self.hand] is None:
                    self.frames[self.hand] = page_id
                    self.ref_bits[self.hand] = 1
                    self.hand = (self.hand + 1) % self.num_frames
                    break
                elif self.ref_bits[self.hand] == 1:
                    self.ref_bits[self.hand] = 0
                    self.hand = (self.hand + 1) % self.num_frames
                else:
                    self.frames[self.hand] = page_id
                    self.ref_bits[self.hand] = 1
                    self.hand = (self.hand + 1) % self.num_frames
                    break

    def is_thrashing(self) -> bool:
        if len(self.history) < self.window_size:
            return False
        recent = self.history[-self.window_size:]
        fault_rate = (sum(recent) / len(recent)) * 100.0
        return fault_rate >= self.threshold_pct

class VirtualMemorySimulator:
    def __init__(self, num_frames: int, penalty: int, window: int, thresh: float):
        self.fifo = FIFOEngine(num_frames, penalty, window, thresh)
        self.clock = ClockEngine(num_frames, penalty, window, thresh)

    def access(self, page_id: str):
        self.fifo.access(page_id)
        self.clock.access(page_id)

    def get_status(self) -> str:
        lines = []
        for name, eng in [("FIFO", self.fifo), ("CLOCK", self.clock)]:
            lines.append(f"=== {name} ENGINE ===")
            lines.append(f"TOTAL_ACCESSES: {eng.total_accesses}")
            lines.append(f"PAGE_HITS: {eng.hits}")
            lines.append(f"PAGE_FAULTS: {eng.faults}")
            lines.append(f"TOTAL_COST_TICKS: {eng.total_cost}")
            active_frames = [p for p in eng.frames if p is not None]
            lines.append(f"CURRENT_FRAMES: {active_frames}")
            lines.append(f"THRASHING: {'TRUE' if eng.is_thrashing() else 'FALSE'}")
        return "\n".join(lines)

def run():
    input_data = sys.stdin.read().splitlines()
    sim = None
    output = []

    for line in input_data:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split()
        cmd = parts[0]

        if cmd == "INIT":
            frames = int(parts[1])
            penalty = int(parts[2])
            window = int(parts[3])
            thresh = float(parts[4])
            sim = VirtualMemorySimulator(frames, penalty, window, thresh)
            output.append(f"INITIALIZED FRAMES={frames} PENALTY={penalty}")

        elif cmd == "ACCESS":
            pid = parts[1]
            sim.access(pid)
            output.append(f"ACCESS {pid}")

        elif cmd == "ACCESS_STREAM":
            pids = parts[1:]
            for pid in pids:
                sim.access(pid)
            output.append(f"ACCESSED {len(pids)} PAGES")

        elif cmd == "STATUS":
            output.append(sim.get_status())

    print("\n".join(output))

if __name__ == "__main__":
    run()
