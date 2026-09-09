import sys

class ClientChannel:
    def __init__(self, client_id):
        self.client_id = client_id
        self.state = "CONNECTED"
        self.is_writable = True
        self.queue = []  # list of {"msg_id": str, "size": int, "key": str or None}
        self.buffer_bytes = 0
        self.delivered_msgs = 0
        self.dropped_msgs = 0
        self.conflated_msgs = 0


class WebSocketBackpressureServer:
    def __init__(self):
        self.reset()

    def reset(self):
        self.high_watermark = 65536   # 64 KB
        self.low_watermark = 32768    # 32 KB
        self.max_capacity = 131072    # 128 KB
        self.policy = "DISCONNECT"    # DISCONNECT | CONFLATE | DROP_OLDEST | DROP_LATEST
        self.clients = {}             # client_id -> ClientChannel

    def config(self, high, low, max_cap, policy):
        self.high_watermark = int(high)
        self.low_watermark = int(low)
        self.max_capacity = int(max_cap)
        self.policy = policy.upper()
        return f"CONFIG_OK high_watermark={self.high_watermark} low_watermark={self.low_watermark} max_capacity={self.max_capacity} policy={self.policy}"

    def connect(self, client_id):
        if client_id in self.clients:
            c = self.clients[client_id]
            c.state = "CONNECTED"
            c.is_writable = True
            c.queue.clear()
            c.buffer_bytes = 0
        else:
            self.clients[client_id] = ClientChannel(client_id)
        return f"CONNECT_OK client_id={client_id}"

    def disconnect(self, client_id):
        if client_id in self.clients:
            c = self.clients[client_id]
            c.state = "DISCONNECTED"
            c.is_writable = False
            return f"DISCONNECT_OK client_id={client_id}"
        return f"DISCONNECT_FAIL client_id={client_id} reason=NOT_FOUND"

    def send(self, client_id, msg_id, size, key=None):
        if client_id not in self.clients:
            return f"SEND_FAIL client_id={client_id} reason=NOT_CONNECTED", "FAIL"
        c = self.clients[client_id]
        if c.state != "CONNECTED":
            return f"SEND_FAIL client_id={client_id} reason=NOT_CONNECTED", "FAIL"

        size = int(size)

        # 1. Check CONFLATE policy
        if self.policy == "CONFLATE" and key is not None:
            found_idx = -1
            for i, m in enumerate(c.queue):
                if m.get("key") == key:
                    found_idx = i
                    break
            if found_idx != -1:
                old_m = c.queue[found_idx]
                delta = size - old_m["size"]
                if c.buffer_bytes + delta <= self.max_capacity:
                    c.buffer_bytes += delta
                    old_m["msg_id"] = msg_id
                    old_m["size"] = size
                    c.conflated_msgs += 1
                    if c.buffer_bytes > self.high_watermark:
                        c.is_writable = False
                    return f"SEND_CONFLATED client_id={client_id} msg_id={msg_id} key={key} buffer_bytes={c.buffer_bytes}", "CONFLATED"

        # 2. Check Capacity & Overflow
        if c.buffer_bytes + size > self.max_capacity:
            if self.policy == "DISCONNECT":
                c.state = "DISCONNECTED"
                c.is_writable = False
                c.queue.clear()
                c.buffer_bytes = 0
                return f"CLIENT_EVICTED client_id={client_id} reason=BUFFER_OVERFLOW", "EVICTED"
            elif self.policy == "DROP_LATEST":
                c.dropped_msgs += 1
                return f"SEND_DROPPED client_id={client_id} msg_id={msg_id} reason=POLICY_DROP", "DROPPED"
            elif self.policy == "DROP_OLDEST" or self.policy == "CONFLATE":
                while c.queue and (c.buffer_bytes + size > self.max_capacity):
                    old = c.queue.pop(0)
                    c.buffer_bytes -= old["size"]
                    c.dropped_msgs += 1
                if c.buffer_bytes + size > self.max_capacity:
                    c.dropped_msgs += 1
                    return f"SEND_DROPPED client_id={client_id} msg_id={msg_id} reason=POLICY_DROP", "DROPPED"
                else:
                    c.queue.append({"msg_id": msg_id, "size": size, "key": key})
                    c.buffer_bytes += size
                    if c.buffer_bytes > self.high_watermark:
                        c.is_writable = False
                    w_str = "true" if c.is_writable else "false"
                    return f"SEND_OK client_id={client_id} msg_id={msg_id} buffer_bytes={c.buffer_bytes} writable={w_str}", "OK"
        else:
            c.queue.append({"msg_id": msg_id, "size": size, "key": key})
            c.buffer_bytes += size
            if c.buffer_bytes > self.high_watermark:
                c.is_writable = False
            w_str = "true" if c.is_writable else "false"
            return f"SEND_OK client_id={client_id} msg_id={msg_id} buffer_bytes={c.buffer_bytes} writable={w_str}", "OK"

    def broadcast(self, msg_id, size, key=None):
        sent_count = 0
        dropped_count = 0
        conflated_count = 0
        evicted_count = 0

        # Sort clients alphabetically for deterministic broadcast order
        active_ids = sorted([cid for cid, c in self.clients.items() if c.state == "CONNECTED"])
        for cid in active_ids:
            res_str, status = self.send(cid, msg_id, size, key)
            if status == "OK":
                sent_count += 1
            elif status == "DROPPED":
                dropped_count += 1
            elif status == "CONFLATED":
                conflated_count += 1
            elif status == "EVICTED":
                evicted_count += 1

        return f"BROADCAST_OK msg_id={msg_id} sent={sent_count} dropped={dropped_count} conflated={conflated_count} evicted={evicted_count}"

    def drain(self, client_id, bytes_to_drain):
        if client_id not in self.clients or self.clients[client_id].state != "CONNECTED":
            return f"DRAIN_FAIL client_id={client_id} reason=NOT_CONNECTED"

        c = self.clients[client_id]
        budget = int(bytes_to_drain)
        drained_bytes = 0
        delivered_count = 0

        while budget > 0 and c.queue:
            front = c.queue[0]
            if front["size"] <= budget:
                drained_bytes += front["size"]
                budget -= front["size"]
                c.buffer_bytes -= front["size"]
                c.queue.pop(0)
                c.delivered_msgs += 1
                delivered_count += 1
            else:
                drained_bytes += budget
                front["size"] -= budget
                c.buffer_bytes -= budget
                budget = 0

        if c.buffer_bytes < self.low_watermark and not c.is_writable:
            c.is_writable = True

        w_str = "true" if c.is_writable else "false"
        return f"DRAIN_OK client_id={client_id} drained_bytes={drained_bytes} remaining_bytes={c.buffer_bytes} delivered={delivered_count} writable={w_str}"

    def status(self, client_id):
        if client_id not in self.clients:
            return f"STATUS_FAIL client_id={client_id} reason=NOT_FOUND"

        c = self.clients[client_id]
        w_str = "true" if c.is_writable else "false"
        lines = [
            f"--- CLIENT_STATUS {client_id} ---",
            f"STATE: {c.state}",
            f"WRITABLE: {w_str}",
            f"BUFFER_BYTES: {c.buffer_bytes}",
            f"QUEUED_MSGS: {len(c.queue)}",
            f"DELIVERED_MSGS: {c.delivered_msgs}",
            f"DROPPED_MSGS: {c.dropped_msgs}",
            f"CONFLATED_MSGS: {c.conflated_msgs}",
            "--- END_STATUS ---"
        ]
        return "\n".join(lines)


