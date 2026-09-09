import sys

class Port:
    def __init__(self, port_number):
        self.port_number = port_number
        self.state = "FREE"  # FREE, ACTIVE, TIME_WAIT
        self.tw_entered_at = 0
        self.tw_expires_at = 0
        self.owner_pool = None

class TcpPortSimulator:
    def __init__(self):
        self.port_start = 30000
        self.port_end = 30004
        self.tw_duration_ms = 60000
        self.tw_reuse = 0
        self.current_time_ms = 0
        self.exhaustion_errors = 0
        self.reused_count = 0
        self.ports = {}
        self.pools = {}

    def config(self, port_start, port_end, tw_duration_ms, tw_reuse):
        self.port_start = port_start
        self.port_end = port_end
        self.tw_duration_ms = tw_duration_ms
        self.tw_reuse = tw_reuse
        self.current_time_ms = 0
        self.exhaustion_errors = 0
        self.reused_count = 0
        self.ports = {p: Port(p) for p in range(port_start, port_end + 1)}
        self.pools = {}
        total = len(self.ports)
        return f"CONFIG_OK ports={port_start}-{port_end} total={total} tw_duration={tw_duration_ms}ms tw_reuse={tw_reuse}"

    def _allocate_port(self):
        # 1. Search for FREE port (smallest port number)
        free_ports = [p for p in self.ports.values() if p.state == "FREE"]
        if free_ports:
            free_ports.sort(key=lambda x: x.port_number)
            return free_ports[0], False

        # 2. If tw_reuse is enabled, search for TIME_WAIT port >= 1000ms old
        if self.tw_reuse == 1:
            reusable_ports = [
                p for p in self.ports.values()
                if p.state == "TIME_WAIT" and (self.current_time_ms - p.tw_entered_at) >= 1000
            ]
            if reusable_ports:
                # Pick the oldest TIME_WAIT port (earliest tw_entered_at, then smallest port_number)
                reusable_ports.sort(key=lambda x: (x.tw_entered_at, x.port_number))
                return reusable_ports[0], True

        # 3. Exhaustion
        self.exhaustion_errors += 1
        return None, False

    def req_short(self, req_id, dst):
        port, reused = self._allocate_port()
        if port is None:
            return f"REQ:{req_id} ERROR:CANNOT_ASSIGN_REQUESTED_ADDRESS"

        # Active Close -> TIME_WAIT
        port.state = "TIME_WAIT"
        port.tw_entered_at = self.current_time_ms
        port.tw_expires_at = self.current_time_ms + self.tw_duration_ms
        port.owner_pool = None

        if reused:
            self.reused_count += 1
            return f"REQ:{req_id} PORT:{port.port_number} STATUS:CLOSED_TO_TIME_WAIT [REUSED]"
        return f"REQ:{req_id} PORT:{port.port_number} STATUS:CLOSED_TO_TIME_WAIT"

    def req_pool(self, req_id, pool_id, dst):
        if pool_id in self.pools and len(self.pools[pool_id]) > 0:
            # Reuse existing idle connection in pool
            port_num = self.pools[pool_id].pop(0)
            self.pools[pool_id].append(port_num)
            return f"REQ:{req_id} POOL:{pool_id} PORT:{port_num} STATUS:REUSED_FROM_POOL"

        # Need to establish a new connection for pool
        port, reused = self._allocate_port()
        if port is None:
            return f"REQ:{req_id} ERROR:CANNOT_ASSIGN_REQUESTED_ADDRESS"

        port.state = "ACTIVE"
        port.owner_pool = pool_id
        if pool_id not in self.pools:
            self.pools[pool_id] = []
        self.pools[pool_id].append(port.port_number)

        if reused:
            self.reused_count += 1
            return f"REQ:{req_id} POOL:{pool_id} PORT:{port.port_number} STATUS:NEW_POOL_CONN [REUSED]"
        return f"REQ:{req_id} POOL:{pool_id} PORT:{port.port_number} STATUS:NEW_POOL_CONN"

    def release_pool(self, pool_id):
        closed_count = 0
        if pool_id in self.pools:
            for port_num in self.pools[pool_id]:
                port = self.ports[port_num]
                port.state = "TIME_WAIT"
                port.tw_entered_at = self.current_time_ms
                port.tw_expires_at = self.current_time_ms + self.tw_duration_ms
                port.owner_pool = None
                closed_count += 1
            del self.pools[pool_id]
        return f"POOL_RELEASED:{pool_id} closed_conns={closed_count}"

    def tick(self, delta_ms):
        self.current_time_ms += delta_ms
        expired_tw = 0
        for port in self.ports.values():
            if port.state == "TIME_WAIT" and self.current_time_ms >= port.tw_expires_at:
                port.state = "FREE"
                port.tw_entered_at = 0
                port.tw_expires_at = 0
                expired_tw += 1

        free_count = sum(1 for p in self.ports.values() if p.state == "FREE")
        return f"TICK_OK time={self.current_time_ms}ms expired_tw={expired_tw} free_ports={free_count}"

    def stats(self):
        total = len(self.ports)
        free = sum(1 for p in self.ports.values() if p.state == "FREE")
        active = sum(1 for p in self.ports.values() if p.state == "ACTIVE")
        time_wait = sum(1 for p in self.ports.values() if p.state == "TIME_WAIT")
        exhaustions = self.exhaustion_errors
        reused = self.reused_count
        util = ((active + time_wait) / total * 100.0) if total > 0 else 0.0

        if free == 0:
            health = "EXHAUSTED"
        elif util >= 75.0:
            health = "WARNING"
        else:
            health = "HEALTHY"

        return f"STATS ports={total} free={free} active={active} time_wait={time_wait} exhaustions={exhaustions} reused={reused} util={util:.1f}% health={health}"

def main():
    sim = TcpPortSimulator()
    lines = sys.stdin.read().splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        cmd = parts[0].upper()

        if cmd == "CONFIG":
            start_p = int(parts[1])
            end_p = int(parts[2])
            tw_dur = int(parts[3])
            tw_reuse = int(parts[4])
            print(sim.config(start_p, end_p, tw_dur, tw_reuse))
        elif cmd == "REQ_SHORT":
            req_id = parts[1]
            dst = parts[2]
            print(sim.req_short(req_id, dst))
        elif cmd == "REQ_POOL":
            req_id = parts[1]
            pool_id = parts[2]
            dst = parts[3]
            print(sim.req_pool(req_id, pool_id, dst))
        elif cmd == "RELEASE_POOL":
            pool_id = parts[1]
            print(sim.release_pool(pool_id))
        elif cmd == "TICK":
            delta_ms = int(parts[1])
            print(sim.tick(delta_ms))
        elif cmd == "STATS":
            print(sim.stats())

if __name__ == '__main__':
    main()
