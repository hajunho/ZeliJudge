import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class PageCacheFolioEngine:
    PAGE_SIZE = 4096

    def __init__(self, config: dict):
        self.max_cache_pages = config.get("max_cache_pages", 1024)
        self.default_readahead_order = config.get("default_readahead_order", 2)
        self.max_folio_order = config.get("max_folio_order", 4)

        self.xarray = {}
        self.folios = []

        self.stats = {
            "read_requests": 0,
            "write_requests": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "folios_allocated": 0,
            "folios_split": 0,
            "folios_truncated": 0,
            "xarray_lookup_traversals": 0,
            "lock_cycles": 0,
            "bytes_read": 0,
            "bytes_written": 0,
            "dirty_folios": 0
        }

    def _allocate_folio(self, start_index: int, order: int) -> dict:
        num_pages = 1 << order
        aligned_index = (start_index // num_pages) * num_pages
        folio = {
            "id": len(self.folios) + 1,
            "start_index": aligned_index,
            "order": order,
            "num_pages": num_pages,
            "size_bytes": num_pages * self.PAGE_SIZE,
            "flags": {"UPTODATE": False, "DIRTY": False, "LOCKED": False, "WRITEBACK": False},
            "data": bytearray(num_pages * self.PAGE_SIZE)
        }
        self.folios.append(folio)
        self.stats["folios_allocated"] += 1
        for p in range(aligned_index, aligned_index + num_pages):
            self.xarray[p] = folio
        return folio

    def read(self, offset: int, length: int, sequential_hint: bool = True) -> dict:
        self.stats["read_requests"] += 1
        self.stats["bytes_read"] += length

        start_page = offset // self.PAGE_SIZE
        end_page = (offset + length - 1) // self.PAGE_SIZE

        curr_page = start_page
        accessed_folios = set()

        while curr_page <= end_page:
            self.stats["xarray_lookup_traversals"] += 1
            folio = self.xarray.get(curr_page)

            if folio is None:
                self.stats["cache_misses"] += 1
                order = self.default_readahead_order if sequential_hint else 0
                order = min(order, self.max_folio_order)
                folio = self._allocate_folio(curr_page, order)
                folio["flags"]["UPTODATE"] = True
            else:
                self.stats["cache_hits"] += 1

            if folio["id"] not in accessed_folios:
                self.stats["lock_cycles"] += 1
                accessed_folios.add(folio["id"])

            curr_page = folio["start_index"] + folio["num_pages"]

        return {
            "status": "OK",
            "start_page": start_page,
            "end_page": end_page,
            "folios_touched": len(accessed_folios)
        }

    def write(self, offset: int, data_hex: str) -> dict:
        data = bytes.fromhex(data_hex)
        length = len(data)
        self.stats["write_requests"] += 1
        self.stats["bytes_written"] += length

        start_page = offset // self.PAGE_SIZE
        end_page = (offset + length - 1) // self.PAGE_SIZE

        curr_page = start_page
        accessed_folios = set()

        while curr_page <= end_page:
            self.stats["xarray_lookup_traversals"] += 1
            folio = self.xarray.get(curr_page)
            if folio is None:
                self.stats["cache_misses"] += 1
                folio = self._allocate_folio(curr_page, self.default_readahead_order)
                folio["flags"]["UPTODATE"] = True
            else:
                self.stats["cache_hits"] += 1

            if not folio["flags"]["DIRTY"]:
                folio["flags"]["DIRTY"] = True
                self.stats["dirty_folios"] += 1

            if folio["id"] not in accessed_folios:
                self.stats["lock_cycles"] += 1
                accessed_folios.add(folio["id"])

            f_offset = max(0, offset - (folio["start_index"] * self.PAGE_SIZE))
            f_end = min(folio["size_bytes"], offset + length - (folio["start_index"] * self.PAGE_SIZE))
            data_start = max(0, (folio["start_index"] * self.PAGE_SIZE) - offset)
            slice_len = f_end - f_offset
            if slice_len > 0:
                folio["data"][f_offset:f_end] = data[data_start:data_start + slice_len]

            curr_page = folio["start_index"] + folio["num_pages"]

        return {
            "status": "OK",
            "bytes_written": length,
            "folios_touched": len(accessed_folios)
        }

    def split_folio(self, page_index: int) -> dict:
        folio = self.xarray.get(page_index)
        if folio is None:
            return {"status": "ERROR", "reason": "FOLIO_NOT_FOUND"}
        if folio["order"] == 0:
            return {"status": "NOOP", "reason": "ALREADY_ORDER_0"}

        old_start = folio["start_index"]
        old_order = folio["order"]
        old_num_pages = folio["num_pages"]
        is_dirty = folio["flags"]["DIRTY"]

        self.folios.remove(folio)
        if is_dirty:
            self.stats["dirty_folios"] -= 1

        new_folios = []
        for i in range(old_num_pages):
            p_idx = old_start + i
            sub_folio = {
                "id": len(self.folios) + 1,
                "start_index": p_idx,
                "order": 0,
                "num_pages": 1,
                "size_bytes": self.PAGE_SIZE,
                "flags": {"UPTODATE": True, "DIRTY": is_dirty, "LOCKED": False, "WRITEBACK": False},
                "data": folio["data"][i * self.PAGE_SIZE:(i + 1) * self.PAGE_SIZE]
            }
            self.folios.append(sub_folio)
            self.xarray[p_idx] = sub_folio
            if is_dirty:
                self.stats["dirty_folios"] += 1
            new_folios.append(sub_folio["id"])

        self.stats["folios_split"] += 1
        return {
            "status": "SPLIT_OK",
            "original_folio_id": folio["id"],
            "original_order": old_order,
            "sub_folios_created": len(new_folios)
        }

    def flush_writeback(self) -> dict:
        flushed_count = 0
        for f in self.folios:
            if f["flags"]["DIRTY"]:
                f["flags"]["WRITEBACK"] = True
                f["flags"]["DIRTY"] = False
                f["flags"]["WRITEBACK"] = False
                flushed_count += 1
        self.stats["dirty_folios"] = 0
        return {"status": "FLUSHED", "flushed_count": flushed_count}

    def truncate(self, new_size: int) -> dict:
        new_end_page = (new_size + self.PAGE_SIZE - 1) // self.PAGE_SIZE
        truncated_folios = 0

        to_remove = []
        for f in list(self.folios):
            if f["start_index"] >= new_end_page:
                to_remove.append(f)
            elif f["start_index"] + f["num_pages"] > new_end_page:
                self.split_folio(f["start_index"])

        for f in list(self.folios):
            if f["start_index"] >= new_end_page:
                if f["flags"]["DIRTY"]:
                    self.stats["dirty_folios"] -= 1
                for p in range(f["start_index"], f["start_index"] + f["num_pages"]):
                    self.xarray.pop(p, None)
                self.folios.remove(f)
                truncated_folios += 1

        self.stats["folios_truncated"] += truncated_folios
        return {"status": "TRUNCATED", "new_size": new_size, "truncated_folios": truncated_folios}

    def get_summary(self) -> dict:
        total_accesses = self.stats["cache_hits"] + self.stats["cache_misses"]
        hit_ratio = round(self.stats["cache_hits"] / total_accesses, 4) if total_accesses > 0 else 0.0

        total_pages = sum(f["num_pages"] for f in self.folios)
        total_folios = len(self.folios)
        metadata_savings_pct = round((1.0 - (total_folios / total_pages)) * 100.0, 2) if total_pages > 0 else 0.0

        return {
            "stats": self.stats,
            "hit_ratio": hit_ratio,
            "active_folios_count": total_folios,
            "cached_pages_count": total_pages,
            "metadata_savings_pct": metadata_savings_pct,
            "folios_detail": [
                {
                    "id": f["id"],
                    "start_index": f["start_index"],
                    "order": f["order"],
                    "num_pages": f["num_pages"],
                    "is_dirty": f["flags"]["DIRTY"]
                }
                for f in sorted(self.folios, key=lambda x: x["start_index"])
            ]
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)
    config = input_data.get("config", {})
    operations = input_data.get("operations", [])

    engine = PageCacheFolioEngine(config)
    execution_log = []

    for op in operations:
        t = op.get("op")
        if t == "READ":
            res = engine.read(op.get("offset", 0), op.get("length", 4096), op.get("sequential_hint", True))
            execution_log.append({"op": t, "result": res})
        elif t == "WRITE":
            res = engine.write(op.get("offset", 0), op.get("data_hex", "00" * 8))
            execution_log.append({"op": t, "result": res})
        elif t == "SPLIT":
            res = engine.split_folio(op.get("page_index", 0))
            execution_log.append({"op": t, "result": res})
        elif t == "FLUSH":
            res = engine.flush_writeback()
            execution_log.append({"op": t, "result": res})
        elif t == "TRUNCATE":
            res = engine.truncate(op.get("new_size", 0))
            execution_log.append({"op": t, "result": res})

    output = {
        "execution_log": execution_log,
        "final_summary": engine.get_summary()
    }
    print(json.dumps(output, separators=(',', ':')))

if __name__ == "__main__":
    main()
