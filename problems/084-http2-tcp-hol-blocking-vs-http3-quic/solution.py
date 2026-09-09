import sys

class ProtocolSimulator:
    def __init__(self, num_streams: int, packets_per_stream: int, retransmit_rtt: int):
        self.num_streams = num_streams
        self.packets_per_stream = packets_per_stream
        self.retransmit_rtt = retransmit_rtt
        self.losses = set()  # set of (stream_id, packet_idx)

    def add_loss(self, stream_id: int, packet_idx: int):
        self.losses.add((stream_id, packet_idx))

    def _get_arrival_tick(self, stream_id: int, packet_idx: int) -> int:
        base_arrival = packet_idx + 1
        if (stream_id, packet_idx) in self.losses:
            return base_arrival + self.retransmit_rtt
        return base_arrival

    def simulate_http3(self):
        # Independent UDP streams
        normal_finish = self.packets_per_stream
        finish_times = []
        blocked_count = 0

        for s in range(1, self.num_streams + 1):
            s_finish = max(self._get_arrival_tick(s, p) for p in range(self.packets_per_stream))
            finish_times.append(s_finish)
            if s_finish > normal_finish:
                blocked_count += 1

        total_ticks = max(finish_times) if finish_times else 0
        return total_ticks, blocked_count, finish_times

    def simulate_http1(self):
        # Parallel independent TCP connections (1 connection per stream)
        normal_finish = self.packets_per_stream
        finish_times = []
        blocked_count = 0

        for s in range(1, self.num_streams + 1):
            s_finish = max(self._get_arrival_tick(s, p) for p in range(self.packets_per_stream))
            finish_times.append(s_finish)
            if s_finish > normal_finish:
                blocked_count += 1

        total_ticks = max(finish_times) if finish_times else 0
        return total_ticks, blocked_count, finish_times

    def simulate_http2(self):
        # Single TCP connection with interleaved streams: (P0: S1..Sm), (P1: S1..Sm)...
        global_packets = []
        for p in range(self.packets_per_stream):
            for s in range(1, self.num_streams + 1):
                arr = self._get_arrival_tick(s, p)
                global_packets.append((s, p, arr))

        # TCP in-order delivery
        running_max = 0
        stream_packet_delivers = {s: [] for s in range(1, self.num_streams + 1)}

        for s, p, arr in global_packets:
            running_max = max(running_max, arr)
            stream_packet_delivers[s].append(running_max)

        normal_finish = self.packets_per_stream
        finish_times = []
        blocked_count = 0

        for s in range(1, self.num_streams + 1):
            s_finish = max(stream_packet_delivers[s])
            finish_times.append(s_finish)
            if s_finish > normal_finish:
                blocked_count += 1

        total_ticks = max(finish_times) if finish_times else 0
        return total_ticks, blocked_count, finish_times

    def run_simulation(self) -> str:
        h1_tot, h1_blk, h1_times = self.simulate_http1()
        h2_tot, h2_blk, h2_times = self.simulate_http2()
        h3_tot, h3_blk, h3_times = self.simulate_http3()

        lines = [
            "=== HTTP/1.1 (PARALLEL TCP) ===",
            f"TOTAL_TICKS: {h1_tot}",
            f"BLOCKED_STREAMS: {h1_blk}",
            f"STREAM_FINISH_TIMES: {h1_times}",
            "=== HTTP/2 (SINGLE TCP MULTIPLEXING) ===",
            f"TOTAL_TICKS: {h2_tot}",
            f"BLOCKED_STREAMS: {h2_blk}",
            f"STREAM_FINISH_TIMES: {h2_times}",
            "=== HTTP/3 QUIC (INDEPENDENT UDP STREAMS) ===",
            f"TOTAL_TICKS: {h3_tot}",
            f"BLOCKED_STREAMS: {h3_blk}",
            f"STREAM_FINISH_TIMES: {h3_times}"
        ]
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
            streams = int(parts[1])
            packets = int(parts[2])
            rtt = int(parts[3])
            simulator = ProtocolSimulator(streams, packets, rtt)
            output.append(f"INITIALIZED STREAMS={streams} PACKETS_PER_STREAM={packets} RETRANSMIT_RTT={rtt}")

        elif cmd == "SET_PACKET_LOSS":
            s_id = int(parts[1])
            p_idx = int(parts[2])
            simulator.add_loss(s_id, p_idx)
            output.append(f"PACKET_LOSS_SCHEDULED STREAM={s_id} PACKET={p_idx}")

        elif cmd == "SIMULATE":
            output.append(simulator.run_simulation())

    print("\n".join(output))

if __name__ == "__main__":
    run()
