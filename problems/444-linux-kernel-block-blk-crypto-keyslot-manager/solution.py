# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #444 Solution:
Linux Kernel Block Layer & Storage Security: block/blk-crypto.c Inline Crypto Keyslot Manager
(block/blk-crypto.c, block/blk-crypto-profile.c, include/linux/blk-crypto.h)
"""

import sys
import json

# Ensure UTF-8 streams on Windows
if sys.platform == "win32":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")


class BlkCryptoEngine:
    def __init__(self, config):
        self.num_keyslots = config.get("num_keyslots", 4)
        self.supported_modes = config.get("supported_modes", ["AES_256_XTS", "SM4_XTS"])
        self.data_unit_size = config.get("data_unit_size", 4096)
        self.sw_fallback_enabled = config.get("software_fallback_enabled", True)
        
        self.slots = []
        for i in range(self.num_keyslots):
            self.slots.append({
                "slot_id": i,
                "key_id": None,
                "crypto_mode": None,
                "refcount": 0,
                "last_used_timestamp": 0
            })
            
        self.active_bios = {}
        
        self.keyslot_hits = 0
        self.keyslot_allocs = 0
        self.keyslot_evictions = 0
        self.fallback_sw_crypt = 0
        self.total_bios_processed = 0
        self.total_bytes_encrypted = 0

    def execute_command(self, cmd):
        op = cmd.get("op")
        if op == "SUBMIT_BIO_CRYPT":
            return self._submit_bio_crypt(cmd)
        elif op == "COMPLETE_BIO_CRYPT":
            return self._complete_bio_crypt(cmd)
        elif op == "EVICT_KEY_EXPLICIT":
            return self._evict_key_explicit(cmd)
        elif op == "GET_STATS":
            return self._get_stats(cmd)
        else:
            return {"op": op, "status": "UNKNOWN_OP"}

    def _submit_bio_crypt(self, cmd):
        bio_id = cmd["bio_id"]
        key_id = cmd["key_id"]
        mode = cmd.get("crypto_mode", "AES_256_XTS")
        sector = cmd.get("sector", 0)
        num_sectors = cmd.get("num_sectors", 8)
        timestamp = cmd.get("timestamp", 0)
        
        byte_len = num_sectors * 512
        dun = (sector * 512) // self.data_unit_size
        self.total_bios_processed += 1
        self.total_bytes_encrypted += byte_len
        
        target_slot = None
        for s in self.slots:
            if s["key_id"] == key_id and s["crypto_mode"] == mode:
                target_slot = s
                self.keyslot_hits += 1
                status = "KEYSLOT_HIT"
                break
                
        if not target_slot:
            for s in self.slots:
                if s["key_id"] is None:
                    target_slot = s
                    target_slot["key_id"] = key_id
                    target_slot["crypto_mode"] = mode
                    self.keyslot_allocs += 1
                    status = "KEYSLOT_ALLOCATED"
                    break
                    
        if not target_slot:
            evictable = [s for s in self.slots if s["refcount"] == 0]
            if evictable:
                evictable.sort(key=lambda x: x["last_used_timestamp"])
                target_slot = evictable[0]
                target_slot["key_id"] = key_id
                target_slot["crypto_mode"] = mode
                self.keyslot_evictions += 1
                status = "KEYSLOT_EVICTED_LRU"
                
        if target_slot:
            target_slot["refcount"] += 1
            target_slot["last_used_timestamp"] = timestamp
            allocated_mode = "HW_KEYSLOT"
            slot_id = target_slot["slot_id"]
        else:
            if self.sw_fallback_enabled:
                self.fallback_sw_crypt += 1
                allocated_mode = "SW_FALLBACK"
                slot_id = None
                status = "FALLBACK_SW_CRYPT"
            else:
                return {
                    "op": "SUBMIT_BIO_CRYPT",
                    "bio_id": bio_id,
                    "status": "KEYSLOTS_BUSY_EBUSY"
                }

        self.active_bios[bio_id] = {
            "bio_id": bio_id,
            "slot_id": slot_id,
            "key_id": key_id,
            "mode": allocated_mode,
            "dun": dun,
            "byte_len": byte_len
        }

        return {
            "op": "SUBMIT_BIO_CRYPT",
            "bio_id": bio_id,
            "mode": allocated_mode,
            "slot_id": slot_id,
            "dun": dun,
            "status": status
        }

    def _complete_bio_crypt(self, cmd):
        bio_id = cmd["bio_id"]
        if bio_id not in self.active_bios:
            return {"op": "COMPLETE_BIO_CRYPT", "bio_id": bio_id, "status": "NOT_FOUND"}
            
        bio = self.active_bios.pop(bio_id)
        if bio["mode"] == "HW_KEYSLOT":
            slot = self.slots[bio["slot_id"]]
            slot["refcount"] = max(0, slot["refcount"] - 1)
            status = "HW_KEYSLOT_RELEASED"
            remaining_refcount = slot["refcount"]
        else:
            status = "SW_FALLBACK_RELEASED"
            remaining_refcount = 0

        return {
            "op": "COMPLETE_BIO_CRYPT",
            "bio_id": bio_id,
            "slot_id": bio["slot_id"],
            "remaining_refcount": remaining_refcount,
            "status": status
        }

    def _evict_key_explicit(self, cmd):
        key_id = cmd["key_id"]
        wiped_slots = []
        for s in self.slots:
            if s["key_id"] == key_id:
                if s["refcount"] == 0:
                    s["key_id"] = None
                    s["crypto_mode"] = None
                    wiped_slots.append(s["slot_id"])
                else:
                    return {
                        "op": "EVICT_KEY_EXPLICIT",
                        "key_id": key_id,
                        "slot_id": s["slot_id"],
                        "status": "KEY_STILL_IN_USE"
                    }
        if wiped_slots:
            return {
                "op": "EVICT_KEY_EXPLICIT",
                "key_id": key_id,
                "wiped_slots": wiped_slots,
                "status": "KEY_WIPED_FROM_KEYSLOT"
            }
        else:
            return {
                "op": "EVICT_KEY_EXPLICIT",
                "key_id": key_id,
                "status": "KEY_NOT_PROGRAMMED"
            }

    def _get_stats(self, cmd):
        slots_summary = []
        for s in self.slots:
            slots_summary.append({
                "slot_id": s["slot_id"],
                "key_id": s["key_id"],
                "refcount": s["refcount"],
                "last_used_timestamp": s["last_used_timestamp"]
            })
        return {
            "op": "GET_STATS",
            "keyslot_hits": self.keyslot_hits,
            "keyslot_allocs": self.keyslot_allocs,
            "keyslot_evictions": self.keyslot_evictions,
            "fallback_sw_crypt": self.fallback_sw_crypt,
            "total_bios_processed": self.total_bios_processed,
            "total_bytes_encrypted": self.total_bytes_encrypted,
            "slots": slots_summary
        }

    def run_trace(self, trace):
        results = []
        for cmd in trace:
            res = self.execute_command(cmd)
            results.append(res)
            
        summary = {
            "keyslot_hits": self.keyslot_hits,
            "keyslot_allocs": self.keyslot_allocs,
            "keyslot_evictions": self.keyslot_evictions,
            "fallback_sw_crypt": self.fallback_sw_crypt,
            "total_bios_processed": self.total_bios_processed,
            "total_bytes_encrypted": self.total_bytes_encrypted,
            "active_bios_in_flight": len(self.active_bios)
        }
        return {"events": results, "summary": summary}


def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    trace = data.get("trace", [])
    
    engine = BlkCryptoEngine(config)
    output = engine.run_trace(trace)
    print(json.dumps(output, separators=(',', ':'), ensure_ascii=False))


if __name__ == "__main__":
    solve()
