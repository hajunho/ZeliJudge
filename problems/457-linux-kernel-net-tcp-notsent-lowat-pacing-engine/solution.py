import sys
import json

class TcpNotsentLowatEngine:
    def __init__(self, sndbuf_limit=131072, default_notsent_lowat=16384, mss=1460, initial_cwnd=10):
        self.sndbuf_limit = sndbuf_limit
        self.tcp_notsent_lowat = default_notsent_lowat
        self.mss = mss
        self.cwnd = initial_cwnd
        self.sk_write_queue = []
        self.total_queued_bytes = 0
        self.unsent_bytes = 0
        self.in_flight_bytes = 0
        self.pollout_ready = True
        self.stats = {
            "app_writes": 0,
            "packets_transmitted": 0,
            "bytes_transmitted": 0,
            "bytes_acked": 0,
            "epollout_wakeups": 0,
            "write_blocks": 0
        }

    def _eval_pollout(self):
        old_ready = self.pollout_ready
        self.pollout_ready = (self.unsent_bytes < self.tcp_notsent_lowat) and (self.total_queued_bytes < self.sndbuf_limit)
        if not old_ready and self.pollout_ready:
            self.stats["epollout_wakeups"] += 1
            return True
        return False

    def setsockopt_notsent_lowat(self, val):
        self.tcp_notsent_lowat = val
        woke = self._eval_pollout()
        return {
            "status": "OPT_UPDATED",
            "tcp_notsent_lowat": self.tcp_notsent_lowat,
            "pollout_ready": self.pollout_ready,
            "woken": woke
        }

    def set_cwnd(self, cwnd):
        self.cwnd = cwnd
        return {"status": "CWND_UPDATED", "cwnd": self.cwnd}

    def app_write(self, stream_id, prio, data_len):
        if self.total_queued_bytes + data_len > self.sndbuf_limit:
            self.stats["write_blocks"] += 1
            return {
                "status": "EAGAIN_SNDBUF_EXCEEDED",
                "stream_id": stream_id,
                "data_len": data_len,
                "current_queued": self.total_queued_bytes,
                "limit": self.sndbuf_limit
            }

        chunk = {
            "stream_id": stream_id,
            "prio": prio,
            "len": data_len,
            "sent": False
        }
        self.sk_write_queue.append(chunk)
        self.total_queued_bytes += data_len
        self.unsent_bytes += data_len
        self.stats["app_writes"] += 1

        self._eval_pollout()

        return {
            "status": "WRITE_QUEUED",
            "stream_id": stream_id,
            "data_len": data_len,
            "unsent_bytes": self.unsent_bytes,
            "total_queued": self.total_queued_bytes,
            "pollout_ready": self.pollout_ready
        }

    def tcp_pace_transmit(self):
        max_flight = self.cwnd * self.mss
        available_flight = max(0, max_flight - self.in_flight_bytes)
        send_budget = min(available_flight, self.unsent_bytes)

        if send_budget <= 0:
            return {
                "status": "NOTHING_TO_SEND",
                "reason": "CWND_LIMITED" if available_flight <= 0 else "NO_UNSENT_DATA",
                "in_flight": self.in_flight_bytes,
                "unsent": self.unsent_bytes
            }

        bytes_sent = 0
        packets_sent = 0

        for chunk in list(self.sk_write_queue):
            if not chunk["sent"]:
                chunk_len = chunk["len"]
                if bytes_sent + chunk_len <= send_budget:
                    chunk["sent"] = True
                    bytes_sent += chunk_len
                    packets_sent += (chunk_len + self.mss - 1) // self.mss
                else:
                    can_send = send_budget - bytes_sent
                    if can_send > 0:
                        rem_len = chunk_len - can_send
                        idx = self.sk_write_queue.index(chunk)
                        chunk["len"] = can_send
                        chunk["sent"] = True
                        bytes_sent += can_send
                        packets_sent += (can_send + self.mss - 1) // self.mss
                        self.sk_write_queue.insert(idx + 1, {
                            "stream_id": chunk["stream_id"],
                            "prio": chunk["prio"],
                            "len": rem_len,
                            "sent": False
                        })
                    break

        self.unsent_bytes -= bytes_sent
        self.in_flight_bytes += bytes_sent
        self.stats["bytes_transmitted"] += bytes_sent
        self.stats["packets_transmitted"] += packets_sent

        woke = self._eval_pollout()

        return {
            "status": "TRANSMITTED",
            "bytes_sent": bytes_sent,
            "packets_sent": packets_sent,
            "unsent_bytes": self.unsent_bytes,
            "in_flight_bytes": self.in_flight_bytes,
            "pollout_ready": self.pollout_ready,
            "woken": woke
        }

    def tcp_receive_ack(self, ack_bytes):
        to_ack = ack_bytes
        actually_acked = 0

        remaining_queue = []
        for chunk in self.sk_write_queue:
            if to_ack > 0 and chunk["sent"]:
                if chunk["len"] <= to_ack:
                    to_ack -= chunk["len"]
                    actually_acked += chunk["len"]
                else:
                    chunk["len"] -= to_ack
                    actually_acked += to_ack
                    to_ack = 0
                    remaining_queue.append(chunk)
            else:
                remaining_queue.append(chunk)

        self.sk_write_queue = remaining_queue
        self.in_flight_bytes -= actually_acked
        self.total_queued_bytes -= actually_acked
        self.stats["bytes_acked"] += actually_acked

        woke = self._eval_pollout()

        return {
            "status": "ACK_PROCESSED",
            "bytes_acked": actually_acked,
            "in_flight_bytes": self.in_flight_bytes,
            "total_queued": self.total_queued_bytes,
            "pollout_ready": self.pollout_ready,
            "woken": woke
        }

    def query_socket_state(self):
        return {
            "total_queued_bytes": self.total_queued_bytes,
            "unsent_bytes": self.unsent_bytes,
            "in_flight_bytes": self.in_flight_bytes,
            "pollout_ready": self.pollout_ready,
            "queue_chunks_count": len(self.sk_write_queue),
            "tcp_notsent_lowat": self.tcp_notsent_lowat,
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
    sndbuf = cfg.get("sndbuf_limit", 131072)
    lowat = cfg.get("default_notsent_lowat", 16384)
    mss = cfg.get("mss", 1460)
    cwnd = cfg.get("initial_cwnd", 10)

    engine = TcpNotsentLowatEngine(sndbuf_limit=sndbuf, default_notsent_lowat=lowat, mss=mss, initial_cwnd=cwnd)
    results = []

    for op in input_data.get("operations", []):
        cmd = op.get("op")
        if cmd == "APP_WRITE":
            res = engine.app_write(op["stream_id"], op.get("prio", 0), op["data_len"])
            results.append(res)
        elif cmd == "TCP_PACE_TRANSMIT":
            res = engine.tcp_pace_transmit()
            results.append(res)
        elif cmd == "TCP_RECEIVE_ACK":
            res = engine.tcp_receive_ack(op["ack_bytes"])
            results.append(res)
        elif cmd == "SETSOCKOPT_NOTSENT_LOWAT":
            res = engine.setsockopt_notsent_lowat(op["val"])
            results.append(res)
        elif cmd == "SET_CWND":
            res = engine.set_cwnd(op["cwnd"])
            results.append(res)
        elif cmd == "QUERY_SOCKET_STATE":
            res = engine.query_socket_state()
            results.append(res)

    out = {"results": results}
    print(json.dumps(out, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
