import sys

class Message:
    def __init__(self, msg_id, processing_time_ms, offset):
        self.msg_id = msg_id
        self.processing_time_ms = int(processing_time_ms)
        self.offset = int(offset)

class Partition:
    def __init__(self, partition_id):
        self.partition_id = partition_id
        self.messages = []          # list of Message
        self.committed_offset = 0   # next uncommitted offset

class Topic:
    def __init__(self, name, num_partitions):
        self.name = name
        self.num_partitions = num_partitions
        self.partitions = [Partition(i) for i in range(num_partitions)]

class ConsumerMember:
    def __init__(self, consumer_id, max_poll_interval_ms, max_poll_records):
        self.consumer_id = consumer_id
        self.max_poll_interval_ms = int(max_poll_interval_ms)
        self.max_poll_records = int(max_poll_records)
        self.status = "ACTIVE"      # ACTIVE, EVICTED, LEFT
        self.generation_id = 0
        self.assigned_partitions = []

class KafkaGroupCoordinator:
    def __init__(self):
        self.topic = None
        self.members = {}           # consumer_id -> ConsumerMember
        self.generation_id = 0
        self.rebalance_count = 0

    def config_topic(self, name, num_partitions):
        self.topic = Topic(name, int(num_partitions))
        self.members = {}
        self.generation_id = 0
        self.rebalance_count = 0
        return f"CONFIG_TOPIC_OK topic={name} partitions={num_partitions}"

    def _rebalance(self):
        self.generation_id += 1
        self.rebalance_count += 1
        active_members = sorted(
            [m for m in self.members.values() if m.status == "ACTIVE"],
            key=lambda m: m.consumer_id
        )
        for m in active_members:
            m.assigned_partitions = []
            m.generation_id = self.generation_id

        if active_members and self.topic:
            for p in range(self.topic.num_partitions):
                owner = active_members[p % len(active_members)]
                owner.assigned_partitions.append(p)

    def join_group(self, consumer_id, max_poll_interval_ms, max_poll_records):
        if consumer_id in self.members and self.members[consumer_id].status == "ACTIVE":
            return f"ERROR:ALREADY_MEMBER consumer={consumer_id}"

        member = ConsumerMember(consumer_id, max_poll_interval_ms, max_poll_records)
        self.members[consumer_id] = member
        self._rebalance()

        p_list = ", ".join(str(p) for p in member.assigned_partitions)
        logs = [
            f"REBALANCE_TRIGGERED generation={self.generation_id} reason=CONSUMER_JOIN member={consumer_id}",
            f"JOIN_OK consumer={consumer_id} generation={self.generation_id} partitions=[{p_list}]"
        ]
        return "\n".join(logs)

    def leave_group(self, consumer_id):
        if consumer_id not in self.members or self.members[consumer_id].status != "ACTIVE":
            return f"ERROR:NOT_MEMBER consumer={consumer_id}"

        member = self.members[consumer_id]
        member.status = "LEFT"
        member.assigned_partitions = []
        self._rebalance()

        logs = [
            f"LEAVE_OK consumer={consumer_id}",
            f"REBALANCE_TRIGGERED generation={self.generation_id} reason=CONSUMER_LEAVE member={consumer_id}"
        ]
        return "\n".join(logs)

    def tune_consumer(self, consumer_id, max_poll_interval_ms, max_poll_records):
        if consumer_id not in self.members or self.members[consumer_id].status != "ACTIVE":
            return f"ERROR:NOT_MEMBER consumer={consumer_id}"

        member = self.members[consumer_id]
        member.max_poll_interval_ms = int(max_poll_interval_ms)
        member.max_poll_records = int(max_poll_records)
        return f"TUNE_OK consumer={consumer_id} max_poll_interval={max_poll_interval_ms} max_poll_records={max_poll_records}"

    def produce(self, topic_name, partition_id, msg_id, processing_time_ms):
        if not self.topic or self.topic.name != topic_name:
            return f"ERROR:UNKNOWN_TOPIC topic={topic_name}"
        p_id = int(partition_id)
        if p_id < 0 or p_id >= self.topic.num_partitions:
            return f"ERROR:INVALID_PARTITION partition={p_id}"

        part = self.topic.partitions[p_id]
        offset = len(part.messages)
        part.messages.append(Message(msg_id, processing_time_ms, offset))
        return f"PRODUCE_OK topic={topic_name} partition={p_id} msg={msg_id} offset={offset}"

    def poll(self, consumer_id):
        if consumer_id not in self.members or self.members[consumer_id].status != "ACTIVE":
            return f"ERROR:NOT_MEMBER consumer={consumer_id}"

        member = self.members[consumer_id]
        if not self.topic or not member.assigned_partitions:
            return f"POLL_OK consumer={consumer_id} processed_records=0 duration=0ms committed_offsets={{}}"

        # Gather uncommitted records up to max_poll_records across assigned partitions
        records = []
        new_offsets = {}  # partition_id -> new committed_offset candidate

        quota = member.max_poll_records
        for p_id in sorted(member.assigned_partitions):
            if quota <= 0:
                break
            part = self.topic.partitions[p_id]
            uncommitted = part.messages[part.committed_offset:]
            take = uncommitted[:quota]
            for m in take:
                records.append((p_id, m))
            if take:
                new_offsets[p_id] = part.committed_offset + len(take)
                quota -= len(take)

        if not records:
            return f"POLL_OK consumer={consumer_id} processed_records=0 duration=0ms committed_offsets={{}}"

        total_duration = sum(m.processing_time_ms for _, m in records)

        # Check timeout: max_poll_interval_ms exceeded!
        if total_duration > member.max_poll_interval_ms:
            member.status = "EVICTED"
            member.assigned_partitions = []
            self._rebalance()
            logs = [
                f"TIMEOUT_EVICTED consumer={consumer_id} duration={total_duration}ms limit={member.max_poll_interval_ms}ms",
                f"REBALANCE_TRIGGERED generation={self.generation_id} reason=CONSUMER_TIMEOUT evicted={consumer_id}"
            ]
            return "\n".join(logs)

        # Successfully processed within deadline: commit offsets
        for p_id, off in new_offsets.items():
            self.topic.partitions[p_id].committed_offset = off

        # Format committed_offsets
        items = [f"{p}:{off}" for p, off in sorted(new_offsets.items())]
        offsets_repr = "{" + ", ".join(items) + "}"
        return f"POLL_OK consumer={consumer_id} processed_records={len(records)} duration={total_duration}ms committed_offsets={offsets_repr}"

    def commit(self, consumer_id):
        if consumer_id not in self.members or self.members[consumer_id].status != "ACTIVE":
            return f"ERROR:COMMIT_FAILED consumer={consumer_id} reason=REBALANCED_OR_EVICTED generation={self.generation_id}"

        member = self.members[consumer_id]
        if member.generation_id != self.generation_id:
            return f"ERROR:COMMIT_FAILED consumer={consumer_id} reason=REBALANCED_OR_EVICTED generation={self.generation_id}"

        return f"COMMIT_OK consumer={consumer_id} generation={self.generation_id}"

    def stats(self):
        active_list = sorted([m.consumer_id for m in self.members.values() if m.status == "ACTIVE"])
        evicted_list = sorted([m.consumer_id for m in self.members.values() if m.status == "EVICTED"])
        lags = []
        if self.topic:
            for p in self.topic.partitions:
                lag = len(p.messages) - p.committed_offset
                lags.append(str(lag))
        active_repr = ", ".join(active_list)
        evicted_repr = ", ".join(evicted_list)
        lags_repr = ", ".join(lags)
        return f"STATS generation={self.generation_id} rebalances={self.rebalance_count} active_members=[{active_repr}] evicted_members=[{evicted_repr}] lag=[{lags_repr}]"

