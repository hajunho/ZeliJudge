import sys

class Client:
    def __init__(self, client_id):
        self.client_id = client_id
        self.buffer = [] # list of (msg_id, msg, size_kb)
        self.current_buffer_kb = 0
        self.is_evicted = False

class StreamMsg:
    def __init__(self, msg_id, payload, timestamp_ms):
        self.msg_id = msg_id
        self.payload = payload
        self.timestamp_ms = timestamp_ms

class PelEntry:
    def __init__(self, msg_id, consumer, delivery_time_ms, delivery_count=1):
        self.msg_id = msg_id
        self.consumer = consumer
        self.delivery_time_ms = delivery_time_ms
        self.delivery_count = delivery_count

class ConsumerGroup:
    def __init__(self, name):
        self.name = name
        self.last_delivered_idx = 0
        self.pel = {} # msg_id -> PelEntry

class RedisSimulator:
    def __init__(self):
        self.reset()

    def reset(self):
        self.mode = "PUBSUB"
        self.buffer_limit_kb = 32
        self.ack_timeout_ms = 1000

        # PubSub state
        self.channels = {} # channel -> set of client_id
        self.clients = {} # client_id -> Client
        self.pubsub_delivered = 0
        self.pubsub_lost = 0
        self.pubsub_evictions = 0
        self.msg_seq = 0

        # Streams state
        self.streams = {} # stream -> list of StreamMsg
        self.stream_seqs = {} # (stream, ts) -> seq
        self.consumer_groups = {} # stream -> dict of name -> ConsumerGroup
        self.streams_total = 0
        self.streams_acked = 0
        self.streams_claimed = 0

    def config(self, mode=None, buffer_limit_kb=None, ack_timeout_ms=None):
        if mode:
            self.mode = mode
        if buffer_limit_kb is not None:
            self.buffer_limit_kb = int(buffer_limit_kb)
        if ack_timeout_ms is not None:
            self.ack_timeout_ms = int(ack_timeout_ms)
        return f"OK mode={self.mode} buffer_limit_kb={self.buffer_limit_kb} ack_timeout_ms={self.ack_timeout_ms}"

    # PubSub methods
    def subscribe(self, client_id, channel):
        if client_id not in self.clients:
            self.clients[client_id] = Client(client_id)
        client = self.clients[client_id]
        if client.is_evicted:
            # Re-connect
            client.is_evicted = False
            client.buffer.clear()
            client.current_buffer_kb = 0

        if channel not in self.channels:
            self.channels[channel] = set()
        self.channels[channel].add(client_id)
        return f"SUBSCRIBED client={client_id} channel={channel}"

    def unsubscribe(self, client_id, channel):
        if channel in self.channels:
            self.channels[channel].discard(client_id)
        return f"UNSUBSCRIBED client={client_id} channel={channel}"

    def publish(self, channel, msg, size_kb=1):
        size_kb = int(size_kb)
        self.msg_seq += 1
        msg_id = f"msg_{self.msg_seq}"

        subscribers = sorted(list(self.channels.get(channel, set())))
        if not subscribers:
            self.pubsub_lost += 1
            return [f"PUBLISHED channel={channel} subscribers=0 delivered=0 lost=1"]

        outputs = []
        delivered_count = 0
        evicted_count = 0

        for cid in subscribers:
            client = self.clients[cid]
            if client.is_evicted:
                continue

            if client.current_buffer_kb + size_kb > self.buffer_limit_kb:
                # Buffer limit exceeded -> Evict client!
                client.is_evicted = True
                self.channels[channel].discard(cid)
                self.pubsub_evictions += 1
                evicted_count += 1
                outputs.append(f"CLIENT_EVICTED client={cid} error=CLIENT_OUTPUT_BUFFER_LIMIT_EXCEEDED current_buffer_kb={client.current_buffer_kb + size_kb} limit_kb={self.buffer_limit_kb}")
            else:
                client.buffer.append((msg_id, msg, size_kb))
                client.current_buffer_kb += size_kb
                delivered_count += 1
                self.pubsub_delivered += 1

        outputs.append(f"PUBLISHED channel={channel} subscribers={len(subscribers)} delivered={delivered_count} evicted={evicted_count}")
        return outputs

    def consume(self, client_id, count):
        count = int(count)
        if client_id not in self.clients:
            return f"CONSUMED client={client_id} count=0 remaining_buffer_kb=0"
        client = self.clients[client_id]
        if client.is_evicted:
            return f"CLIENT_ERROR client={client_id} error=CLIENT_ALREADY_EVICTED"

        actual_consumed = min(count, len(client.buffer))
        consumed_items = client.buffer[:actual_consumed]
        client.buffer = client.buffer[actual_consumed:]
        consumed_kb = sum(item[2] for item in consumed_items)
        client.current_buffer_kb = max(0, client.current_buffer_kb - consumed_kb)

        return f"CONSUMED client={client_id} count={actual_consumed} remaining_buffer_kb={client.current_buffer_kb}"

    # Streams methods
    def xadd(self, stream, msg, timestamp_ms=0):
        ts = int(timestamp_ms)
        key = (stream, ts)
        seq = self.stream_seqs.get(key, 0)
        self.stream_seqs[key] = seq + 1

        msg_id = f"{ts}-{seq}"
        if stream not in self.streams:
            self.streams[stream] = []
        self.streams[stream].append(StreamMsg(msg_id, msg, ts))
        self.streams_total += 1
        return f"XADD_OK stream={stream} id={msg_id} msg={msg}"

    def xgroup_create(self, stream, group):
        if stream not in self.consumer_groups:
            self.consumer_groups[stream] = {}
        if group not in self.consumer_groups[stream]:
            self.consumer_groups[stream][group] = ConsumerGroup(group)
        return f"XGROUP_CREATED stream={stream} group={group}"

    def xreadgroup(self, stream, group, consumer, count, timestamp_ms=0):
        count = int(count)
        now_ms = int(timestamp_ms)

        if stream not in self.streams or stream not in self.consumer_groups or group not in self.consumer_groups[stream]:
            return f"XREADGROUP_OK group={group} consumer={consumer} count=0 ids=[]"

        cgroup = self.consumer_groups[stream][group]
        msgs = self.streams[stream]

        start_idx = cgroup.last_delivered_idx
        end_idx = min(start_idx + count, len(msgs))

        read_msgs = msgs[start_idx:end_idx]
        cgroup.last_delivered_idx = end_idx

        read_ids = []
        for m in read_msgs:
            cgroup.pel[m.msg_id] = PelEntry(m.msg_id, consumer, now_ms, 1)
            read_ids.append(m.msg_id)

        ids_str = f"[{','.join(read_ids)}]"
        return f"XREADGROUP_OK group={group} consumer={consumer} count={len(read_ids)} ids={ids_str}"

    def xack(self, stream, group, msg_id):
        if stream in self.consumer_groups and group in self.consumer_groups[stream]:
            cgroup = self.consumer_groups[stream][group]
            if msg_id in cgroup.pel:
                del cgroup.pel[msg_id]
                self.streams_acked += 1
                return f"XACK_OK group={group} id={msg_id}"
        return f"XACK_IGNORED group={group} id={msg_id}"

    def xpending(self, stream, group):
        if stream not in self.consumer_groups or group not in self.consumer_groups[stream]:
            return f"XPENDING_OK group={group} pending_count=0 consumers={{}}"

        cgroup = self.consumer_groups[stream][group]
        consumer_counts = {}
        for pel in cgroup.pel.values():
            consumer_counts[pel.consumer] = consumer_counts.get(pel.consumer, 0) + 1

        parts = [f"{c}:{consumer_counts[c]}" for c in sorted(consumer_counts.keys())]
        cons_str = f"{{{','.join(parts)}}}"
        return f"XPENDING_OK group={group} pending_count={len(cgroup.pel)} consumers={cons_str}"

    def xclaim(self, stream, group, new_consumer, min_idle_ms, timestamp_ms=0):
        min_idle = int(min_idle_ms)
        now_ms = int(timestamp_ms)

        if stream not in self.consumer_groups or group not in self.consumer_groups[stream]:
            return f"XCLAIM_OK group={group} new_consumer={new_consumer} claimed_count=0 ids=[]"

        cgroup = self.consumer_groups[stream][group]
        claimed_ids = []

        for msg_id in sorted(cgroup.pel.keys()):
            entry = cgroup.pel[msg_id]
            idle_time = now_ms - entry.delivery_time_ms
            if idle_time >= min_idle:
                entry.consumer = new_consumer
                entry.delivery_time_ms = now_ms
                entry.delivery_count += 1
                claimed_ids.append(msg_id)
                self.streams_claimed += 1

        ids_str = f"[{','.join(claimed_ids)}]"
        return f"XCLAIM_OK group={group} new_consumer={new_consumer} claimed_count={len(claimed_ids)} ids={ids_str}"

    def stats(self):
        if self.mode == "PUBSUB":
            return f"STATS mode=PUBSUB delivered={self.pubsub_delivered} lost={self.pubsub_lost} evictions={self.pubsub_evictions}"
        else:
            total_pending = 0
            for grps in self.consumer_groups.values():
                for g in grps.values():
                    total_pending += len(g.pel)
            return f"STATS mode=STREAMS total_messages={self.streams_total} acked={self.streams_acked} pending={total_pending} claimed={self.streams_claimed}"

