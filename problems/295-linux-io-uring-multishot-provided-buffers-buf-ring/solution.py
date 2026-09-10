# -*- coding: utf-8 -*-
"""
ZeliJudge Pro Track Problem #295: Linux io_uring Multishot Receive & Provided Buffer Ring (io_uring_buf_ring)
https://github.com/hajunho/ZeliJudge
"""

import sys
import json
from collections import deque

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ENOBUFS = -105
ECANCELED = -125
IORING_CQE_F_MORE = 1
IORING_CQE_F_BUFFER = 2

class ProvidedBuffer:
    def __init__(self, bid, length):
        self.bid = bid
        self.length = length

class IOUringEngine:
    def __init__(self, config):
        self.sq_depth = config.get("sq_depth", 128)
        self.cq_depth = config.get("cq_depth", 256)
        self.buf_groups = {}  # bgid -> deque of ProvidedBuffer
        self.armed_multishot = {}  # fd -> req_info
        self.cqes = []
        
        self.stats = {
            "multishot_recvs_completed": 0,
            "total_bytes_received": 0,
            "enobufs_starvation_count": 0,
            "requests_armed": 0,
            "requests_terminated_eof": 0,
            "requests_cancelled": 0
        }

    def provide_buffers(self, bgid, buffers):
        if bgid not in self.buf_groups:
            self.buf_groups[bgid] = deque()
        for b in buffers:
            self.buf_groups[bgid].append(ProvidedBuffer(b["bid"], b.get("len", 4096)))

    def submit_multishot_recv(self, time_us, user_data, fd, bgid):
        self.stats["requests_armed"] += 1
        self.armed_multishot[fd] = {
            "user_data": user_data,
            "fd": fd,
            "bgid": bgid,
            "armed_time_us": time_us,
            "status": "ARMED"
        }

    def handle_socket_data(self, time_us, fd, data_len):
        req = self.armed_multishot.get(fd)
        if not req or req["status"] != "ARMED":
            return

        bgid = req["bgid"]
        group = self.buf_groups.get(bgid, deque())

        if data_len == 0:
            self.stats["requests_terminated_eof"] += 1
            req["status"] = "TERMINATED_EOF"
            self.cqes.append({
                "time_us": time_us,
                "user_data": req["user_data"],
                "res": 0,
                "flags": 0,
                "buffer_id": None,
                "multishot_active": False
            })
            del self.armed_multishot[fd]
            return

        if len(group) == 0:
            self.stats["enobufs_starvation_count"] += 1
            req["status"] = "DISARMED_ENOBUFS"
            self.cqes.append({
                "time_us": time_us,
                "user_data": req["user_data"],
                "res": ENOBUFS,
                "flags": 0,
                "buffer_id": None,
                "multishot_active": False
            })
            del self.armed_multishot[fd]
            return

        buf = group.popleft()
        transferred = min(data_len, buf.length)
        self.stats["multishot_recvs_completed"] += 1
        self.stats["total_bytes_received"] += transferred

        self.cqes.append({
            "time_us": time_us,
            "user_data": req["user_data"],
            "res": transferred,
            "flags": IORING_CQE_F_MORE | IORING_CQE_F_BUFFER,
            "buffer_id": buf.bid,
            "multishot_active": True
        })

    def replenish_buffer(self, bgid, bid, length=4096):
        if bgid not in self.buf_groups:
            self.buf_groups[bgid] = deque()
        self.buf_groups[bgid].append(ProvidedBuffer(bid, length))

    def cancel_request(self, time_us, user_data):
        target_fd = None
        for fd, req in self.armed_multishot.items():
            if req["user_data"] == user_data:
                target_fd = fd
                break
        if target_fd:
            req = self.armed_multishot.pop(target_fd)
            self.stats["requests_cancelled"] += 1
            self.cqes.append({
                "time_us": time_us,
                "user_data": user_data,
                "res": ECANCELED,
                "flags": 0,
                "buffer_id": None,
                "multishot_active": False
            })

def simulate_io_uring(data):
    config = data.get("config", {})
    initial_buffers = data.get("initial_buffers", [])
    events = data.get("events", [])

    ring = IOUringEngine(config)

    # Load initial buffer rings
    for group in initial_buffers:
        ring.provide_buffers(group["bgid"], group.get("buffers", []))

    for ev in events:
        ev_type = ev.get("type")
        time_us = ev.get("time_us", 0.0)

        if ev_type == "SUBMIT_MULTISHOT":
            ring.submit_multishot_recv(time_us, ev.get("user_data"), ev.get("fd"), ev.get("bgid", 0))
        elif ev_type == "SOCKET_DATA":
            ring.handle_socket_data(time_us, ev.get("fd"), ev.get("data_len", 0))
        elif ev_type == "REPLENISH":
            ring.replenish_buffer(ev.get("bgid", 0), ev.get("bid"), ev.get("len", 4096))
        elif ev_type == "CANCEL":
            ring.cancel_request(time_us, ev.get("user_data"))

    # Buffer group status summary
    buf_group_status = {}
    for bgid, group in ring.buf_groups.items():
        buf_group_status[f"bgid_{bgid}"] = {
            "available_buffers": len(group),
            "head_buffer_id": group[0].bid if len(group) > 0 else None
        }

    anomalies = []
    status = "OPTIMAL_ZERO_ALLOC_MULTISHOT"
    if ring.stats["enobufs_starvation_count"] > 0:
        status = "BUFFER_RING_STARVATION_DETECTED"
        anomalies.append("BUFFER_RING_EXHAUSTION_DISARM")

    return {
        "metrics": ring.stats,
        "buf_group_status": buf_group_status,
        "diagnostics": {
            "status": status,
            "anomalies": anomalies
        },
        "cqe_sample": ring.cqes[:20]
    }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    result = simulate_io_uring(data)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))

if __name__ == "__main__":
    main()
