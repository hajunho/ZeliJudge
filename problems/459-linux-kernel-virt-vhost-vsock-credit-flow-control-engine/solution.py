import sys
import json

class VhostVsockEngine:
    def __init__(self, host_cid=2, default_buf_alloc=65536):
        self.host_cid = host_cid
        self.default_buf_alloc = default_buf_alloc
        self.sockets = {}
        self.stats = {
            "connections_established": 0,
            "data_packets_sent": 0,
            "bytes_sent": 0,
            "bytes_received": 0,
            "credit_updates": 0,
            "flow_control_blocks": 0
        }

    def _get_sock(self, cid, port):
        return self.sockets.get((cid, port))

    def listen(self, cid, port, buf_alloc=None):
        if (cid, port) in self.sockets:
            return {"status": "EADDRINUSE", "cid": cid, "port": port}
        alloc = buf_alloc if buf_alloc is not None else self.default_buf_alloc
        self.sockets[(cid, port)] = {
            "cid": cid,
            "port": port,
            "state": "LISTEN",
            "peer_cid": None,
            "peer_port": None,
            "rx_queue": [],
            "rx_bytes": 0,
            "buf_alloc": alloc,
            "fwd_cnt": 0,
            "tx_cnt": 0,
            "peer_buf_alloc": 0,
            "peer_fwd_cnt": 0
        }
        return {"status": "LISTENING", "cid": cid, "port": port, "buf_alloc": alloc}

    def connect(self, src_cid, src_port, dst_cid, dst_port, buf_alloc=None):
        if (src_cid, src_port) in self.sockets:
            return {"status": "EADDRINUSE", "cid": src_cid, "port": src_port}
        dst_sock = self._get_sock(dst_cid, dst_port)
        if not dst_sock or dst_sock["state"] != "LISTEN":
            return {"status": "ECONNREFUSED", "dst_cid": dst_cid, "dst_port": dst_port}

        src_alloc = buf_alloc if buf_alloc is not None else self.default_buf_alloc

        client_sock = {
            "cid": src_cid,
            "port": src_port,
            "state": "CONNECTED",
            "peer_cid": dst_cid,
            "peer_port": dst_port,
            "rx_queue": [],
            "rx_bytes": 0,
            "buf_alloc": src_alloc,
            "fwd_cnt": 0,
            "tx_cnt": 0,
            "peer_buf_alloc": dst_sock["buf_alloc"],
            "peer_fwd_cnt": dst_sock["fwd_cnt"]
        }
        self.sockets[(src_cid, src_port)] = client_sock

        dst_sock["state"] = "CONNECTED"
        dst_sock["peer_cid"] = src_cid
        dst_sock["peer_port"] = src_port
        dst_sock["peer_buf_alloc"] = src_alloc
        dst_sock["peer_fwd_cnt"] = 0

        self.stats["connections_established"] += 1
        return {
            "status": "CONNECTED",
            "src": f"{src_cid}:{src_port}",
            "dst": f"{dst_cid}:{dst_port}",
            "client_peer_buf": client_sock["peer_buf_alloc"],
            "server_peer_buf": dst_sock["peer_buf_alloc"]
        }

    def send_data(self, src_cid, src_port, data_len):
        sock = self._get_sock(src_cid, src_port)
        if not sock or sock["state"] != "CONNECTED":
            return {"status": "ENOTCONN", "src": f"{src_cid}:{src_port}"}

        peer_sock = self._get_sock(sock["peer_cid"], sock["peer_port"])
        if not peer_sock or peer_sock["state"] != "CONNECTED":
            return {"status": "ECONNRESET", "src": f"{src_cid}:{src_port}"}

        in_flight = sock["tx_cnt"] - sock["peer_fwd_cnt"]
        available_credits = sock["peer_buf_alloc"] - in_flight

        if available_credits < data_len:
            self.stats["flow_control_blocks"] += 1
            return {
                "status": "EAGAIN_CREDIT_EXHAUSTED",
                "available_credits": available_credits,
                "requested": data_len,
                "in_flight": in_flight,
                "peer_buf_alloc": sock["peer_buf_alloc"]
            }

        sock["tx_cnt"] += data_len
        peer_sock["rx_queue"].append(data_len)
        peer_sock["rx_bytes"] += data_len

        self.stats["data_packets_sent"] += 1
        self.stats["bytes_sent"] += data_len

        return {
            "status": "DATA_SENT",
            "bytes_sent": data_len,
            "tx_cnt": sock["tx_cnt"],
            "remaining_credits": sock["peer_buf_alloc"] - (sock["tx_cnt"] - sock["peer_fwd_cnt"]),
            "peer_rx_bytes": peer_sock["rx_bytes"]
        }

    def recv_data(self, cid, port, max_bytes=None):
        sock = self._get_sock(cid, port)
        if not sock or sock["state"] not in ["CONNECTED", "LISTEN"]:
            return {"status": "ENOTCONN", "cid": cid, "port": port}

        if not sock["rx_queue"]:
            return {"status": "EAGAIN_NO_DATA", "cid": cid, "port": port}

        bytes_to_read = max_bytes if max_bytes is not None else sock["rx_bytes"]
        actually_read = 0

        while sock["rx_queue"] and actually_read < bytes_to_read:
            pkt = sock["rx_queue"][0]
            if actually_read + pkt <= bytes_to_read:
                actually_read += pkt
                sock["rx_queue"].pop(0)
            else:
                needed = bytes_to_read - actually_read
                actually_read += needed
                sock["rx_queue"][0] = pkt - needed
                break

        sock["rx_bytes"] -= actually_read
        sock["fwd_cnt"] += actually_read
        self.stats["bytes_received"] += actually_read

        peer_sock = self._get_sock(sock["peer_cid"], sock["peer_port"]) if sock["peer_cid"] else None
        if peer_sock:
            peer_sock["peer_fwd_cnt"] = sock["fwd_cnt"]
            peer_sock["peer_buf_alloc"] = sock["buf_alloc"]
            self.stats["credit_updates"] += 1

        return {
            "status": "DATA_RECEIVED",
            "bytes_read": actually_read,
            "rx_remaining": sock["rx_bytes"],
            "fwd_cnt": sock["fwd_cnt"],
            "peer_credits_replenished": (peer_sock["peer_buf_alloc"] - (peer_sock["tx_cnt"] - peer_sock["peer_fwd_cnt"])) if peer_sock else 0
        }

    def close(self, cid, port):
        sock = self._get_sock(cid, port)
        if not sock:
            return {"status": "ENOTCONN", "cid": cid, "port": port}

        peer_sock = self._get_sock(sock["peer_cid"], sock["peer_port"]) if sock["peer_cid"] else None
        if peer_sock:
            peer_sock["state"] = "CLOSED"

        sock["state"] = "CLOSED"
        return {"status": "CONNECTION_CLOSED", "cid": cid, "port": port}

    def query_vsock_state(self):
        active = {}
        for (c, p), s in sorted(self.sockets.items()):
            active[f"{c}:{p}"] = {
                "state": s["state"],
                "peer": f"{s['peer_cid']}:{s['peer_port']}" if s["peer_cid"] else None,
                "rx_bytes": s["rx_bytes"],
                "fwd_cnt": s["fwd_cnt"],
                "tx_cnt": s["tx_cnt"],
                "buf_alloc": s["buf_alloc"],
                "peer_buf_alloc": s["peer_buf_alloc"]
            }
        return {
            "host_cid": self.host_cid,
            "sockets": active,
            "stats": self.stats
        }

