# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #398 Solution:
Linux Kernel Memory Management: ZSWAP Compressed Cache & LRU Writeback Eviction Engine
"""
import sys
import json
import zlib

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PAGE_SIZE = 4096

class ZswapEntry:
    def __init__(self, page_id, raw_data_hex, comp_bytes, same_filled=False, same_byte=None):
        self.page_id = str(page_id)
        self.raw_data_hex = raw_data_hex
        self.comp_bytes = int(comp_bytes)
        self.same_filled = bool(same_filled)
        self.same_byte = same_byte
        self.last_access_tick = 0

    def to_dict(self):
        return {
            "page_id": self.page_id,
            "comp_bytes": self.comp_bytes,
            "same_filled": self.same_filled,
            "same_byte": self.same_byte
        }

class ZswapEngine:
    def __init__(self, config):
        self.max_pool_bytes = int(config.get("max_pool_bytes", 16384))
        self.max_compression_ratio = float(config.get("max_compression_ratio", 0.80))
        self.current_pool_bytes = 0
        self.current_tick = 0

        self.entries = {}
        self.lru_list = []
        self.disk_swap = {}

        self.stats = {
            "stored_pages": 0,
            "same_filled_pages": 0,
            "rejected_poor_compression": 0,
            "rejected_pool_full": 0,
            "written_back_to_disk": 0,
            "zswap_hits": 0,
            "disk_hits": 0,
            "reclaimed_pool_bytes": 0
        }
        self.event_log = []

    def touch_lru(self, page_id):
        if page_id in self.lru_list:
            self.lru_list.remove(page_id)
        self.lru_list.append(page_id)
        if page_id in self.entries:
            self.entries[page_id].last_access_tick = self.current_tick

    def evict_one_to_disk(self):
        if not self.lru_list:
            return False

        coldest_id = self.lru_list.pop(0)
        entry = self.entries.pop(coldest_id)

        self.disk_swap[coldest_id] = entry.raw_data_hex
        self.current_pool_bytes -= entry.comp_bytes
        self.stats["written_back_to_disk"] += 1
        self.stats["stored_pages"] -= 1
        self.stats["reclaimed_pool_bytes"] += entry.comp_bytes

        self.event_log.append({
            "tick": self.current_tick,
            "action": "WRITEBACK_TO_DISK",
            "page_id": coldest_id,
            "freed_bytes": entry.comp_bytes
        })
        return True

    def store_page(self, page_id, raw_data_hex):
        self.current_tick += 1
        raw_bytes = bytes.fromhex(raw_data_hex) if len(raw_data_hex) > 0 else b""
        if len(raw_bytes) < PAGE_SIZE:
            raw_bytes = raw_bytes + b"\x00" * (PAGE_SIZE - len(raw_bytes))

        first_b = raw_bytes[0]
        if all(b == first_b for b in raw_bytes):
            entry = ZswapEntry(page_id, raw_data_hex, comp_bytes=0, same_filled=True, same_byte=f"0x{first_b:02x}")
            self.entries[page_id] = entry
            self.touch_lru(page_id)
            self.stats["stored_pages"] += 1
            self.stats["same_filled_pages"] += 1
            self.event_log.append({
                "tick": self.current_tick,
                "action": "STORE_SAME_FILLED",
                "page_id": page_id,
                "same_byte": f"0x{first_b:02x}"
            })
            return {"status": "SUCCESS_SAME_FILLED"}

        comp = zlib.compress(raw_bytes, level=6)
        comp_len = len(comp)

        if comp_len > int(PAGE_SIZE * self.max_compression_ratio):
            self.disk_swap[page_id] = raw_data_hex
            self.stats["rejected_poor_compression"] += 1
            self.event_log.append({
                "tick": self.current_tick,
                "action": "REJECT_POOR_COMPRESSION",
                "page_id": page_id,
                "comp_len": comp_len,
                "threshold": int(PAGE_SIZE * self.max_compression_ratio)
            })
            return {"status": "REJECT_POOR_COMPRESSION", "comp_len": comp_len}

        while (self.current_pool_bytes + comp_len) > self.max_pool_bytes:
            success = self.evict_one_to_disk()
            if not success:
                self.disk_swap[page_id] = raw_data_hex
                self.stats["rejected_pool_full"] += 1
                return {"status": "REJECT_POOL_FULL"}

        entry = ZswapEntry(page_id, raw_data_hex, comp_bytes=comp_len, same_filled=False)
        self.entries[page_id] = entry
        self.current_pool_bytes += comp_len
        self.touch_lru(page_id)
        self.stats["stored_pages"] += 1
        self.event_log.append({
            "tick": self.current_tick,
            "action": "STORE_COMPRESSED",
            "page_id": page_id,
            "comp_bytes": comp_len,
            "pool_used": self.current_pool_bytes
        })
        return {"status": "SUCCESS_STORED", "comp_bytes": comp_len}

    def load_page(self, page_id):
        self.current_tick += 1
        if page_id in self.entries:
            entry = self.entries[page_id]
            self.stats["zswap_hits"] += 1
            self.touch_lru(page_id)
            self.event_log.append({
                "tick": self.current_tick,
                "action": "LOAD_ZSWAP_HIT",
                "page_id": page_id
            })
            return {"status": "ZSWAP_HIT", "data": entry.raw_data_hex}

        if page_id in self.disk_swap:
            data = self.disk_swap[page_id]
            self.stats["disk_hits"] += 1
            self.event_log.append({
                "tick": self.current_tick,
                "action": "LOAD_DISK_HIT",
                "page_id": page_id
            })
            return {"status": "DISK_HIT", "data": data}

        return {"status": "NOT_FOUND"}

    def run_simulation(self, operations):
        for op in operations:
            act = op["action"]
            if act == "STORE":
                self.store_page(op["page_id"], op.get("data_hex", ""))
            elif act == "LOAD":
                self.load_page(op["page_id"])

        return self.get_summary()

    def get_summary(self):
        pool_compression_ratio = round(self.current_pool_bytes / (self.stats["stored_pages"] * PAGE_SIZE), 4) if self.stats["stored_pages"] > 0 else 0.0
        return {
            "current_pool_bytes": self.current_pool_bytes,
            "max_pool_bytes": self.max_pool_bytes,
            "pool_compression_ratio": pool_compression_ratio,
            "stats": self.stats,
            "stored_in_zswap": list(self.entries.keys()),
            "stored_on_disk": list(self.disk_swap.keys()),
            "lru_order": list(self.lru_list),
            "event_log_sample": self.event_log[-8:]
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    operations = data.get("operations", [])
    engine = ZswapEngine(config)
    res = engine.run_simulation(operations)
    print(json.dumps(res, separators=(",", ":"), ensure_ascii=False))

if __name__ == "__main__":
    main()