def main():
    coordinator = KafkaGroupCoordinator()
    lines = sys.stdin.read().splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        cmd = parts[0].upper()

        if cmd == "CONFIG_TOPIC":
            topic_name = parts[1]
            num_parts = parts[2]
            print(coordinator.config_topic(topic_name, num_parts))
        elif cmd == "JOIN_GROUP":
            consumer_id = parts[1]
            max_poll_interval = parts[2]
            max_poll_records = parts[3]
            print(coordinator.join_group(consumer_id, max_poll_interval, max_poll_records))
        elif cmd == "LEAVE_GROUP":
            consumer_id = parts[1]
            print(coordinator.leave_group(consumer_id))
        elif cmd == "TUNE_CONSUMER":
            consumer_id = parts[1]
            max_poll_interval = parts[2]
            max_poll_records = parts[3]
            print(coordinator.tune_consumer(consumer_id, max_poll_interval, max_poll_records))
        elif cmd == "PRODUCE":
            topic_name = parts[1]
            p_id = parts[2]
            msg_id = parts[3]
            proc_time = parts[4]
            print(coordinator.produce(topic_name, p_id, msg_id, proc_time))
        elif cmd == "POLL":
            consumer_id = parts[1]
            print(coordinator.poll(consumer_id))
        elif cmd == "COMMIT":
            consumer_id = parts[1]
            print(coordinator.commit(consumer_id))
        elif cmd == "STATS":
            print(coordinator.stats())

if __name__ == '__main__':
    main()