def main():
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    raw = sys.stdin.read()
    if not raw.strip():
        return
    input_data = json.loads(raw)

    cfg = input_data.get("config", {})
    host_cid = cfg.get("host_cid", 2)
    default_buf = cfg.get("default_buf_alloc", 65536)

    engine = VhostVsockEngine(host_cid=host_cid, default_buf_alloc=default_buf)
    results = []

    for op in input_data.get("operations", []):
        cmd = op.get("op")
        if cmd == "LISTEN":
            res = engine.listen(op["cid"], op["port"], op.get("buf_alloc"))
            results.append(res)
        elif cmd == "CONNECT":
            res = engine.connect(op["src_cid"], op["src_port"], op["dst_cid"], op["dst_port"], op.get("buf_alloc"))
            results.append(res)
        elif cmd == "SEND_DATA":
            res = engine.send_data(op["src_cid"], op["src_port"], op["data_len"])
            results.append(res)
        elif cmd == "RECV_DATA":
            res = engine.recv_data(op["cid"], op["port"], op.get("max_bytes"))
            results.append(res)
        elif cmd == "CLOSE":
            res = engine.close(op["cid"], op["port"])
            results.append(res)
        elif cmd == "QUERY_VSOCK_STATE":
            res = engine.query_vsock_state()
            results.append(res)

    out = {"results": results}
    print(json.dumps(out, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
