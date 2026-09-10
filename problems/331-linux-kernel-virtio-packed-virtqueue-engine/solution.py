import sys
import json

# Windows 콘솔 UTF-8 입출력 호환성 보장
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

VRING_DESC_F_NEXT = 0x0001
VRING_DESC_F_WRITE = 0x0002
VRING_DESC_F_INDIRECT = 0x0004
VRING_PACKED_DESC_F_AVAIL = 0x0080
VRING_PACKED_DESC_F_USED = 0x8000

RING_EVENT_FLAGS_ENABLE = 0x0
RING_EVENT_FLAGS_DISABLE = 0x1
RING_EVENT_FLAGS_DESC = 0x2

def is_in_batch(start_idx, start_wrap, count, target_off, target_wrap, ring_size):
    curr_idx = start_idx
    curr_wrap = start_wrap
    for _ in range(count):
        if curr_idx == target_off and curr_wrap == target_wrap:
            return True
        curr_idx += 1
        if curr_idx >= ring_size:
            curr_idx = 0
            curr_wrap ^= 1
    return False

class VirtIOPackedVirtqueue:
    def __init__(self, size: int):
        self.size = size
        self.ring = [{
            "addr": 0,
            "len": 0,
            "id": 0,
            "flags": 0,
            "indirect_table": []
        } for _ in range(size)]
        
        # Driver state
        self.driver_avail_idx = 0
        self.driver_avail_wrap = 1
        self.driver_used_idx = 0
        self.driver_used_wrap = 1
        self.free_slots = size
        
        # Driver descriptor state table (id -> {"num": chain_len})
        self.desc_state = {}
        
        # Device state
        self.device_avail_idx = 0
        self.device_avail_wrap = 1
        self.device_used_idx = 0
        self.device_used_wrap = 1
        
        # Event suppression structures
        self.driver_event = {"flags": RING_EVENT_FLAGS_ENABLE, "off": 0, "wrap": 0}
        self.device_event = {"flags": RING_EVENT_FLAGS_ENABLE, "off": 0, "wrap": 0}
        
        # Counters
        self.kicks_sent = 0
        self.kicks_suppressed = 0
        self.irqs_sent = 0
        self.irqs_suppressed = 0
        self.total_submitted_buffers = 0
        self.total_completed_buffers = 0
        self.total_descriptors_reaped = 0

    def should_kick(self, start_idx, start_wrap, count):
        flags = self.device_event["flags"]
        if flags == RING_EVENT_FLAGS_DISABLE:
            return False
        if flags == RING_EVENT_FLAGS_ENABLE:
            return True
        if flags == RING_EVENT_FLAGS_DESC:
            return is_in_batch(start_idx, start_wrap, count,
                               self.device_event["off"], self.device_event["wrap"], self.size)
        return True

    def should_irq(self, start_idx, start_wrap, count):
        flags = self.driver_event["flags"]
        if flags == RING_EVENT_FLAGS_DISABLE:
            return False
        if flags == RING_EVENT_FLAGS_ENABLE:
            return True
        if flags == RING_EVENT_FLAGS_DESC:
            return is_in_batch(start_idx, start_wrap, count,
                               self.driver_event["off"], self.driver_event["wrap"], self.size)
        return True

    def submit_buffer(self, buffer_id: int, descs: list):
        chain_len = len(descs)
        if self.free_slots < chain_len:
            return {
                "status": "QUEUE_FULL",
                "buffer_id": buffer_id,
                "required": chain_len,
                "free_slots": self.free_slots
            }

        start_idx = self.driver_avail_idx
        start_wrap = self.driver_avail_wrap
        self.desc_state[buffer_id] = {"num": chain_len, "start_idx": start_idx}

        curr_idx = start_idx
        curr_wrap = start_wrap
        staged = []

        for i, d in enumerate(descs):
            is_last = (i == chain_len - 1)
            flags = 0
            if not is_last:
                flags |= VRING_DESC_F_NEXT
            if d.get("write", False):
                flags |= VRING_DESC_F_WRITE
            if d.get("indirect", False):
                flags |= VRING_DESC_F_INDIRECT

            avail_flag = VRING_PACKED_DESC_F_AVAIL if curr_wrap == 1 else 0
            used_flag = 0 if curr_wrap == 1 else VRING_PACKED_DESC_F_USED
            desc_flags = flags | avail_flag | used_flag

            staged.append({
                "idx": curr_idx,
                "addr": d["addr"],
                "len": d["len"],
                "id": buffer_id,
                "flags": desc_flags,
                "indirect_table": d.get("indirect_table", [])
            })

            curr_idx += 1
            if curr_idx >= self.size:
                curr_idx = 0
                curr_wrap ^= 1

        # Memory ordering: write descriptors 1..N-1 first
        for entry in staged[1:]:
            idx = entry["idx"]
            self.ring[idx] = {
                "addr": entry["addr"],
                "len": entry["len"],
                "id": entry["id"],
                "flags": entry["flags"],
                "indirect_table": entry["indirect_table"]
            }

        # Write head descriptor last
        head = staged[0]
        self.ring[head["idx"]] = {
            "addr": head["addr"],
            "len": head["len"],
            "id": head["id"],
            "flags": head["flags"],
            "indirect_table": head["indirect_table"]
        }

        self.driver_avail_idx = curr_idx
        self.driver_avail_wrap = curr_wrap
        self.free_slots -= chain_len
        self.total_submitted_buffers += 1

        kick = self.should_kick(start_idx, start_wrap, chain_len)
        if kick:
            self.kicks_sent += 1
        else:
            self.kicks_suppressed += 1

        return {
            "status": "SUBMITTED",
            "buffer_id": buffer_id,
            "chain_len": chain_len,
            "start_idx": start_idx,
            "next_avail_idx": self.driver_avail_idx,
            "avail_wrap": self.driver_avail_wrap,
            "kick_notified": kick,
            "free_slots": self.free_slots
        }

    def device_process(self, max_chains: int = 16):
        chains_done = []
        old_used_idx = self.device_used_idx
        start_wrap = self.device_used_wrap
        total_descs_processed = 0

        while len(chains_done) < max_chains:
            head = self.ring[self.device_avail_idx]
            flags = head["flags"]
            avail_bit = 1 if (flags & VRING_PACKED_DESC_F_AVAIL) else 0
            used_bit = 1 if (flags & VRING_PACKED_DESC_F_USED) else 0

            # Available condition: avail == wrap and used != wrap
            if not ((avail_bit == self.device_avail_wrap) and (used_bit != self.device_avail_wrap)):
                break

            buf_id = head["id"]
            curr_idx = self.device_avail_idx
            curr_wrap = self.device_avail_wrap
            chain_descs = []
            total_len = 0

            while True:
                desc = self.ring[curr_idx]
                chain_descs.append(curr_idx)

                if desc["flags"] & VRING_DESC_F_INDIRECT:
                    indirect_bytes = sum(entry["len"] for entry in desc.get("indirect_table", []))
                    total_len += indirect_bytes
                else:
                    total_len += desc["len"]

                has_next = bool(desc["flags"] & VRING_DESC_F_NEXT)
                curr_idx += 1
                if curr_idx >= self.size:
                    curr_idx = 0
                    curr_wrap ^= 1

                if not has_next:
                    break

            self.device_avail_idx = curr_idx
            self.device_avail_wrap = curr_wrap

            chain_len = len(chain_descs)
            total_descs_processed += chain_len
            used_idx = self.device_used_idx
            used_wrap = self.device_used_wrap

            used_flags = (VRING_PACKED_DESC_F_AVAIL | VRING_PACKED_DESC_F_USED) if used_wrap == 1 else 0

            # Write head used info
            self.ring[used_idx]["id"] = buf_id
            self.ring[used_idx]["len"] = total_len
            self.ring[used_idx]["flags"] = used_flags

            for i in range(1, chain_len):
                slot = (used_idx + i) % self.size
                slot_wrap = used_wrap if (used_idx + i) < self.size else (used_wrap ^ 1)
                slot_flags = (VRING_PACKED_DESC_F_AVAIL | VRING_PACKED_DESC_F_USED) if slot_wrap == 1 else 0
                self.ring[slot]["flags"] = slot_flags

            next_used = (used_idx + chain_len) % self.size
            if used_idx + chain_len >= self.size:
                self.device_used_wrap ^= 1
            self.device_used_idx = next_used

            chains_done.append({
                "buffer_id": buf_id,
                "chain_len": chain_len,
                "bytes_transferred": total_len
            })

        irq = False
        if chains_done:
            irq = self.should_irq(old_used_idx, start_wrap, total_descs_processed)
            if irq:
                self.irqs_sent += 1
            else:
                self.irqs_suppressed += 1

        return {
            "status": "DEVICE_BATCH_COMPLETE",
            "chains_processed": len(chains_done),
            "chains": chains_done,
            "next_used_idx": self.device_used_idx,
            "used_wrap": self.device_used_wrap,
            "irq_notified": irq
        }

    def driver_reap(self, max_reap: int = 16):
        reaped = []

        while len(reaped) < max_reap:
            desc = self.ring[self.driver_used_idx]
            flags = desc["flags"]
            avail_bit = 1 if (flags & VRING_PACKED_DESC_F_AVAIL) else 0
            used_bit = 1 if (flags & VRING_PACKED_DESC_F_USED) else 0

            # Used condition: avail == wrap and used == wrap
            if not ((avail_bit == self.driver_used_wrap) and (used_bit == self.driver_used_wrap)):
                break

            buf_id = desc["id"]
            transferred = desc["len"]
            state = self.desc_state.get(buf_id, {"num": 1})
            chain_len = state["num"]

            curr_used = self.driver_used_idx
            next_used = (curr_used + chain_len) % self.size
            if curr_used + chain_len >= self.size:
                self.driver_used_wrap ^= 1
            self.driver_used_idx = next_used

            self.free_slots += chain_len
            self.total_completed_buffers += 1
            self.total_descriptors_reaped += chain_len
            del self.desc_state[buf_id]

            reaped.append({
                "buffer_id": buf_id,
                "chain_len": chain_len,
                "bytes_transferred": transferred
            })

        return {
            "status": "REAPED",
            "count": len(reaped),
            "reaped": reaped,
            "next_driver_used_idx": self.driver_used_idx,
            "driver_used_wrap": self.driver_used_wrap,
            "free_slots": self.free_slots
        }

    def configure_event(self, target: str, flags_str: str, off: int = 0, wrap: int = 0):
        flag_map = {"ENABLE": RING_EVENT_FLAGS_ENABLE, "DISABLE": RING_EVENT_FLAGS_DISABLE, "DESC": RING_EVENT_FLAGS_DESC}
        cfg = {"flags": flag_map.get(flags_str, 0), "off": off, "wrap": wrap}
        if target == "driver":
            self.driver_event = cfg
        else:
            self.device_event = cfg
        return {"status": f"{target.upper()}_EVENT_CONFIGURED", "event": cfg}

    def inspect(self):
        return {
            "ring_size": self.size,
            "free_slots": self.free_slots,
            "driver_avail": {"idx": self.driver_avail_idx, "wrap": self.driver_avail_wrap},
            "device_avail": {"idx": self.device_avail_idx, "wrap": self.device_avail_wrap},
            "device_used": {"idx": self.device_used_idx, "wrap": self.device_used_wrap},
            "driver_used": {"idx": self.driver_used_idx, "wrap": self.driver_used_wrap},
            "stats": {
                "total_submitted": self.total_submitted_buffers,
                "total_completed": self.total_completed_buffers,
                "total_descriptors_reaped": self.total_descriptors_reaped,
                "kicks_sent": self.kicks_sent,
                "kicks_suppressed": self.kicks_suppressed,
                "irqs_sent": self.irqs_sent,
                "irqs_suppressed": self.irqs_suppressed
            }
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return

    commands = json.loads(raw_input)
    vq = None
    results = []

    for cmd in commands:
        op = cmd.get("op")
        if op == "INIT":
            vq = VirtIOPackedVirtqueue(cmd["size"])
            results.append({"op": "INIT", "status": "OK", "ring_size": cmd["size"]})
        elif op == "SUBMIT":
            res = vq.submit_buffer(cmd["buffer_id"], cmd["descriptors"])
            results.append({"op": "SUBMIT", "result": res})
        elif op == "DEVICE_PROCESS":
            max_c = cmd.get("max_chains", 16)
            res = vq.device_process(max_c)
            results.append({"op": "DEVICE_PROCESS", "result": res})
        elif op == "DRIVER_REAP":
            max_r = cmd.get("max_reap", 16)
            res = vq.driver_reap(max_r)
            results.append({"op": "DRIVER_REAP", "result": res})
        elif op == "CONFIG_EVENT":
            target = cmd["target"]
            flags = cmd["flags"]
            off = cmd.get("off", 0)
            wrap = cmd.get("wrap", 0)
            res = vq.configure_event(target, flags, off, wrap)
            results.append({"op": "CONFIG_EVENT", "result": res})
        elif op == "INSPECT":
            res = vq.inspect()
            results.append({"op": "INSPECT", "result": res})
        else:
            results.append({"op": op, "status": "UNKNOWN_OP"})

    print(json.dumps(results, separators=(',', ':')))

if __name__ == "__main__":
    main()
