import sys

class KafkaRetrySimulator:
    def __init__(self):
        self.reset()

    def reset(self):
        self.mode = "NON_BLOCKING"   # NON_BLOCKING | BLOCKING
        self.retry1_delay = 5        # seconds
        self.retry2_delay = 30       # seconds
        self.current_time = 0

        # Queues
        self.main_queue = []
        self.retry1_queue = []
        self.retry2_queue = []
        self.dlt_queue = []

        # Blocking mode state
        self.current_inflight = None

        # Stats
        self.main_processed = 0
        self.total_success = 0

    def config(self, mode, retry1_delay, retry2_delay):
        self.mode = mode.upper()
        self.retry1_delay = int(retry1_delay)
        self.retry2_delay = int(retry2_delay)
        return f"CONFIG_OK mode={self.mode} retry1_delay={self.retry1_delay} retry2_delay={self.retry2_delay}"

    def produce(self, msg_id, fail_count):
        msg = {
            "id": msg_id,
            "fail_count": int(fail_count),
            "attempts": 0,
            "execute_at": 0,
            "next_attempt_time": 0
        }
        self.main_queue.append(msg)
        return f"PRODUCE_OK id={msg_id} fail_count={fail_count}"

    def tick(self, seconds):
        self.current_time += int(seconds)
        return f"TICK_OK time={self.current_time}"

    def process(self):
        if self.mode == "NON_BLOCKING":
            # 1. Process all available messages in main_queue
            curr_main = list(self.main_queue)
            self.main_queue.clear()

            for msg in curr_main:
                self.main_processed += 1
                if msg["fail_count"] == 0:
                    self.total_success += 1
                else:
                    msg["attempts"] += 1
                    msg["fail_count"] -= 1
                    msg["execute_at"] = self.current_time + self.retry1_delay
                    self.retry1_queue.append(msg)

            # 2. Process ready messages in retry1_queue
            new_r1 = []
            for msg in self.retry1_queue:
                if msg["execute_at"] <= self.current_time:
                    if msg["fail_count"] == 0:
                        self.total_success += 1
                    else:
                        msg["attempts"] += 1
                        msg["fail_count"] -= 1
                        msg["execute_at"] = self.current_time + self.retry2_delay
                        self.retry2_queue.append(msg)
                else:
                    new_r1.append(msg)
            self.retry1_queue = new_r1

            # 3. Process ready messages in retry2_queue
            new_r2 = []
            for msg in self.retry2_queue:
                if msg["execute_at"] <= self.current_time:
                    if msg["fail_count"] == 0:
                        self.total_success += 1
                    else:
                        msg["attempts"] += 1
                        self.dlt_queue.append(msg)
                else:
                    new_r2.append(msg)
            self.retry2_queue = new_r2

            return f"PROCESS_OK mode=NON_BLOCKING time={self.current_time}"

        else: # BLOCKING mode
            if self.current_inflight is None and self.main_queue:
                self.current_inflight = self.main_queue.pop(0)
                self.current_inflight["next_attempt_time"] = self.current_time

            while self.current_inflight is not None:
                if self.current_time < self.current_inflight["next_attempt_time"]:
                    # Blocked!
                    break

                # Ready to attempt
                if self.current_inflight["fail_count"] == 0:
                    self.total_success += 1
                    self.main_processed += 1
                    self.current_inflight = None
                    if self.main_queue:
                        self.current_inflight = self.main_queue.pop(0)
                        self.current_inflight["next_attempt_time"] = self.current_time
                else:
                    self.current_inflight["attempts"] += 1
                    self.current_inflight["fail_count"] -= 1

                    if self.current_inflight["attempts"] == 1:
                        self.current_inflight["next_attempt_time"] = self.current_time + self.retry1_delay
                        break
                    elif self.current_inflight["attempts"] == 2:
                        self.current_inflight["next_attempt_time"] = self.current_time + self.retry2_delay
                        break
                    else:
                        # Exhausted
                        self.dlt_queue.append(self.current_inflight)
                        self.main_processed += 1
                        self.current_inflight = None
                        if self.main_queue:
                            self.current_inflight = self.main_queue.pop(0)
                            self.current_inflight["next_attempt_time"] = self.current_time

            return f"PROCESS_OK mode=BLOCKING time={self.current_time}"

    def status(self):
        if self.mode == "NON_BLOCKING":
            hol = "false"
            main_p = len(self.main_queue)
            r1_p = len(self.retry1_queue)
            r2_p = len(self.retry2_queue)
        else:
            is_hol = (self.current_inflight is not None and self.current_time < self.current_inflight["next_attempt_time"])
            hol = "true" if is_hol else "false"
            main_p = len(self.main_queue) + (1 if self.current_inflight is not None else 0)
            r1_p = 0
            r2_p = 0

        lines = [
            "--- KAFKA_RETRY_STATUS ---",
            f"TIME: {self.current_time}s",
            f"MODE: {self.mode}",
            f"MAIN_PROCESSED: {self.main_processed}",
            f"MAIN_PENDING: {main_p}",
            f"RETRY_1_PENDING: {r1_p}",
            f"RETRY_2_PENDING: {r2_p}",
            f"DLT_COUNT: {len(self.dlt_queue)}",
            f"TOTAL_SUCCESS: {self.total_success}",
            f"HOL_BLOCKED: {hol}",
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
    sim = KafkaRetrySimulator()
    for line in sys.stdin:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split()
        cmd = parts[0].upper()
        kv, pos = parse_tokens(parts[1:])

        if cmd == "CONFIG":
            mode = kv.get("mode", pos[0] if len(pos) > 0 else "NON_BLOCKING")
            r1 = kv.get("retry1_delay", pos[1] if len(pos) > 1 else 5)
            r2 = kv.get("retry2_delay", pos[2] if len(pos) > 2 else 30)
            print(sim.config(mode, r1, r2))
        elif cmd == "PRODUCE":
            mid = kv.get("id", pos[0] if len(pos) > 0 else "")
            fc = kv.get("fail_count", pos[1] if len(pos) > 1 else 0)
            print(sim.produce(mid, fc))
        elif cmd == "TICK":
            sec = kv.get("seconds", pos[0] if len(pos) > 0 else 1)
            print(sim.tick(sec))
        elif cmd == "PROCESS":
            print(sim.process())
        elif cmd == "STATUS":
            print(sim.status())
        elif cmd == "RESET":
            sim.reset()
            print("RESET_OK")


if __name__ == "__main__":
    main()
