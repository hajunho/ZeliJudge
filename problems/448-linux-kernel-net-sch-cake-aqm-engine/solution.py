import sys
import json
import hashlib

class CakeQdisc:
    def __init__(self, config):
        self.bandwidth_bps = config.get("bandwidth_bps", 100000000)
        self.diffserv_mode = config.get("diffserv_mode", "DIFFSERV4")
        self.ack_filter_enabled = config.get("ack_filter_enabled", True)
        self.target_us = config.get("target_us", 5000)
        self.interval_us = config.get("interval_us", 100000)
        
        self.tins = {
            0: {"name": "Bulk", "flows": {}},
            1: {"name": "BestEffort", "flows": {}},
            2: {"name": "Video", "flows": {}},
            3: {"name": "Voice", "flows": {}}
        }
        
        self.codel_states = {}
        self.stats = {
            "total_enqueued": 0,
            "total_dequeued": 0,
            "ack_filtered_count": 0,
            "aqm_dropped_count": 0,
            "ecn_marked_count": 0,
            "tin_stats": {
                0: {"packets": 0, "bytes": 0},
                1: {"packets": 0, "bytes": 0},
                2: {"packets": 0, "bytes": 0},
                3: {"packets": 0, "bytes": 0}
            }
        }

    def _classify_tin(self, dscp):
        if self.diffserv_mode == "DIFFSERV4":
            if dscp in [46, 48, 56]:
                return 3
            elif dscp in [24, 26, 32, 34, 40]:
                return 2
            elif dscp in [8, 10, 12, 14]:
                return 0
            else:
                return 1
        else:
            if dscp in [46, 48, 56]:
                return 3
            elif dscp in [8, 10, 12, 14]:
                return 0
            else:
                return 1

    def _hash_flow(self, src_ip, dst_ip, src_port, dst_port, proto):
        key = f"{src_ip}:{src_port}->{dst_ip}:{dst_port}/{proto}"
        h = int(hashlib.md5(key.encode()).hexdigest(), 16)
        set_idx = (h >> 16) % 128
        way_idx = (h & 0xFFFF) % 8
        flow_id = set_idx * 8 + way_idx
        return flow_id, key

    def enqueue(self, pkt):
        pkt_id = pkt["pkt_id"]
        time_us = pkt["time_us"]
        dscp = pkt.get("dscp", 0)
        src_ip = pkt.get("src_ip", "10.0.0.1")
        dst_ip = pkt.get("dst_ip", "10.0.0.2")
        src_port = pkt.get("src_port", 1234)
        dst_port = pkt.get("dst_port", 80)
        proto = pkt.get("proto", "TCP")
        length = pkt.get("len", 64)
        tcp_flags = pkt.get("tcp_flags", [])
        ack_seq = pkt.get("ack_seq", 0)
        ecn = pkt.get("ecn", 0)

        tin_id = self._classify_tin(dscp)
        flow_id, flow_key = self._hash_flow(src_ip, dst_ip, src_port, dst_port, proto)
        
        tin = self.tins[tin_id]
        if flow_id not in tin["flows"]:
            tin["flows"][flow_id] = []
        
        queue = tin["flows"][flow_id]
        
        ack_filtered = False
        is_pure_ack = (proto == "TCP" and tcp_flags == ["ACK"] and length <= 64)
        if self.ack_filter_enabled and is_pure_ack:
            for idx, existing in enumerate(queue):
                if (existing.get("proto") == "TCP" and 
                    existing.get("tcp_flags") == ["ACK"] and
                    existing.get("len", 64) <= 64 and
                    existing.get("ack_seq", 0) < ack_seq):
                    queue.pop(idx)
                    self.stats["ack_filtered_count"] += 1
                    ack_filtered = True
                    break
        
        packet_record = {
            "pkt_id": pkt_id,
            "enqueue_time": time_us,
            "tin": tin_id,
            "flow_id": flow_id,
            "flow_key": flow_key,
            "len": length,
            "ecn": ecn,
            "tcp_flags": tcp_flags,
            "ack_seq": ack_seq,
            "proto": proto
        }
        queue.append(packet_record)
        self.stats["total_enqueued"] += 1
        self.stats["tin_stats"][tin_id]["packets"] += 1
        self.stats["tin_stats"][tin_id]["bytes"] += length

        return {
            "status": "ENQUEUED",
            "pkt_id": pkt_id,
            "tin": tin_id,
            "flow_id": flow_id,
            "ack_filtered": ack_filtered
        }

    def dequeue(self, time_us):
        for tin_id in [3, 2, 1, 0]:
            tin = self.tins[tin_id]
            active_flow_ids = [fid for fid, q in tin["flows"].items() if len(q) > 0]
            if not active_flow_ids:
                continue

            active_flow_ids.sort()
            for flow_id in active_flow_ids:
                queue = tin["flows"][flow_id]
                if not queue:
                    continue

                while queue:
                    pkt = queue[0]
                    sojourn_us = time_us - pkt["enqueue_time"]
                    flow_key = pkt["flow_key"]
                    
                    if flow_key not in self.codel_states:
                        self.codel_states[flow_key] = {"first_above_time": 0, "dropping": False, "count": 0}
                    
                    cstate = self.codel_states[flow_key]
                    
                    if sojourn_us > self.target_us:
                        if cstate["first_above_time"] == 0:
                            cstate["first_above_time"] = time_us + self.interval_us
                        elif time_us >= cstate["first_above_time"]:
                            cstate["dropping"] = True
                    else:
                        cstate["first_above_time"] = 0
                        cstate["dropping"] = False
                    
                    if cstate["dropping"]:
                        if pkt["ecn"] in [1, 2]:
                            pkt["ecn"] = 3
                            action = "ECN_MARKED"
                            self.stats["ecn_marked_count"] += 1
                            queue.pop(0)
                            self.stats["total_dequeued"] += 1
                            return {
                                "status": "DEQUEUED",
                                "pkt_id": pkt["pkt_id"],
                                "action": action,
                                "tin": tin_id,
                                "sojourn_us": sojourn_us,
                                "len": pkt["len"],
                                "ecn": pkt["ecn"]
                            }
                        else:
                            dropped_pkt = queue.pop(0)
                            self.stats["aqm_dropped_count"] += 1
                            cstate["count"] += 1
                            return {
                                "status": "DEQUEUED",
                                "pkt_id": dropped_pkt["pkt_id"],
                                "action": "AQM_DROPPED",
                                "tin": tin_id,
                                "sojourn_us": sojourn_us,
                                "len": dropped_pkt["len"],
                                "ecn": dropped_pkt["ecn"]
                            }
                    else:
                        queue.pop(0)
                        self.stats["total_dequeued"] += 1
                        return {
                            "status": "DEQUEUED",
                            "pkt_id": pkt["pkt_id"],
                            "action": "DELIVERED",
                            "tin": tin_id,
                            "sojourn_us": sojourn_us,
                            "len": pkt["len"],
                            "ecn": pkt["ecn"]
                        }

        return {"status": "QUEUE_EMPTY"}

    def query_stats(self):
        return {
            "total_enqueued": self.stats["total_enqueued"],
            "total_dequeued": self.stats["total_dequeued"],
            "ack_filtered_count": self.stats["ack_filtered_count"],
            "aqm_dropped_count": self.stats["aqm_dropped_count"],
            "ecn_marked_count": self.stats["ecn_marked_count"],
            "tin_stats": {
                "0_Bulk": self.stats["tin_stats"][0],
                "1_BestEffort": self.stats["tin_stats"][1],
                "2_Video": self.stats["tin_stats"][2],
                "3_Voice": self.stats["tin_stats"][3]
            }
        }

def solve():
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    raw = sys.stdin.read().strip()
    if not raw:
        return

    input_data = json.loads(raw)
    config = input_data.get("config", {})
    cake = CakeQdisc(config)
    results = []

    for op in input_data.get("operations", []):
        cmd = op.get("op")
        if cmd == "ENQUEUE":
            res = cake.enqueue(op["packet"])
            results.append(res)
        elif cmd == "DEQUEUE":
            res = cake.dequeue(op["time_us"])
            results.append(res)
        elif cmd == "QUERY_STATS":
            res = cake.query_stats()
            results.append(res)

    out_obj = {"results": results}
    print(json.dumps(out_obj, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    solve()
