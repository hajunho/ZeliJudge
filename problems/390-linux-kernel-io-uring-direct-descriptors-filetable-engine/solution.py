# -*- coding: utf-8 -*-
"""
ZeliJudge Pro #390: Linux Kernel io_uring Direct Descriptors & Fixed Buffers Engine
Implementation in Python 3.
"""
import sys
import json

class IoUringDirectEngine:
    def __init__(self, config):
        self.file_table_cap = config.get("file_table_capacity", 16)
        self.file_table = [None] * self.file_table_cap

        self.buf_table_cap = config.get("buf_table_capacity", 16)
        self.buf_table = [None] * self.buf_table_cap

        raw_posix = config.get("posix_fds", {})
        self.posix_fd_map = {int(k): v for k, v in raw_posix.items()}

        self.atomic_refcount_ops = 0
        self.page_pin_ops = 0
        self.refcount_ops_saved = 0
        self.page_pins_saved = 0

        self.sqe_count = 0
        self.cqe_count = 0
        self.cqes = []
        self.events = []

    def run_commands(self, commands):
        for cmd in commands:
            op = cmd.get("op")
            if op == "REGISTER_FILES":
                self._handle_register_files(cmd)
            elif op == "UPDATE_FILES":
                self._handle_update_files(cmd)
            elif op == "REGISTER_BUFFERS":
                self._handle_register_buffers(cmd)
            elif op == "SUBMIT_SQE":
                self._handle_submit_sqe(cmd)

    def _handle_register_files(self, cmd):
        files = cmd.get("files", [])
        for idx, f in enumerate(files):
            if idx < self.file_table_cap:
                self.file_table[idx] = {"path": f, "slot": idx}
                self.atomic_refcount_ops += 1

        self.events.append({
            "op": "REGISTER_FILES",
            "registered_count": len(files),
            "status": "SUCCESS"
        })

    def _handle_update_files(self, cmd):
        slot = cmd["slot"]
        new_file = cmd.get("file")
        if 0 <= slot < self.file_table_cap:
            old = self.file_table[slot]
            if old:
                self.atomic_refcount_ops += 1
            if new_file:
                self.file_table[slot] = {"path": new_file, "slot": slot}
                self.atomic_refcount_ops += 1
            else:
                self.file_table[slot] = None

            self.events.append({
                "op": "UPDATE_FILES",
                "slot": slot,
                "status": "SUCCESS"
            })
        else:
            self.events.append({
                "op": "UPDATE_FILES",
                "slot": slot,
                "status": "FAIL_OUT_OF_BOUNDS"
            })

    def _handle_register_buffers(self, cmd):
        buffers = cmd.get("buffers", [])
        for b in buffers:
            idx = b["buf_idx"]
            if 0 <= idx < self.buf_table_cap:
                self.buf_table[idx] = b
                self.page_pin_ops += 1

        self.events.append({
            "op": "REGISTER_BUFFERS",
            "registered_count": len(buffers),
            "status": "SUCCESS"
        })

    def _handle_submit_sqe(self, cmd):
        self.sqe_count += 1
        user_data = cmd["user_data"]
        opcode = cmd.get("opcode", "READ")
        fd_type = cmd.get("fd_type", "POSIX")
        fd_val = cmd["fd_val"]
        buf_type = cmd.get("buf_type", "NORMAL")
        buf_val = cmd.get("buf_val", 0)
        length = cmd.get("length", 1024)

        if fd_type == "POSIX":
            if fd_val not in self.posix_fd_map:
                self._emit_cqe(user_data, -9, "EBADF")
                return
            self.atomic_refcount_ops += 2
        else:
            if fd_val < 0 or fd_val >= self.file_table_cap or self.file_table[fd_val] is None:
                self._emit_cqe(user_data, -9, "EBADF_DIRECT_SLOT_EMPTY")
                return
            self.refcount_ops_saved += 2

        if buf_type == "NORMAL":
            self.page_pin_ops += 2
        else:
            if buf_val < 0 or buf_val >= self.buf_table_cap or self.buf_table[buf_val] is None:
                self._emit_cqe(user_data, -14, "EFAULT_FIXED_BUF_NOT_REGISTERED")
                return
            self.page_pins_saved += 2

        self._emit_cqe(user_data, length, "SUCCESS")

    def _emit_cqe(self, user_data, res, status):
        self.cqe_count += 1
        cqe = {
            "user_data": user_data,
            "res": res,
            "status": status
        }
        self.cqes.append(cqe)
        self.events.append({
            "op": "CQE",
            "cqe": cqe
        })

    def get_result(self):
        return {
            "total_sqes": self.sqe_count,
            "total_cqes": self.cqe_count,
            "atomic_refcount_ops": self.atomic_refcount_ops,
            "refcount_ops_saved": self.refcount_ops_saved,
            "page_pin_ops": self.page_pin_ops,
            "page_pins_saved": self.page_pins_saved,
            "active_direct_files": sum(1 for f in self.file_table if f is not None),
            "active_fixed_buffers": sum(1 for b in self.buf_table if b is not None),
            "events": self.events
        }

def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    commands = data.get("commands", [])

    engine = IoUringDirectEngine(config)
    engine.run_commands(commands)
    result = engine.get_result()

    sys.stdout.write(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
