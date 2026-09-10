# -*- coding: utf-8 -*-
"""
ZeliJudge Pro Track Problem #379: Linux Kernel Memory: ZRAM Compressed In-RAM Swap Device Engine
Canonical Solution Implementation
"""
import sys
import json
import math

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class ZSmallocPool:
    def __init__(self, step=32, max_zspage_pages=4, mem_limit_bytes=1048576):
        self.step = step
        self.max_zspage_pages = max_zspage_pages
        self.mem_limit_bytes = mem_limit_bytes
        self.size_classes = list(range(step, 4096 + step, step))
        self.classes = {}
        self.total_physical_mem = 0
        self.next_zspage_id = 1
        self.pages_compacted = 0
        
        for c in self.size_classes:
            best_p = 1
            min_waste = 4096 % c
            for p in range(1, max_zspage_pages + 1):
                waste = (p * 4096) % c
                if waste < min_waste:
                    min_waste = waste
                    best_p = p
            cap = (best_p * 4096) // c
            self.classes[c] = {
                "class_size": c,
                "pages_per_zspage": best_p,
                "capacity": cap,
                "zspages": []
            }

    def _get_class(self, size):
        c = int(math.ceil(size / self.step)) * self.step
        return min(c, 4096)

    def allocate(self, comp_size):
        c = self._get_class(comp_size)
        cls_info = self.classes[c]
        
        target_zp = None
        for zp in cls_info["zspages"]:
            cap = zp["capacity"]
            u = len(zp["slots"])
            if (cap // 3) < u < cap:
                target_zp = zp
                break
        
        if not target_zp:
            for zp in cls_info["zspages"]:
                cap = zp["capacity"]
                u = len(zp["slots"])
                if 0 < u <= (cap // 3):
                    target_zp = zp
                    break
                    
        if not target_zp:
            for zp in cls_info["zspages"]:
                if len(zp["slots"]) == 0:
                    target_zp = zp
                    break

        if not target_zp:
            needed_bytes = cls_info["pages_per_zspage"] * 4096
            if self.total_physical_mem + needed_bytes > self.mem_limit_bytes:
                return None, "ENOMEM"
            target_zp = {
                "id": self.next_zspage_id,
                "class_size": c,
                "pages": cls_info["pages_per_zspage"],
                "capacity": cls_info["capacity"],
                "slots": {}
            }
            self.next_zspage_id += 1
            self.total_physical_mem += needed_bytes
            cls_info["zspages"].append(target_zp)

        used_slots = set(target_zp["slots"].keys())
        allocated_slot = None
        for s in range(target_zp["capacity"]):
            if s not in used_slots:
                allocated_slot = s
                break
        
        handle = (c, target_zp["id"], allocated_slot)
        target_zp["slots"][allocated_slot] = comp_size
        return handle, "SUCCESS"

    def free(self, handle):
        if not handle:
            return
        c, zp_id, slot = handle
        cls_info = self.classes[c]
        for zp in cls_info["zspages"]:
            if zp["id"] == zp_id:
                if slot in zp["slots"]:
                    del zp["slots"][slot]
                break

    def compact(self):
        reclaimed_physical_pages = 0
        for c in self.size_classes:
            cls_info = self.classes[c]
            remaining = []
            for zp in cls_info["zspages"]:
                if len(zp["slots"]) == 0:
                    self.total_physical_mem -= zp["pages"] * 4096
                    reclaimed_physical_pages += zp["pages"]
                else:
                    remaining.append(zp)
            cls_info["zspages"] = remaining

            while True:
                non_full = [zp for zp in cls_info["zspages"] if len(zp["slots"]) < zp["capacity"]]
                if len(non_full) <= 1:
                    break
                non_full.sort(key=lambda zp: (len(zp["slots"]), zp["id"]))
                donor = non_full[0]
                receivers = [zp for zp in non_full if zp["id"] != donor["id"]]
                receivers.sort(key=lambda zp: (-len(zp["slots"]), zp["id"]))
                receiver = receivers[0]

                free_space_in_recv = receiver["capacity"] - len(receiver["slots"])
                if free_space_in_recv <= 0:
                    break

                donor_slots = list(donor["slots"].keys())
                if len(donor_slots) <= free_space_in_recv:
                    for s in donor_slots:
                        comp_size = donor["slots"].pop(s)
                        recv_used = set(receiver["slots"].keys())
                        for rs in range(receiver["capacity"]):
                            if rs not in recv_used:
                                receiver["slots"][rs] = comp_size
                                break
                    cls_info["zspages"].remove(donor)
                    self.total_physical_mem -= donor["pages"] * 4096
                    reclaimed_physical_pages += donor["pages"]
                else:
                    break

        self.pages_compacted += reclaimed_physical_pages
        return reclaimed_physical_pages


class ZRAMDevice:
    def __init__(self, config):
        self.num_pages = config.get("num_pages", 1024)
        self.mem_limit_bytes = config.get("mem_limit_bytes", 1048576)
        self.comp_algorithm = config.get("comp_algorithm", "lz4")
        self.zsmalloc = ZSmallocPool(
            step=config.get("zsmalloc", {}).get("class_step_bytes", 32),
            max_zspage_pages=config.get("zsmalloc", {}).get("max_zspage_pages", 4),
            mem_limit_bytes=self.mem_limit_bytes
        )
        self.backing_cfg = config.get("backing_device", {"enabled": False, "capacity_pages": 0})
        self.backing_enabled = self.backing_cfg.get("enabled", False)
        self.backing_capacity = self.backing_cfg.get("capacity_pages", 0)
        
        self.table = {}
        self.backing_dev_pages = {}
        self.pages_written_back = 0
        self.history = []

    def execute_operation(self, op):
        cmd = op["op"]
        ts = op.get("timestamp", 0)
        
        if cmd == "WRITE":
            page_idx = op["page_idx"]
            if page_idx < 0 or page_idx >= self.num_pages:
                self.history.append({"op": cmd, "page_idx": page_idx, "status": "ERR_INVALID_PAGE", "detail": f"page_idx {page_idx} out of range [0, {self.num_pages})"})
                return

            if page_idx in self.table:
                self._free_page(page_idx)

            content_type = op.get("content_type", "DATA")
            if content_type == "ZERO":
                self.table[page_idx] = {
                    "type": "SAME",
                    "same_val": 0,
                    "comp_len": 0,
                    "handle": None,
                    "flags": set(),
                    "last_access_ts": ts,
                    "in_backing_dev": False
                }
                self.history.append({"op": cmd, "page_idx": page_idx, "status": "SUCCESS", "detail": "same-page zero deduplicated (0 bytes RAM)"})
            elif content_type == "PATTERN":
                pval = op.get("pattern_val", 0)
                self.table[page_idx] = {
                    "type": "SAME",
                    "same_val": pval,
                    "comp_len": 0,
                    "handle": None,
                    "flags": set(),
                    "last_access_ts": ts,
                    "in_backing_dev": False
                }
                self.history.append({"op": cmd, "page_idx": page_idx, "status": "SUCCESS", "detail": f"same-page pattern 0x{pval:08x} deduplicated (0 bytes RAM)"})
            else: # DATA
                comp_len = op.get("comp_bytes", None)
                if comp_len is None:
                    ratio = op.get("comp_ratio", 0.5)
                    comp_len = int(math.ceil(4096 * ratio))
                comp_len = max(1, min(4096, comp_len))

                is_huge = (comp_len >= 4096 - 64)
                alloc_len = 4096 if is_huge else comp_len
                
                handle, alloc_status = self.zsmalloc.allocate(alloc_len)
                if not handle:
                    self.history.append({"op": cmd, "page_idx": page_idx, "status": "ERR_ENOMEM", "detail": f"mem_limit {self.mem_limit_bytes} exceeded while allocating {alloc_len} bytes"})
                    return
                
                flags = set()
                if is_huge:
                    flags.add("HUGE")

                self.table[page_idx] = {
                    "type": "HUGE" if is_huge else "COMPR",
                    "same_val": None,
                    "comp_len": alloc_len,
                    "handle": handle,
                    "flags": flags,
                    "last_access_ts": ts,
                    "in_backing_dev": False
                }
                self.history.append({
                    "op": cmd,
                    "page_idx": page_idx,
                    "status": "SUCCESS",
                    "detail": f"{'huge ' if is_huge else ''}compressed {alloc_len} bytes stored in zsmalloc class {self.zsmalloc._get_class(alloc_len)}"
                })

        elif cmd == "READ":
            page_idx = op["page_idx"]
            if page_idx not in self.table:
                self.history.append({"op": cmd, "page_idx": page_idx, "status": "PAGE_FAULT_EMPTY", "detail": f"page {page_idx} is unallocated (returns zero-filled page)"})
                return
            entry = self.table[page_idx]
            entry["last_access_ts"] = ts
            entry["flags"].discard("IDLE")
            where = "backing_dev" if entry["in_backing_dev"] else "ram"
            self.history.append({"op": cmd, "page_idx": page_idx, "status": "SUCCESS", "detail": f"read page from {where} (type={entry['type']}, comp_len={entry['comp_len']})"})

        elif cmd == "DISCARD":
            page_idx = op["page_idx"]
            if page_idx in self.table:
                self._free_page(page_idx)
                self.history.append({"op": cmd, "page_idx": page_idx, "status": "SUCCESS", "detail": f"discarded and reclaimed page {page_idx}"})
            else:
                self.history.append({"op": cmd, "page_idx": page_idx, "status": "NOOP", "detail": f"page {page_idx} not present"})

        elif cmd == "SET_IDLE":
            thresh = op.get("idle_age_threshold", 60)
            idle_count = 0
            for p_idx, entry in sorted(self.table.items()):
                if not entry["in_backing_dev"]:
                    if (ts - entry["last_access_ts"]) >= thresh:
                        entry["flags"].add("IDLE")
                        idle_count += 1
            self.history.append({"op": cmd, "status": "SUCCESS", "detail": f"marked {idle_count} pages as IDLE (age >= {thresh})"})

        elif cmd == "WRITEBACK":
            wb_type = op.get("type", "IDLE")
            if not self.backing_enabled:
                self.history.append({"op": cmd, "status": "ERR_NO_BACKING_DEV", "detail": "backing device not configured"})
                return
            
            evicted = 0
            for p_idx in sorted(self.table.keys()):
                if len(self.backing_dev_pages) >= self.backing_capacity:
                    break
                entry = self.table[p_idx]
                if entry["in_backing_dev"]:
                    continue
                if entry["type"] == "SAME":
                    continue
                
                eligible = False
                if wb_type == "ALL":
                    eligible = True
                elif wb_type == "IDLE" and "IDLE" in entry["flags"]:
                    eligible = True
                elif wb_type == "HUGE" and "HUGE" in entry["flags"]:
                    eligible = True
                
                if eligible:
                    if entry["handle"]:
                        self.zsmalloc.free(entry["handle"])
                        entry["handle"] = None
                    entry["in_backing_dev"] = True
                    entry["flags"].discard("IDLE")
                    entry["flags"].discard("HUGE")
                    entry["flags"].add("WB")
                    self.backing_dev_pages[p_idx] = True
                    self.pages_written_back += 1
                    evicted += 1
            
            self.history.append({"op": cmd, "status": "SUCCESS", "detail": f"evicted {evicted} pages to backing device (type={wb_type})"})

        elif cmd == "COMPACT":
            reclaimed = self.zsmalloc.compact()
            self.history.append({"op": cmd, "status": "SUCCESS", "detail": f"compaction reclaimed {reclaimed} physical pages ({reclaimed * 4096} bytes)"})

    def _free_page(self, page_idx):
        entry = self.table[page_idx]
        if entry["handle"]:
            self.zsmalloc.free(entry["handle"])
        if entry["in_backing_dev"]:
            if page_idx in self.backing_dev_pages:
                del self.backing_dev_pages[page_idx]
        del self.table[page_idx]

    def get_summary(self):
        total_pages = len(self.table)
        pages_ram = sum(1 for e in self.table.values() if not e["in_backing_dev"])
        pages_bd = sum(1 for e in self.table.values() if e["in_backing_dev"])
        same_pages = sum(1 for e in self.table.values() if e["type"] == "SAME")
        huge_pages = sum(1 for e in self.table.values() if "HUGE" in e["flags"] or (e["type"] == "HUGE" and not e["in_backing_dev"]))
        
        orig_data_size = total_pages * 4096
        compr_data_size = sum(e["comp_len"] for e in self.table.values() if not e["in_backing_dev"])
        mem_used_total = self.zsmalloc.total_physical_mem

        eff_ratio = round(mem_used_total / (pages_ram * 4096), 4) if pages_ram > 0 else 0.0
        savings = orig_data_size - mem_used_total

        return {
            "total_pages_stored": total_pages,
            "pages_in_ram": pages_ram,
            "pages_in_backing_dev": pages_bd,
            "same_pages": same_pages,
            "huge_pages": huge_pages,
            "orig_data_size_bytes": orig_data_size,
            "compr_data_size_bytes": compr_data_size,
            "mem_used_total_bytes": mem_used_total,
            "memory_savings_bytes": savings,
            "effective_ram_ratio": eff_ratio,
            "pages_compacted_total": self.zsmalloc.pages_compacted,
            "pages_written_back_total": self.pages_written_back
        }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    dev = ZRAMDevice(data["config"])
    for op in data["operations"]:
        dev.execute_operation(op)
    result = {
        "history": dev.history,
        "summary": dev.get_summary()
    }
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
