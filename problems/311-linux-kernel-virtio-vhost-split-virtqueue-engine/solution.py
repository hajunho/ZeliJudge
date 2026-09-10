# -*- coding: utf-8 -*-
"""
ZeliJudge Pro Track Problem #311
Linux Kernel VirtIO & vhost-net Split Virtqueue Ring Buffer Engine (virtio_ring.c, drivers/vhost/net.c)

Operationalizes the OASIS VirtIO 1.1 Standard and Linux Kernel Split Virtqueue:
1. Three Ring Components: Descriptor Table (vring_desc), Available Ring (vring_avail), Used Ring (vring_used).
2. Scatter-gather buffer descriptor chaining with VRING_DESC_F_NEXT and VRING_DESC_F_WRITE flags.
3. Guest enqueue (vring_avail.ring, avail.idx) & Host batch dequeuing/processing (vring_used.ring, used.idx).
4. Notification / Interrupt suppression mechanics:
   - VRING_AVAIL_F_NO_INTERRUPT (Guest tells Host not to raise call-eventfd/irqfd)
   - VRING_USED_F_NO_NOTIFY (Host tells Guest not to kick ioeventfd)
5. Zero-copy ring buffer wrapping, memory accounting, and descriptor exhaustion defense.
"""

import sys
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


VRING_DESC_F_NEXT = 1
VRING_DESC_F_WRITE = 2
VRING_DESC_F_INDIRECT = 4

VRING_AVAIL_F_NO_INTERRUPT = 1
VRING_USED_F_NO_NOTIFY = 1


def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return

    data = json.loads(raw_input)

    config = data.get("config", {})
    q_size = int(config.get("queue_size", 16))

    desc_table = [{"addr": 0, "len": 0, "flags": 0, "next": 0} for _ in range(q_size)]

    avail_flags = 0
    avail_idx = 0
    avail_ring = [0] * q_size

    used_flags = 0
    used_idx = 0
    used_ring = [{"id": 0, "len": 0} for _ in range(q_size)]

    free_head = 0
    for i in range(q_size - 1):
        desc_table[i]["next"] = i + 1
    desc_table[q_size - 1]["next"] = -1

    last_avail_idx = 0
    last_used_idx = 0

    commands = data.get("commands", [])
    cmd_logs = []

    kicks_sent = 0
    interrupts_raised = 0
    packets_processed = 0
    bytes_transferred = 0

    for c_idx, cmd in enumerate(commands, start=1):
        op = cmd.get("op")
        log_entry = {"command_index": c_idx, "op": op, "details": {}}

        if op == "GUEST_SUBMIT":
            buffers = cmd.get("buffers", [])
            if not buffers:
                log_entry["details"] = {"status": "EMPTY_BUFFERS"}
                cmd_logs.append(log_entry)
                continue

            needed = len(buffers)
            curr = free_head
            free_indices = []
            while curr != -1 and len(free_indices) < needed:
                free_indices.append(curr)
                curr = desc_table[curr]["next"]

            if len(free_indices) < needed:
                log_entry["details"] = {
                    "status": "DESCRIPTOR_EXHAUSTION",
                    "needed": needed,
                    "available": len(free_indices)
                }
                cmd_logs.append(log_entry)
                continue

            free_head = curr

            head_idx = free_indices[0]
            for i, d_idx in enumerate(free_indices):
                buf = buffers[i]
                d = desc_table[d_idx]
                d["addr"] = int(buf.get("addr", 0))
                d["len"] = int(buf.get("len", 0))
                d_flags = 0
                if buf.get("is_write", False):
                    d_flags |= VRING_DESC_F_WRITE
                if i < needed - 1:
                    d_flags |= VRING_DESC_F_NEXT
                    d["next"] = free_indices[i + 1]
                else:
                    d["next"] = -1
                d["flags"] = d_flags

            avail_ring[avail_idx % q_size] = head_idx
            avail_idx += 1

            need_kick = True
            if (used_flags & VRING_USED_F_NO_NOTIFY):
                need_kick = False

            if need_kick:
                kicks_sent += 1

            log_entry["details"] = {
                "status": "SUBMITTED",
                "head_desc": head_idx,
                "chain_length": needed,
                "avail_idx": avail_idx,
                "kick_sent": need_kick
            }

        elif op == "HOST_PROCESS_BATCH":
            max_batch = int(cmd.get("max_batch", q_size))
            processed = 0
            batch_bytes = 0

            while last_avail_idx < avail_idx and processed < max_batch:
                head = avail_ring[last_avail_idx % q_size]
                last_avail_idx += 1

                curr = head
                chain_len = 0
                chain_bytes = 0
                while curr != -1 and curr < q_size:
                    d = desc_table[curr]
                    chain_bytes += d["len"]
                    chain_len += 1
                    if d["flags"] & VRING_DESC_F_NEXT:
                        curr = d["next"]
                    else:
                        break

                used_ring[used_idx % q_size] = {"id": head, "len": chain_bytes}
                used_idx += 1

                processed += 1
                batch_bytes += chain_bytes

            packets_processed += processed
            bytes_transferred += batch_bytes

            need_interrupt = True
            if (avail_flags & VRING_AVAIL_F_NO_INTERRUPT):
                need_interrupt = False

            if processed > 0 and need_interrupt:
                interrupts_raised += 1

            log_entry["details"] = {
                "processed_count": processed,
                "batch_bytes": batch_bytes,
                "used_idx": used_idx,
                "interrupt_raised": need_interrupt if processed > 0 else False
            }

        elif op == "GUEST_REAP":
            reaped = 0
            while last_used_idx < used_idx:
                used_entry = used_ring[last_used_idx % q_size]
                last_used_idx += 1
                head = used_entry["id"]

                curr = head
                while curr != -1 and curr < q_size:
                    nxt = desc_table[curr]["next"] if (desc_table[curr]["flags"] & VRING_DESC_F_NEXT) else -1
                    desc_table[curr]["next"] = free_head
                    free_head = curr
                    curr = nxt

                reaped += 1

            log_entry["details"] = {
                "reaped_count": reaped,
                "last_used_idx": last_used_idx,
                "free_head": free_head
            }

        elif op == "SET_FLAGS":
            if "avail_flags" in cmd:
                avail_flags = int(cmd["avail_flags"])
            if "used_flags" in cmd:
                used_flags = int(cmd["used_flags"])
            log_entry["details"] = {
                "avail_flags": avail_flags,
                "used_flags": used_flags
            }

        cmd_logs.append(log_entry)

    output = {
        "summary": {
            "queue_size": q_size,
            "packets_processed": packets_processed,
            "bytes_transferred": bytes_transferred,
            "kicks_sent": kicks_sent,
            "interrupts_raised": interrupts_raised,
            "final_avail_idx": avail_idx,
            "final_used_idx": used_idx
        },
        "command_history": cmd_logs
    }

    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    solve()