def main():
    sim = RedisSimulator()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        parts = line.split()
        cmd = parts[0]
        params = {}
        for p in parts[1:]:
            if '=' in p:
                k, v = p.split('=', 1)
                params[k] = v

        if cmd == "CONFIG":
            print(sim.config(
                mode=params.get('mode'),
                buffer_limit_kb=params.get('buffer_limit_kb'),
                ack_timeout_ms=params.get('ack_timeout_ms')
            ))

        elif cmd == "SUBSCRIBE":
            print(sim.subscribe(
                client_id=params.get('client'),
                channel=params.get('channel')
            ))

        elif cmd == "UNSUBSCRIBE":
            print(sim.unsubscribe(
                client_id=params.get('client'),
                channel=params.get('channel')
            ))

        elif cmd == "PUBLISH":
            lines = sim.publish(
                channel=params.get('channel'),
                msg=params.get('msg', ''),
                size_kb=params.get('size_kb', 1)
            )
            for out_line in lines:
                print(out_line)

        elif cmd == "CONSUME":
            print(sim.consume(
                client_id=params.get('client'),
                count=params.get('count', 1)
            ))

        elif cmd == "XADD":
            print(sim.xadd(
                stream=params.get('stream'),
                msg=params.get('msg', ''),
                timestamp_ms=params.get('now', 0)
            ))

        elif cmd == "XGROUP_CREATE":
            print(sim.xgroup_create(
                stream=params.get('stream'),
                group=params.get('group')
            ))

        elif cmd == "XREADGROUP":
            print(sim.xreadgroup(
                stream=params.get('stream'),
                group=params.get('group'),
                consumer=params.get('consumer'),
                count=params.get('count', 1),
                timestamp_ms=params.get('now', 0)
            ))

        elif cmd == "XACK":
            print(sim.xack(
                stream=params.get('stream'),
                group=params.get('group'),
                msg_id=params.get('id')
            ))

        elif cmd == "XPENDING":
            print(sim.xpending(
                stream=params.get('stream'),
                group=params.get('group')
            ))

        elif cmd == "XCLAIM":
            print(sim.xclaim(
                stream=params.get('stream'),
                group=params.get('group'),
                new_consumer=params.get('new_consumer'),
                min_idle_ms=params.get('min_idle_ms', 1000),
                timestamp_ms=params.get('now', 0)
            ))

        elif cmd == "STATS":
            print(sim.stats())

        elif cmd == "RESET":
            sim.reset()
            print("OK mode=PUBSUB buffer_limit_kb=32 ack_timeout_ms=1000")

if __name__ == '__main__':
    main()
