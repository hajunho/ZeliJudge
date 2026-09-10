# -*- coding: utf-8 -*-
"""
ZeliJudge Pro #384: Linux Kernel SLUB Allocator Redzoning, Object Poisoning & Freelist Hardening Engine
Implementation in Python 3.
"""
import sys
import json

def swab64(x):
    b = x.to_bytes(8, byteorder='little')
    return int.from_bytes(b[::-1], byteorder='little')

class SlubSimulationEngine:
    def __init__(self, config):
        self.slab_size = config.get("slab_size", 1024)
        self.object_size = config.get("object_size", 64)
        self.redzone_size = config.get("redzone_size", 16)
        self.poison_byte = config.get("poison_byte", 0x6b)
        self.redzone_byte = config.get("redzone_byte", 0xbb)
        self.freelist_hardened = config.get("freelist_hardened", True)
        self.freelist_random = config.get("freelist_random", False)
        self.cookie = config.get("cookie", 0xdeadbeefcafebabe)
        self.base_address = config.get("base_address", 0xffff888000000000)

        self.slot_size = self.redzone_size + self.object_size + self.redzone_size
        self.max_objects = self.slab_size // self.slot_size

        self.slots = []
        for i in range(self.max_objects):
            slot_addr = self.base_address + i * self.slot_size
            payload_addr = slot_addr + self.redzone_size
            self.slots.append({
                "index": i,
                "slot_addr": slot_addr,
                "payload_addr": payload_addr,
                "state": "FREE",
                "left_rz": bytearray([self.redzone_byte] * self.redzone_size),
                "payload": bytearray([self.poison_byte] * self.object_size),
                "right_rz": bytearray([self.redzone_byte] * self.redzone_size),
                "obj_id": None,
                "alloc_caller": None,
                "free_caller": None,
                "encoded_next": 0
            })

        order = list(range(self.max_objects))
        if self.freelist_random:
            seed = config.get("random_seed", 42)
            for i in range(len(order) - 1, 0, -1):
                seed = (seed * 1103515245 + 12345) & 0x7fffffff
                j = seed % (i + 1)
                order[i], order[j] = order[j], order[i]

        self.freelist_head = order[0] if order else None
        for k in range(len(order)):
            curr_idx = order[k]
            next_idx = order[k + 1] if k + 1 < len(order) else None
            next_addr = self.slots[next_idx]["payload_addr"] if next_idx is not None else 0
            curr_payload_addr = self.slots[curr_idx]["payload_addr"]

            if self.freelist_hardened:
                encoded = next_addr ^ self.cookie ^ swab64(curr_payload_addr)
            else:
                encoded = next_addr
            self.slots[curr_idx]["encoded_next"] = encoded

        self.obj_map = {}
        self.events = []
        self.corruptions_detected = 0

    def _decode_ptr(self, curr_idx, encoded_val):
        curr_payload_addr = self.slots[curr_idx]["payload_addr"]
        if self.freelist_hardened:
            return encoded_val ^ self.cookie ^ swab64(curr_payload_addr)
        else:
            return encoded_val

    def _encode_ptr(self, curr_idx, target_addr):
        curr_payload_addr = self.slots[curr_idx]["payload_addr"]
        if self.freelist_hardened:
            return target_addr ^ self.cookie ^ swab64(curr_payload_addr)
        else:
            return target_addr

    def run_commands(self, commands):
        for cmd in commands:
            op = cmd.get("op")
            if op == "KMALLOC":
                self._handle_kmalloc(cmd)
            elif op == "KFREE":
                self._handle_kfree(cmd)
            elif op == "WRITE":
                self._handle_write(cmd)
            elif op == "VALIDATE_SLAB":
                self._handle_validate(cmd)
            elif op == "CORRUPT_FREELIST_RAW":
                self._handle_corrupt_freelist_raw(cmd)

    def _handle_kmalloc(self, cmd):
        obj_id = cmd["obj_id"]
        caller_pc = cmd.get("caller_pc", "0xffffffff81000000")

        if self.freelist_head is None:
            self.events.append({
                "op": "KMALLOC",
                "obj_id": obj_id,
                "status": "FAIL_OUT_OF_SLAB",
                "reason": "Freelist empty"
            })
            return

        slot_idx = self.freelist_head
        slot = self.slots[slot_idx]

        decoded_next_addr = self._decode_ptr(slot_idx, slot["encoded_next"])
        next_head = None
        if decoded_next_addr != 0:
            found = False
            for s in self.slots:
                if s["payload_addr"] == decoded_next_addr:
                    next_head = s["index"]
                    found = True
                    break
            if not found:
                self.corruptions_detected += 1
                self.events.append({
                    "op": "KMALLOC",
                    "obj_id": obj_id,
                    "status": "CRITICAL_PANIC",
                    "reason": "SLUB_FREELIST_CORRUPTED",
                    "slot_index": slot_idx,
                    "invalid_ptr": hex(decoded_next_addr)
                })
                return
        else:
            next_head = None

        poison_corrupted = False
        for b in slot["payload"]:
            if b != self.poison_byte:
                poison_corrupted = True
                break
        if poison_corrupted:
            self.corruptions_detected += 1
            self.events.append({
                "op": "KMALLOC",
                "obj_id": obj_id,
                "warning": "SLUB_POISON_CORRUPTED_BEFORE_ALLOC",
                "slot_index": slot_idx
            })

        self.freelist_head = next_head
        slot["state"] = "ALLOCATED"
        slot["obj_id"] = obj_id
        slot["alloc_caller"] = caller_pc
        slot["free_caller"] = None
        slot["left_rz"] = bytearray([self.redzone_byte] * self.redzone_size)
        slot["right_rz"] = bytearray([self.redzone_byte] * self.redzone_size)
        slot["payload"] = bytearray([0x00] * self.object_size)

        self.obj_map[obj_id] = slot_idx
        self.events.append({
            "op": "KMALLOC",
            "obj_id": obj_id,
            "status": "SUCCESS",
            "slot_index": slot_idx,
            "address": hex(slot["payload_addr"])
        })

    def _handle_kfree(self, cmd):
        obj_id = cmd["obj_id"]
        caller_pc = cmd.get("caller_pc", "0xffffffff81000000")

        if obj_id not in self.obj_map:
            self.events.append({
                "op": "KFREE",
                "obj_id": obj_id,
                "status": "FAIL_INVALID_OBJECT",
                "reason": "Object not tracked"
            })
            return

        slot_idx = self.obj_map[obj_id]
        slot = self.slots[slot_idx]

        if slot["state"] == "FREE":
            self.corruptions_detected += 1
            self.events.append({
                "op": "KFREE",
                "obj_id": obj_id,
                "status": "CRITICAL_PANIC",
                "reason": "SLUB_DOUBLE_FREE_DETECTED",
                "slot_index": slot_idx
            })
            return

        left_corrupt = any(b != self.redzone_byte for b in slot["left_rz"])
        right_corrupt = any(b != self.redzone_byte for b in slot["right_rz"])

        if left_corrupt:
            self.corruptions_detected += 1
            self.events.append({
                "op": "KFREE",
                "obj_id": obj_id,
                "warning": "SLUB_REDZONE_UNDERFLOW_DETECTED",
                "slot_index": slot_idx
            })

        if right_corrupt:
            self.corruptions_detected += 1
            self.events.append({
                "op": "KFREE",
                "obj_id": obj_id,
                "warning": "SLUB_REDZONE_OVERFLOW_DETECTED",
                "slot_index": slot_idx
            })

        slot["payload"] = bytearray([self.poison_byte] * self.object_size)
        slot["state"] = "FREE"
        slot["free_caller"] = caller_pc

        curr_head_addr = self.slots[self.freelist_head]["payload_addr"] if self.freelist_head is not None else 0
        slot["encoded_next"] = self._encode_ptr(slot_idx, curr_head_addr)
        self.freelist_head = slot_idx

        self.events.append({
            "op": "KFREE",
            "obj_id": obj_id,
            "status": "SUCCESS",
            "slot_index": slot_idx
        })

    def _handle_write(self, cmd):
        obj_id = cmd["obj_id"]
        offset = cmd["offset"]
        data_hex = cmd["data_hex"]

        if obj_id not in self.obj_map:
            self.events.append({
                "op": "WRITE",
                "obj_id": obj_id,
                "status": "FAIL_UNKNOWN_OBJECT"
            })
            return

        slot_idx = self.obj_map[obj_id]
        slot = self.slots[slot_idx]
        data_bytes = bytes.fromhex(data_hex)

        for i, b in enumerate(data_bytes):
            curr_off = offset + i
            if curr_off < 0:
                rz_idx = self.redzone_size + curr_off
                if 0 <= rz_idx < self.redzone_size:
                    slot["left_rz"][rz_idx] = b
            elif curr_off < self.object_size:
                slot["payload"][curr_off] = b
            else:
                right_idx = curr_off - self.object_size
                if 0 <= right_idx < self.redzone_size:
                    slot["right_rz"][right_idx] = b

        self.events.append({
            "op": "WRITE",
            "obj_id": obj_id,
            "status": "SUCCESS",
            "offset": offset,
            "bytes_written": len(data_bytes)
        })

    def _handle_corrupt_freelist_raw(self, cmd):
        slot_idx = cmd["slot_index"]
        corrupt_val = cmd["raw_value"]
        if 0 <= slot_idx < self.max_objects:
            self.slots[slot_idx]["encoded_next"] = corrupt_val
            self.events.append({
                "op": "CORRUPT_FREELIST_RAW",
                "slot_index": slot_idx,
                "status": "SUCCESS"
            })

    def _handle_validate(self, cmd):
        issues = []
        for slot in self.slots:
            idx = slot["index"]
            if any(b != self.redzone_byte for b in slot["left_rz"]):
                issues.append({"slot": idx, "type": "REDZONE_LEFT_CORRUPTED"})
            if any(b != self.redzone_byte for b in slot["right_rz"]):
                issues.append({"slot": idx, "type": "REDZONE_RIGHT_CORRUPTED"})
            if slot["state"] == "FREE":
                if any(b != self.poison_byte for b in slot["payload"]):
                    issues.append({"slot": idx, "type": "POISON_CORRUPTED"})

        self.events.append({
            "op": "VALIDATE_SLAB",
            "issues_count": len(issues),
            "issues": issues
        })

    def get_result(self):
        alloc_count = sum(1 for s in self.slots if s["state"] == "ALLOCATED")
        free_count = sum(1 for s in self.slots if s["state"] == "FREE")
        return {
            "total_slots": self.max_objects,
            "allocated_count": alloc_count,
            "free_count": free_count,
            "corruptions_detected": self.corruptions_detected,
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

    engine = SlubSimulationEngine(config)
    engine.run_commands(commands)
    result = engine.get_result()

    sys.stdout.write(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
