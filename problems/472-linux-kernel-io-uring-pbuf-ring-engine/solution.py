import sys
import json

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

class IoUringPbufRingEngine:
    IORING_CQE_F_BUFFER = 1 << 0      # 1
    IORING_CQE_F_MORE = 1 << 1        # 2
    IORING_CQE_BUFFER_SHIFT = 16
    ENOBUFS = 105
    ECANCELED = 125

    def __init__(self, config=None):
        self.config = config or {}
        self.rings = {}
        self.sockets = {}
        self.active_sqes = {}
        self.cqe_log = []
        self.stats = {
            "total_cqes": 0,
            "total_bytes_received": 0,
            "total_enobufs_errors": 0,
            "total_canceled_requests": 0,
            "total_truncated_packets": 0,
            "total_buffers_added": 0,
            "total_buffers_consumed": 0
        }

    def register_pbuf_ring(self, bgid, ring_entries, watermark=1):
        assert (ring_entries & (ring_entries - 1)) == 0, "ring_entries must be power of 2"
        self.rings[bgid] = {
            "bgid": bgid,
            "capacity": ring_entries,
            "mask": ring_entries - 1,
            "watermark": watermark,
            "head": 0,
            "tail": 0,
            "bufs": [None] * ring_entries
        }

    def add_buffers(self, bgid, buffers):
        ring = self.rings[bgid]
        added = []
        for b in buffers:
            idx = ring["tail"] & ring["mask"]
            buf_entry = {
                "bid": b["bid"],
                "addr": b["addr"],
                "len": b["len"]
            }
            ring["bufs"][idx] = buf_entry
            ring["tail"] = (ring["tail"] + 1) & 0xFFFF
            self.stats["total_buffers_added"] += 1
            added.append(buf_entry)
        avail = (ring["tail"] - ring["head"]) & 0xFFFF
        return {
            "bgid": bgid,
            "count_added": len(added),
            "tail": ring["tail"],
            "available_buffers": avail,
            "low_buffer_warning": avail < ring["watermark"]
        }

    def submit_recv(self, sqe_id, fd, bgid, multishot=False, socket_type="TCP"):
        if fd not in self.sockets:
            self.sockets[fd] = {
                "fd": fd,
                "type": socket_type,
                "rx_queue": [],
                "eof": False
            }
        sqe = {
            "sqe_id": sqe_id,
            "fd": fd,
            "bgid": bgid,
            "multishot": multishot,
            "socket_type": socket_type
        }
        self.active_sqes[fd] = sqe
        cqes = self._drain_socket(fd)
        return {
            "sqe_id": sqe_id,
            "fd": fd,
            "bgid": bgid,
            "multishot": multishot,
            "cqes_generated": len(cqes)
        }

    def cancel_recv(self, sqe_id, fd):
        if fd in self.active_sqes and self.active_sqes[fd]["sqe_id"] == sqe_id:
            del self.active_sqes[fd]
            self.stats["total_canceled_requests"] += 1
            cqe = {
                "sqe_id": sqe_id,
                "fd": fd,
                "res": -self.ECANCELED,
                "flags": 0,
                "bid": None,
                "buf_addr": None,
                "bytes_read": 0,
                "multishot_active": False,
                "status": "ECANCELED"
            }
            self.cqe_log.append(cqe)
            self.stats["total_cqes"] += 1
            return {
                "sqe_id": sqe_id,
                "fd": fd,
                "canceled": True,
                "status": "ECANCELED"
            }
        return {
            "sqe_id": sqe_id,
            "fd": fd,
            "canceled": False,
            "status": "NOT_FOUND"
        }

    def rx_packet_arrival(self, fd, payload_bytes, data_tag="packet", eof=False, socket_type="TCP"):
        if fd not in self.sockets:
            self.sockets[fd] = {
                "fd": fd,
                "type": socket_type,
                "rx_queue": [],
                "eof": False
            }
        sock = self.sockets[fd]
        if payload_bytes > 0:
            sock["rx_queue"].append({"bytes": payload_bytes, "tag": data_tag})
        if eof:
            sock["eof"] = True

        cqes = self._drain_socket(fd)
        return {
            "fd": fd,
            "payload_bytes": payload_bytes,
            "data_tag": data_tag,
            "eof": eof,
            "cqes_generated": len(cqes)
        }

    def _drain_socket(self, fd):
        sock = self.sockets.get(fd)
        if not sock:
            return []
        sqe = self.active_sqes.get(fd)
        if not sqe:
            return []

        generated_cqes = []
        bgid = sqe["bgid"]
        ring = self.rings.get(bgid)
        if not ring:
            return []

        while True:
            if not sock["rx_queue"]:
                if sock["eof"]:
                    cqe = {
                        "sqe_id": sqe["sqe_id"],
                        "fd": fd,
                        "res": 0,
                        "flags": 0,
                        "bid": None,
                        "buf_addr": None,
                        "bytes_read": 0,
                        "multishot_active": False,
                        "status": "EOF"
                    }
                    self.cqe_log.append(cqe)
                    generated_cqes.append(cqe)
                    self.stats["total_cqes"] += 1
                    del self.active_sqes[fd]
                break

            avail = (ring["tail"] - ring["head"]) & 0xFFFF
            if avail == 0:
                cqe = {
                    "sqe_id": sqe["sqe_id"],
                    "fd": fd,
                    "res": -self.ENOBUFS,
                    "flags": 0,
                    "bid": None,
                    "buf_addr": None,
                    "bytes_read": 0,
                    "multishot_active": False,
                    "status": "ENOBUFS"
                }
                self.cqe_log.append(cqe)
                generated_cqes.append(cqe)
                self.stats["total_cqes"] += 1
                self.stats["total_enobufs_errors"] += 1
                del self.active_sqes[fd]
                break

            idx = ring["head"] & ring["mask"]
            buf = ring["bufs"][idx]
            ring["head"] = (ring["head"] + 1) & 0xFFFF
            self.stats["total_buffers_consumed"] += 1

            if sock["type"] == "TCP":
                item = sock["rx_queue"][0]
                available_bytes = item["bytes"]
                bytes_to_read = min(available_bytes, buf["len"])
                item["bytes"] -= bytes_to_read
                if item["bytes"] == 0:
                    sock["rx_queue"].pop(0)
                truncated = False
                truncated_bytes = 0
            else:
                item = sock["rx_queue"].pop(0)
                datagram_len = item["bytes"]
                bytes_to_read = min(datagram_len, buf["len"])
                if datagram_len > buf["len"]:
                    truncated = True
                    truncated_bytes = datagram_len - buf["len"]
                    self.stats["total_truncated_packets"] += 1
                else:
                    truncated = False
                    truncated_bytes = 0

            self.stats["total_bytes_received"] += bytes_to_read

            flags = (buf["bid"] << self.IORING_CQE_BUFFER_SHIFT) | self.IORING_CQE_F_BUFFER
            multishot_active = sqe["multishot"]

            if multishot_active:
                flags |= self.IORING_CQE_F_MORE

            cqe = {
                "sqe_id": sqe["sqe_id"],
                "fd": fd,
                "res": bytes_to_read,
                "flags": flags,
                "bid": buf["bid"],
                "buf_addr": buf["addr"],
                "bytes_read": bytes_to_read,
                "truncated": truncated,
                "truncated_bytes": truncated_bytes,
                "multishot_active": multishot_active,
                "status": "SUCCESS"
            }
            self.cqe_log.append(cqe)
            generated_cqes.append(cqe)
            self.stats["total_cqes"] += 1

            if not multishot_active:
                del self.active_sqes[fd]
                break

        return generated_cqes

    def run(self, ops):
        results = []
        for idx, op in enumerate(ops):
            t = op["type"]
            if t == "REGISTER_PBUF_RING":
                self.register_pbuf_ring(
                    op["bgid"],
                    op["ring_entries"],
                    op.get("watermark", 1)
                )
                results.append({
                    "op_index": idx,
                    "type": t,
                    "bgid": op["bgid"],
                    "ring_entries": op["ring_entries"],
                    "status": "REGISTERED"
                })
            elif t in ("USER_ADD_BUFFERS", "RETURN_BUFFERS"):
                res = self.add_buffers(op["bgid"], op["buffers"])
                results.append({
                    "op_index": idx,
                    "type": t,
                    **res
                })
            elif t == "SUBMIT_RECV":
                res = self.submit_recv(
                    op["sqe_id"],
                    op["fd"],
                    op["bgid"],
                    op.get("multishot", False),
                    op.get("socket_type", "TCP")
                )
                results.append({
                    "op_index": idx,
                    "type": t,
                    **res
                })
            elif t == "CANCEL_RECV":
                res = self.cancel_recv(op["sqe_id"], op["fd"])
                results.append({
                    "op_index": idx,
                    "type": t,
                    **res
                })
            elif t == "RX_PACKET_ARRIVAL":
                res = self.rx_packet_arrival(
                    op["fd"],
                    op["payload_bytes"],
                    op.get("data_tag", "packet"),
                    op.get("eof", False),
                    op.get("socket_type", "TCP")
                )
                results.append({
                    "op_index": idx,
                    "type": t,
                    **res
                })
            elif t == "QUERY_RING_STATE":
                bgid = op["bgid"]
                ring = self.rings[bgid]
                avail = (ring["tail"] - ring["head"]) & 0xFFFF
                results.append({
                    "op_index": idx,
                    "type": t,
                    "bgid": bgid,
                    "head": ring["head"],
                    "tail": ring["tail"],
                    "available_buffers": avail,
                    "capacity": ring["capacity"],
                    "low_buffer_warning": avail < ring["watermark"]
                })
        
        rings_summary = {}
        for bgid, ring in self.rings.items():
            avail = (ring["tail"] - ring["head"]) & 0xFFFF
            rings_summary[str(bgid)] = {
                "head": ring["head"],
                "tail": ring["tail"],
                "available_buffers": avail,
                "capacity": ring["capacity"],
                "low_buffer_warning": avail < ring["watermark"]
            }

        return {
            "operation_results": results,
            "cqe_log": self.cqe_log,
            "summary": {
                "total_operations": len(ops),
                "rings": rings_summary,
                "active_sqes": list(self.active_sqes.keys()),
                "stats": self.stats
            }
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    engine = IoUringPbufRingEngine(data.get("config", {}))
    output = engine.run(data.get("operations", []))
    print(json.dumps(output, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
