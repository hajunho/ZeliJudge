import sys
import json

# Windows 콘솔 UTF-8 입출력 호환성 보장
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

IOSQE_BUFFER_SELECT = 0x0001
IORING_RECV_MULTISHOT = 0x0004

IORING_CQE_F_BUFFER = 0x0001
IORING_CQE_F_MORE = 0x0002
IORING_CQE_F_NOTIF = 0x0004
IORING_CQE_BUFFER_SHIFT = 16

ENOBUFS = -105

class IoUringBufRingEngine:
    def __init__(self):
        self.buf_rings = {}
        self.recv_requests = {}
        self.zc_sends = {}
        self.cqes = []
        self.total_buffers_consumed = 0
        self.total_packets_received = 0
        self.total_bytes_received = 0
        self.total_bytes_sent_zc = 0
        self.starvation_count = 0

    def register_buf_ring(self, bgid: int, ring_size: int):
        self.buf_rings[bgid] = {
            "size": ring_size,
            "ring": [{"bid": 0, "addr": 0, "len": 0} for _ in range(ring_size)],
            "head": 0,
            "tail": 0
        }
        return {"status": "BUF_RING_REGISTERED", "bgid": bgid, "ring_size": ring_size}

    def add_buffers(self, bgid: int, buffers: list):
        br = self.buf_rings.get(bgid)
        if not br:
            return {"status": "ERROR_NO_SUCH_BGID", "bgid": bgid}

        added = 0
        for b in buffers:
            idx = br["tail"] % br["size"]
            br["ring"][idx] = {
                "bid": b["bid"],
                "addr": b["addr"],
                "len": b["len"]
            }
            br["tail"] += 1
            added += 1

        avail = br["tail"] - br["head"]
        return {
            "status": "BUFFERS_ADDED",
            "bgid": bgid,
            "added_count": added,
            "tail": br["tail"],
            "head": br["head"],
            "available_buffers": avail
        }

    def submit_recv(self, user_data: int, fd: int, bgid: int, multishot: bool = True):
        self.recv_requests[user_data] = {
            "user_data": user_data,
            "fd": fd,
            "bgid": bgid,
            "multishot": multishot,
            "active": True
        }
        return {
            "status": "RECV_SUBMITTED",
            "user_data": user_data,
            "fd": fd,
            "bgid": bgid,
            "multishot": multishot
        }

    def incoming_packet(self, fd: int, payload_len: int, is_eof: bool = False, is_error: bool = False):
        req = None
        for r in self.recv_requests.values():
            if r["active"] and r["fd"] == fd:
                req = r
                break

        if not req:
            return {"status": "NO_MATCHING_RECV_REQ", "fd": fd}

        u_data = req["user_data"]
        bgid = req["bgid"]
        br = self.buf_rings.get(bgid)

        if not br or (br["head"] == br["tail"]):
            self.starvation_count += 1
            req["active"] = False
            cqe = {
                "user_data": u_data,
                "res": ENOBUFS,
                "flags": 0,
                "bid": None,
                "is_notif": False
            }
            self.cqes.append(cqe)
            return {
                "status": "BUFFER_STARVATION",
                "user_data": u_data,
                "res": ENOBUFS,
                "cqe_emitted": cqe
            }

        buf_idx = br["head"] % br["size"]
        buf = br["ring"][buf_idx]
        br["head"] += 1
        self.total_buffers_consumed += 1

        bytes_transferred = min(payload_len, buf["len"])
        self.total_packets_received += 1
        self.total_bytes_received += bytes_transferred

        flags = IORING_CQE_F_BUFFER | (buf["bid"] << IORING_CQE_BUFFER_SHIFT)

        if req["multishot"] and not is_eof and not is_error:
            flags |= IORING_CQE_F_MORE
        else:
            req["active"] = False

        cqe = {
            "user_data": u_data,
            "res": bytes_transferred,
            "flags": flags,
            "bid": buf["bid"],
            "is_notif": False
        }
        self.cqes.append(cqe)

        return {
            "status": "PACKET_PROCESSED",
            "user_data": u_data,
            "consumed_bid": buf["bid"],
            "bytes_transferred": bytes_transferred,
            "remaining_buffers": br["tail"] - br["head"],
            "cqe_emitted": cqe
        }

    def submit_send_zc(self, user_data: int, fd: int, addr: int, length: int):
        self.zc_sends[user_data] = {
            "fd": fd,
            "addr": addr,
            "len": length,
            "notif_pending": True
        }
        self.total_bytes_sent_zc += length

        cqe = {
            "user_data": user_data,
            "res": length,
            "flags": IORING_CQE_F_MORE,
            "bid": None,
            "is_notif": False
        }
        self.cqes.append(cqe)

        return {
            "status": "SEND_ZC_SUBMITTED",
            "user_data": user_data,
            "bytes_sent": length,
            "cqe_emitted": cqe
        }

    def nic_tx_complete(self, user_data: int):
        zc = self.zc_sends.get(user_data)
        if not zc or not zc["notif_pending"]:
            return {"status": "ERROR_NO_PENDING_NOTIF", "user_data": user_data}

        zc["notif_pending"] = False
        del self.zc_sends[user_data]

        cqe = {
            "user_data": user_data,
            "res": 0,
            "flags": IORING_CQE_F_NOTIF,
            "bid": None,
            "is_notif": True
        }
        self.cqes.append(cqe)

        return {
            "status": "NOTIF_EMITTED",
            "user_data": user_data,
            "cqe_emitted": cqe
        }

    def harvest_cqes(self, max_cqes: int = 16):
        count = min(max_cqes, len(self.cqes))
        harvested = self.cqes[:count]
        self.cqes = self.cqes[count:]
        return {
            "status": "CQES_HARVESTED",
            "count": len(harvested),
            "cqes": harvested,
            "remaining_cqes": len(self.cqes)
        }

    def inspect(self):
        buf_ring_stats = {}
        for bgid, br in self.buf_rings.items():
            buf_ring_stats[str(bgid)] = {
                "size": br["size"],
                "head": br["head"],
                "tail": br["tail"],
                "available": br["tail"] - br["head"]
            }

        active_recvs = [r["user_data"] for r in self.recv_requests.values() if r["active"]]
        pending_zcs = [u for u, z in self.zc_sends.items() if z["notif_pending"]]

        return {
            "buf_rings": buf_ring_stats,
            "active_recv_requests": active_recvs,
            "pending_zc_notifs": pending_zcs,
            "queued_cqe_count": len(self.cqes),
            "stats": {
                "total_buffers_consumed": self.total_buffers_consumed,
                "total_packets_received": self.total_packets_received,
                "total_bytes_received": self.total_bytes_received,
                "total_bytes_sent_zc": self.total_bytes_sent_zc,
                "starvation_count": self.starvation_count
            }
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return

    commands = json.loads(raw_input)
    engine = IoUringBufRingEngine()
    results = []

    for cmd in commands:
        op = cmd.get("op")
        if op == "REGISTER_BUF_RING":
            res = engine.register_buf_ring(cmd["bgid"], cmd["ring_size"])
            results.append({"op": "REGISTER_BUF_RING", "result": res})
        elif op == "ADD_BUFFERS":
            res = engine.add_buffers(cmd["bgid"], cmd["buffers"])
            results.append({"op": "ADD_BUFFERS", "result": res})
        elif op == "SUBMIT_RECV":
            res = engine.submit_recv(cmd["user_data"], cmd["fd"], cmd["bgid"], cmd.get("multishot", True))
            results.append({"op": "SUBMIT_RECV", "result": res})
        elif op == "INCOMING_PACKET":
            res = engine.incoming_packet(cmd["fd"], cmd["payload_len"], cmd.get("is_eof", False), cmd.get("is_error", False))
            results.append({"op": "INCOMING_PACKET", "result": res})
        elif op == "SUBMIT_SEND_ZC":
            res = engine.submit_send_zc(cmd["user_data"], cmd["fd"], cmd["addr"], cmd["len"])
            results.append({"op": "SUBMIT_SEND_ZC", "result": res})
        elif op == "NIC_TX_COMPLETE":
            res = engine.nic_tx_complete(cmd["user_data"])
            results.append({"op": "NIC_TX_COMPLETE", "result": res})
        elif op == "HARVEST_CQES":
            res = engine.harvest_cqes(cmd.get("max_cqes", 16))
            results.append({"op": "HARVEST_CQES", "result": res})
        elif op == "INSPECT":
            res = engine.inspect()
            results.append({"op": "INSPECT", "result": res})
        else:
            results.append({"op": op, "status": "UNKNOWN_OP"})

    print(json.dumps(results, separators=(',', ':')))

if __name__ == "__main__":
    main()
