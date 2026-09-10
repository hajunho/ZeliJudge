# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #309: 리눅스 커널 io_uring(fs/io_uring.c) SQPOLL 제로 시스콜 링 버퍼 및 비동기 I/O 체인 엔진
Linux Kernel fs/io_uring.c IORING_SETUP_SQPOLL, Submission/Completion Ring Buffers,
IOSQE_IO_LINK 체인, 유휴 타임아웃 슬립 및 IORING_ENTER_SQ_WAKEUP 시뮬레이션
"""
import sys
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def run_iouring_engine(data):
    config = data.get("config", {})
    sq_entries = config.get("sq_entries", 8)
    cq_entries = config.get("cq_entries", 16)
    sqpoll = config.get("sqpoll_enabled", True)
    idle_ms = config.get("sq_thread_idle_ms", 100)

    files = {int(k): dict(v) for k, v in data.get("files", {}).items()}
    ops = data.get("operations", [])

    sq_ring = []
    cq_ring = []

    sq_head = 0
    sq_tail = 0
    cq_head = 0
    cq_tail = 0

    sq_thread_sleeping = False
    last_sq_activity_ts = 0

    syscall_enter_count = 0
    total_sqes_submitted = 0
    total_cqes_posted = 0
    drained_cqes = []

    def process_sqes(sqes_to_run):
        nonlocal cq_tail, total_cqes_posted
        i = 0
        while i < len(sqes_to_run):
            sqe = sqes_to_run[i]
            opc = sqe.get("opcode")
            fd = sqe.get("fd")
            offset = sqe.get("offset", 0)
            length = sqe.get("len", 0)
            flags = sqe.get("flags", [])
            u_data = sqe.get("user_data", 0)
            is_linked = "IOSQE_IO_LINK" in flags

            res = 0
            if opc == "NOP":
                res = 0
            elif opc == "READ":
                if fd not in files:
                    res = -9  # -EBADF
                else:
                    f_size = files[fd].get("size", 0)
                    if offset >= f_size:
                        res = 0  # EOF
                    else:
                        res = min(length, f_size - offset)
            elif opc == "WRITE":
                if fd not in files:
                    res = -9  # -EBADF
                else:
                    files[fd]["size"] = max(files[fd].get("size", 0), offset + length)
                    res = length
            elif opc == "FSYNC":
                if fd not in files:
                    res = -9  # -EBADF
                else:
                    res = 0
            else:
                res = -22  # -EINVAL

            cq_entry = {
                "user_data": u_data,
                "res": res,
                "flags": 0
            }
            cq_ring.append(cq_entry)
            cq_tail += 1
            total_cqes_posted += 1

            # If failed and linked, cancel subsequent linked SQEs
            if res < 0 and is_linked:
                j = i + 1
                while j < len(sqes_to_run):
                    cancel_sqe = sqes_to_run[j]
                    cancel_flags = cancel_sqe.get("flags", [])
                    cq_ring.append({
                        "user_data": cancel_sqe.get("user_data", 0),
                        "res": -125,  # -ECANCELED
                        "flags": 0
                    })
                    cq_tail += 1
                    total_cqes_posted += 1
                    if "IOSQE_IO_LINK" not in cancel_flags:
                        i = j
                        break
                    j += 1
            i += 1

    for op in ops:
        op_id = op["op_id"]
        ts = op.get("timestamp_ms", 0)
        op_type = op["type"]

        if sqpoll:
            if (ts - last_sq_activity_ts) > idle_ms and not sq_ring:
                sq_thread_sleeping = True

        if op_type == "SUBMIT_SQE":
            sqe = dict(op)
            sq_ring.append(sqe)
            sq_tail += 1
            total_sqes_submitted += 1
            last_sq_activity_ts = ts

            if sqpoll and not sq_thread_sleeping:
                to_proc = list(sq_ring)
                sq_ring = []
                sq_head += len(to_proc)
                process_sqes(to_proc)

        elif op_type == "ENTER_SYSCALL":
            syscall_enter_count += 1
            enter_flags = op.get("flags", [])
            if "IORING_ENTER_SQ_WAKEUP" in enter_flags:
                sq_thread_sleeping = False

            if sq_ring:
                to_proc = list(sq_ring)
                sq_ring = []
                sq_head += len(to_proc)
                process_sqes(to_proc)

        elif op_type == "DRAIN_CQE":
            max_ev = op.get("max_events", cq_entries)
            drained = []
            while cq_ring and len(drained) < max_ev:
                drained.append(cq_ring.pop(0))
                cq_head += 1
            drained_cqes.append({
                "op_id": op_id,
                "count": len(drained),
                "cqes": drained
            })

    zero_sys_rate = 0.0
    if total_sqes_submitted > 0:
        if syscall_enter_count == 0:
            zero_sys_rate = 1.0
        elif syscall_enter_count < total_sqes_submitted:
            zero_sys_rate = round(1.0 - (syscall_enter_count / total_sqes_submitted), 4)
        else:
            zero_sys_rate = 0.0

    return {
        "summary": {
            "sqpoll_enabled": sqpoll,
            "total_sqes_submitted": total_sqes_submitted,
            "total_cqes_posted": total_cqes_posted,
            "total_syscall_enters": syscall_enter_count,
            "zero_syscall_rate": zero_sys_rate,
            "final_sq_ring_empty": len(sq_ring) == 0,
            "final_cq_ring_pending": len(cq_ring)
        },
        "drained_batches": drained_cqes
    }


def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    result = run_iouring_engine(data)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
