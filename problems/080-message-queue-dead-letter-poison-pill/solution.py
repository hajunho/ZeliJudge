import sys
from collections import deque

class Message:
    def __init__(self, msg_id: str, msg_type: str, payload: str):
        self.msg_id = msg_id
        self.msg_type = msg_type  # "NORMAL" or "POISON"
        self.payload = payload
        self.retries = 0

class NaiveEngine:
    def __init__(self):
        self.queue = deque()
        self.processed = 0
        self.failed_attempts = 0

    def enqueue(self, msg: Message):
        self.queue.append(msg)

    def consume_one(self):
        if not self.queue:
            return
        msg = self.queue[0]
        if msg.msg_type == "NORMAL":
            self.queue.popleft()
            self.processed += 1
        else:
            # POISON message: transaction rollback, cannot commit offset
            self.failed_attempts += 1

    def is_hol_blocked(self) -> bool:
        return len(self.queue) > 0 and self.queue[0].msg_type == "POISON"

class DLQEngine:
    def __init__(self, max_retries: int):
        self.max_retries = max_retries
        self.queue = deque()
        self.dlq = []
        self.processed = 0
        self.failed_attempts = 0

    def enqueue(self, msg: Message):
        self.queue.append(msg)

    def consume_one(self):
        if not self.queue:
            return
        msg = self.queue[0]
        if msg.msg_type == "NORMAL":
            self.queue.popleft()
            self.processed += 1
        else:
            # POISON message
            self.failed_attempts += 1
            msg.retries += 1
            if msg.retries >= self.max_retries:
                # Quarantined to DLQ, commit offset so queue can advance
                self.queue.popleft()
                self.dlq.append(msg)

    def redrive(self) -> int:
        count = len(self.dlq)
        for msg in self.dlq:
            msg.msg_type = "NORMAL"
            msg.retries = 0
            self.queue.append(msg)
        self.dlq.clear()
        return count

    def is_hol_blocked(self) -> bool:
        return len(self.queue) > 0 and self.queue[0].msg_type == "POISON"

class QueueSimulator:
    def __init__(self, max_retries: int):
        self.max_retries = max_retries
        self.naive = NaiveEngine()
        self.dlq = DLQEngine(max_retries)

    def enqueue(self, msg_id: str, msg_type: str, payload: str):
        self.naive.enqueue(Message(msg_id, msg_type, payload))
        self.dlq.enqueue(Message(msg_id, msg_type, payload))

    def consume(self, count: int):
        for _ in range(count):
            self.naive.consume_one()
            self.dlq.consume_one()

    def redrive(self) -> int:
        return self.dlq.redrive()

    def get_status(self) -> str:
        lines = []
        lines.append("=== NAIVE ENGINE ===")
        lines.append(f"PROCESSED: {self.naive.processed}")
        lines.append(f"FAILED_ATTEMPTS: {self.naive.failed_attempts}")
        lines.append(f"MAIN_QUEUE_LAG: {len(self.naive.queue)}")
        lines.append("DLQ_SIZE: 0")
        lines.append(f"HOL_BLOCKED: {'TRUE' if self.naive.is_hol_blocked() else 'FALSE'}")

        lines.append("=== DLQ ENGINE ===")
        lines.append(f"PROCESSED: {self.dlq.processed}")
        lines.append(f"FAILED_ATTEMPTS: {self.dlq.failed_attempts}")
        lines.append(f"MAIN_QUEUE_LAG: {len(self.dlq.queue)}")
        lines.append(f"DLQ_SIZE: {len(self.dlq.dlq)}")
        lines.append(f"HOL_BLOCKED: {'TRUE' if self.dlq.is_hol_blocked() else 'FALSE'}")
        return "\n".join(lines)

def run():
    input_data = sys.stdin.read().splitlines()
    simulator = None
    output = []

    for line in input_data:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split()
        cmd = parts[0]

        if cmd == "INIT":
            max_r = int(parts[1])
            simulator = QueueSimulator(max_r)
            output.append(f"INITIALIZED MAX_RETRIES={max_r}")

        elif cmd == "ENQUEUE":
            msg_id = parts[1]
            msg_type = parts[2]
            payload = parts[3] if len(parts) > 3 else ""
            simulator.enqueue(msg_id, msg_type, payload)
            output.append(f"ENQUEUED {msg_id} TYPE={msg_type}")

        elif cmd == "CONSUME":
            cnt = int(parts[1])
            simulator.consume(cnt)
            output.append(f"CONSUMED {cnt} STEPS")

        elif cmd == "REDRIVE":
            redriven_cnt = simulator.redrive()
            output.append(f"REDRIVEN {redriven_cnt} MESSAGES FROM DLQ")

        elif cmd == "STATUS":
            output.append(simulator.get_status())

    print("\n".join(output))

if __name__ == "__main__":
    run()
