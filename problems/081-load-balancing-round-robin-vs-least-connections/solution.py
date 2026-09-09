import sys

class Server:
    def __init__(self, server_id: int):
        self.server_id = server_id
        self.in_flight = 0
        self.peak_in_flight = 0
        self.allocations = 0
        self.active_requests = []  # list of finish_tick

    def assign(self, finish_tick: int):
        self.allocations += 1
        self.in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
        self.active_requests.append(finish_tick)

    def complete_up_to(self, current_tick: int) -> int:
        remaining = []
        finished_cnt = 0
        for ft in self.active_requests:
            if ft <= current_tick:
                finished_cnt += 1
            else:
                remaining.append(ft)
        self.active_requests = remaining
        self.in_flight -= finished_cnt
        return finished_cnt

class LoadBalancerEngine:
    def __init__(self, strategy: str, num_servers: int):
        self.strategy = strategy
        self.num_servers = num_servers
        self.servers = [Server(i) for i in range(num_servers)]
        self.rr_pointer = 0
        self.total_requests = 0
        self.completed_requests = 0

    def select_server(self) -> int:
        if self.strategy == "ROUND_ROBIN":
            target = self.rr_pointer
            self.rr_pointer = (self.rr_pointer + 1) % self.num_servers
            return target
        elif self.strategy == "LEAST_CONNECTIONS":
            min_conn = min(s.in_flight for s in self.servers)
            for s in self.servers:
                if s.in_flight == min_conn:
                    return s.server_id
        return 0

    def route_request(self, current_tick: int, duration: int):
        self.total_requests += 1
        target_id = self.select_server()
        finish_tick = current_tick + duration
        self.servers[target_id].assign(finish_tick)

    def step(self, current_tick: int):
        for s in self.servers:
            finished = s.complete_up_to(current_tick)
            self.completed_requests += finished

    def get_active_in_flight(self) -> int:
        return sum(s.in_flight for s in self.servers)

    def get_peak_in_flight(self) -> int:
        if not self.servers:
            return 0
        return max(s.peak_in_flight for s in self.servers)

class Simulator:
    def __init__(self, num_servers: int):
        self.num_servers = num_servers
        self.current_tick = 0
        self.rr_engine = LoadBalancerEngine("ROUND_ROBIN", num_servers)
        self.lc_engine = LoadBalancerEngine("LEAST_CONNECTIONS", num_servers)

    def route(self, req_id: str, duration: int):
        self.rr_engine.route_request(self.current_tick, duration)
        self.lc_engine.route_request(self.current_tick, duration)

    def step_one_tick(self):
        self.current_tick += 1
        self.rr_engine.step(self.current_tick)
        self.lc_engine.step(self.current_tick)

    def step(self, ticks: int) -> str:
        for _ in range(ticks):
            self.step_one_tick()
        return f"STEPPED {ticks} TICKS (CURRENT_TICK: {self.current_tick})"

    def is_idle(self) -> bool:
        return self.rr_engine.get_active_in_flight() == 0 and self.lc_engine.get_active_in_flight() == 0

    def run_until_idle(self, max_ticks: int) -> str:
        advanced = 0
        while advanced < max_ticks:
            if self.is_idle():
                return f"IDLE_REACHED AT TICK {self.current_tick}"
            self.step_one_tick()
            advanced += 1

        if self.is_idle():
            return f"IDLE_REACHED AT TICK {self.current_tick}"
        else:
            return f"MAX_TICKS_REACHED AT TICK {self.current_tick}"

    def get_status(self) -> str:
        lines = []
        for name, eng in [("ROUND_ROBIN", self.rr_engine), ("LEAST_CONNECTIONS", self.lc_engine)]:
            lines.append(f"=== {name} ===")
            lines.append(f"TOTAL_REQUESTS: {eng.total_requests}")
            lines.append(f"COMPLETED: {eng.completed_requests}")
            lines.append(f"ACTIVE_IN_FLIGHT: {eng.get_active_in_flight()}")
            lines.append(f"PEAK_IN_FLIGHT: {eng.get_peak_in_flight()}")
            lines.append(f"SERVER_IN_FLIGHT: {[s.in_flight for s in eng.servers]}")
            lines.append(f"SERVER_ALLOCATIONS: {[s.allocations for s in eng.servers]}")
        return "\n".join(lines)

def run():
    input_data = sys.stdin.read().splitlines()
    simulator = None
    output = []

    for line in input_data:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split()
        cmd = parts[0]

        if cmd == "INIT":
            num_servers = int(parts[1])
            simulator = Simulator(num_servers)
            output.append(f"INITIALIZED NUM_SERVERS={num_servers}")

        elif cmd == "REQUEST":
            req_id = parts[1]
            duration = int(parts[2])
            simulator.route(req_id, duration)
            output.append(f"ROUTED {req_id} DURATION={duration}")

        elif cmd == "STEP":
            ticks = int(parts[1])
            res = simulator.step(ticks)
            output.append(res)

        elif cmd == "RUN_UNTIL_IDLE":
            max_ticks = int(parts[1])
            res = simulator.run_until_idle(max_ticks)
            output.append(res)

        elif cmd == "STATUS":
            output.append(simulator.get_status())

    print("\n".join(output))

if __name__ == "__main__":
    run()
