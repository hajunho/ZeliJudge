import sys
import json
import heapq
from collections import deque

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class Packet:
    def __init__(self, packet_id, flow_id, size_bytes, arrival_time_ns, skb_tstamp_ns):
        self.packet_id = packet_id
        self.flow_id = flow_id
        self.size_bytes = size_bytes
        self.arrival_time_ns = arrival_time_ns
        self.skb_tstamp_ns = skb_tstamp_ns

class Flow:
    def __init__(self, flow_id, initial_quantum):
        self.flow_id = flow_id
        self.initial_quantum = initial_quantum
        self.credit = initial_quantum
        self.socket_pacing_rate = 0
        self.time_next_packet = 0
        self.queue = deque()
        self.state = "INACTIVE"
        self.packets_enqueued = 0
        self.packets_dequeued = 0
        self.bytes_dequeued = 0
        self.packets_dropped = 0

class FQEngine:
    def __init__(self, config):
        self.quantum = config.get("quantum", 1514)
        self.initial_quantum = config.get("initial_quantum", self.quantum)
        self.limit = config.get("limit", 100)
        self.flow_limit = config.get("flow_limit", 20)
        self.current_time_ns = 0
        self.total_qlen = 0
        self.total_byte_len = 0
        self.drops_global_limit = 0
        self.drops_flow_limit = 0
        
        self.flows = {}
        self.new_flows = deque()
        self.old_flows = deque()
        self.throttled_heap = []
        self.throttled_set = set()
        self._tie_counter = 0

    def _unthrottle(self):
        while self.throttled_heap and self.throttled_heap[0][0] <= self.current_time_ns:
            tstamp, _, fid = heapq.heappop(self.throttled_heap)
            if fid not in self.throttled_set:
                continue
            self.throttled_set.remove(fid)
            flow = self.flows[fid]
            if len(flow.queue) > 0:
                flow.state = "OLD"
                self.old_flows.append(flow)
            else:
                flow.state = "INACTIVE"

    def advance_time(self, new_time_ns):
        if new_time_ns > self.current_time_ns:
            self.current_time_ns = new_time_ns
            self._unthrottle()

    def enqueue(self, op):
        arr_time = op.get("arrival_time_ns", self.current_time_ns)
        if arr_time > self.current_time_ns:
            self.advance_time(arr_time)

        pkt_id = op["packet_id"]
        fid = op["flow_id"]
        size = op["size_bytes"]
        skb_tstamp = op.get("skb_tstamp_ns", 0)
        pacing_rate = op.get("pacing_rate_bps", 0)

        if fid not in self.flows:
            self.flows[fid] = Flow(fid, self.initial_quantum)
        flow = self.flows[fid]

        if pacing_rate > 0:
            flow.socket_pacing_rate = pacing_rate

        if self.total_qlen >= self.limit:
            flow.packets_dropped += 1
            self.drops_global_limit += 1
            return {"status": "DROPPED_GLOBAL_LIMIT", "packet_id": pkt_id, "flow_id": fid}

        if len(flow.queue) >= self.flow_limit:
            flow.packets_dropped += 1
            self.drops_flow_limit += 1
            return {"status": "DROPPED_FLOW_LIMIT", "packet_id": pkt_id, "flow_id": fid}

        pkt = Packet(pkt_id, fid, size, arr_time, skb_tstamp)
        flow.queue.append(pkt)
        flow.packets_enqueued += 1
        self.total_qlen += 1
        self.total_byte_len += size

        if flow.state == "INACTIVE":
            flow.credit = self.initial_quantum
            flow.time_next_packet = max(flow.time_next_packet, arr_time)
            req_time = max(flow.time_next_packet, skb_tstamp)
            if req_time > self.current_time_ns:
                flow.time_next_packet = req_time
                flow.state = "THROTTLED"
                self._tie_counter += 1
                heapq.heappush(self.throttled_heap, (req_time, self._tie_counter, fid))
                self.throttled_set.add(fid)
            else:
                flow.state = "NEW"
                self.new_flows.append(flow)

        return {
            "status": "ENQUEUED",
            "packet_id": pkt_id,
            "flow_id": fid,
            "flow_qlen": len(flow.queue),
            "total_qlen": self.total_qlen
        }

    def dequeue(self, op):
        count = op.get("count", 1)
        dequeued = []

        while len(dequeued) < count:
            selected_flow = None
            from_queue = None

            # 1. Check new_flows
            while self.new_flows:
                f = self.new_flows[0]
                if len(f.queue) == 0:
                    self.new_flows.popleft()
                    f.state = "INACTIVE"
                    continue
                head_pkt = f.queue[0]
                req_time = max(f.time_next_packet, head_pkt.skb_tstamp_ns)
                if req_time > self.current_time_ns:
                    self.new_flows.popleft()
                    f.time_next_packet = req_time
                    f.state = "THROTTLED"
                    self._tie_counter += 1
                    heapq.heappush(self.throttled_heap, (req_time, self._tie_counter, f.flow_id))
                    self.throttled_set.add(f.flow_id)
                    continue
                if f.credit <= 0:
                    self.new_flows.popleft()
                    f.credit += self.quantum
                    f.state = "OLD"
                    self.old_flows.append(f)
                    continue
                selected_flow = f
                from_queue = "new_flows"
                break

            # 2. Check old_flows
            if selected_flow is None:
                while self.old_flows:
                    f = self.old_flows[0]
                    if len(f.queue) == 0:
                        self.old_flows.popleft()
                        f.state = "INACTIVE"
                        continue
                    head_pkt = f.queue[0]
                    req_time = max(f.time_next_packet, head_pkt.skb_tstamp_ns)
                    if req_time > self.current_time_ns:
                        self.old_flows.popleft()
                        f.time_next_packet = req_time
                        f.state = "THROTTLED"
                        self._tie_counter += 1
                        heapq.heappush(self.throttled_heap, (req_time, self._tie_counter, f.flow_id))
                        self.throttled_set.add(f.flow_id)
                        continue
                    if f.credit <= 0:
                        self.old_flows.popleft()
                        f.credit += self.quantum
                        self.old_flows.append(f)
                        continue
                    selected_flow = f
                    from_queue = "old_flows"
                    break

            if selected_flow is None:
                break

            f = selected_flow
            pkt = f.queue.popleft()
            self.total_qlen -= 1
            self.total_byte_len -= pkt.size_bytes
            f.credit -= pkt.size_bytes
            f.packets_dequeued += 1
            f.bytes_dequeued += pkt.size_bytes

            dep_time = self.current_time_ns
            if f.socket_pacing_rate > 0:
                pacing_delay = (pkt.size_bytes * 1_000_000_000) // f.socket_pacing_rate
                f.time_next_packet = dep_time + pacing_delay
            else:
                f.time_next_packet = dep_time

            exhausted_credit = (f.credit <= 0)
            if exhausted_credit:
                f.credit += self.quantum

            dequeued.append({
                "packet_id": pkt.packet_id,
                "flow_id": f.flow_id,
                "size_bytes": pkt.size_bytes,
                "departure_time_ns": dep_time,
                "flow_credit_after": f.credit
            })

            if len(f.queue) == 0:
                if from_queue == "new_flows":
                    self.new_flows.popleft()
                else:
                    self.old_flows.popleft()
                f.state = "INACTIVE"
            else:
                next_pkt = f.queue[0]
                next_req = max(f.time_next_packet, next_pkt.skb_tstamp_ns)
                if next_req > self.current_time_ns:
                    if from_queue == "new_flows":
                        self.new_flows.popleft()
                    else:
                        self.old_flows.popleft()
                    f.time_next_packet = next_req
                    f.state = "THROTTLED"
                    self._tie_counter += 1
                    heapq.heappush(self.throttled_heap, (next_req, self._tie_counter, f.flow_id))
                    self.throttled_set.add(f.flow_id)
                elif exhausted_credit:
                    if from_queue == "new_flows":
                        self.new_flows.popleft()
                        f.state = "OLD"
                        self.old_flows.append(f)
                    else:
                        self.old_flows.popleft()
                        self.old_flows.append(f)
                else:
                    pass

        return {"dequeued": dequeued, "count": len(dequeued)}

    def get_flow_stats(self, fid):
        if fid not in self.flows:
            return None
        f = self.flows[fid]
        return {
            "flow_id": f.flow_id,
            "state": f.state,
            "credit": f.credit,
            "qlen": len(f.queue),
            "byte_len": sum(p.size_bytes for p in f.queue),
            "time_next_packet": f.time_next_packet,
            "packets_enqueued": f.packets_enqueued,
            "packets_dequeued": f.packets_dequeued,
            "bytes_dequeued": f.bytes_dequeued,
            "packets_dropped": f.packets_dropped
        }

    def get_qdisc_stats(self):
        return {
            "current_time_ns": self.current_time_ns,
            "total_qlen": self.total_qlen,
            "total_byte_len": self.total_byte_len,
            "new_flows_count": len(self.new_flows),
            "old_flows_count": len(self.old_flows),
            "throttled_flows_count": len(self.throttled_set),
            "drops_global_limit": self.drops_global_limit,
            "drops_flow_limit": self.drops_flow_limit
        }

def solve():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    engine = FQEngine(data.get("config", {}))
    results = []
    for op in data.get("operations", []):
        name = op["op"]
        if name == "ENQUEUE":
            results.append(engine.enqueue(op))
        elif name == "DEQUEUE":
            results.append(engine.dequeue(op))
        elif name == "ADVANCE_TIME":
            engine.advance_time(op["current_time_ns"])
            results.append({"status": "TIME_ADVANCED", "current_time_ns": engine.current_time_ns})
        elif name == "GET_FLOW_STATS":
            results.append(engine.get_flow_stats(op["flow_id"]))
        elif name == "GET_QDISC_STATS":
            results.append(engine.get_qdisc_stats())
        else:
            raise ValueError(f"Unknown op: {name}")

    print(json.dumps(results, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    solve()