def parse_tokens(tokens):
    kv = {}
    pos = []
    for t in tokens:
        if "=" in t:
            k, v = t.split("=", 1)
            kv[k.strip().lower()] = v.strip()
        else:
            pos.append(t.strip())
    return kv, pos


def main():
    server = WebSocketBackpressureServer()
    for line in sys.stdin:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split()
        cmd = parts[0].upper()
        kv, pos = parse_tokens(parts[1:])

        if cmd == "CONFIG":
            high = kv.get("high_watermark", pos[0] if len(pos) > 0 else 65536)
            low = kv.get("low_watermark", pos[1] if len(pos) > 1 else 32768)
            max_cap = kv.get("max_capacity", pos[2] if len(pos) > 2 else 131072)
            policy = kv.get("policy", pos[3] if len(pos) > 3 else "DISCONNECT")
            print(server.config(high, low, max_cap, policy))
        elif cmd == "CONNECT":
            cid = kv.get("client_id", pos[0] if len(pos) > 0 else "")
            print(server.connect(cid))
        elif cmd == "DISCONNECT":
            cid = kv.get("client_id", pos[0] if len(pos) > 0 else "")
            print(server.disconnect(cid))
        elif cmd == "SEND":
            cid = kv.get("client_id", pos[0] if len(pos) > 0 else "")
            mid = kv.get("msg_id", pos[1] if len(pos) > 1 else "")
            size = int(kv.get("size", pos[2] if len(pos) > 2 else 100))
            key = kv.get("key", pos[3] if len(pos) > 3 else None)
            res, _ = server.send(cid, mid, size, key)
            print(res)
        elif cmd == "BROADCAST":
            mid = kv.get("msg_id", pos[0] if len(pos) > 0 else "")
            size = int(kv.get("size", pos[1] if len(pos) > 1 else 100))
            key = kv.get("key", pos[2] if len(pos) > 2 else None)
            print(server.broadcast(mid, size, key))
        elif cmd == "DRAIN":
            cid = kv.get("client_id", pos[0] if len(pos) > 0 else "")
            b = int(kv.get("bytes", pos[1] if len(pos) > 1 else 1024))
            print(server.drain(cid, b))
        elif cmd == "STATUS":
            cid = kv.get("client_id", pos[0] if len(pos) > 0 else "")
            print(server.status(cid))
        elif cmd == "RESET":
            server.reset()
            print("RESET_OK")


if __name__ == "__main__":
    main()
