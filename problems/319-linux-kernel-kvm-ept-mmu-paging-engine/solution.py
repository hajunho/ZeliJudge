import sys
import os
import json

PAGE_SHIFT = 12
PAGE_SIZE = 1 << PAGE_SHIFT # 4096

class KVMEPTEngine:
    def __init__(self, config: dict):
        self.memslots = {}
        for s in config.get("memslots", []):
            sid = s["slot_id"]
            self.memslots[sid] = {
                "slot_id": sid,
                "base_gfn": s["base_gfn"],
                "npages": s["npages"],
                "base_hfn": s.get("base_hfn", s["base_gfn"] + 0x10000),
                "supports_huge_pages": s.get("supports_huge_pages", True),
                "dirty_logging": s.get("dirty_logging", False),
                "dirty_bitmap": set()
            }

        self.ept_table = {}
        self.event_log = []
        self.history = []
        self.stats = {
            "ept_violations": 0,
            "fast_dirty_logged": 0,
            "slow_path_mapped": 0,
            "huge_pages_mapped": 0,
            "mmio_exits": 0,
            "tlb_invept_count": 0
        }

    def log(self, msg: str):
        self.event_log.append(msg)

    def find_memslot(self, gfn: int):
        for s in self.memslots.values():
            if s["base_gfn"] <= gfn < s["base_gfn"] + s["npages"]:
                return s
        return None

    def enable_dirty_logging(self, slot_id: int):
        if slot_id in self.memslots:
            slot = self.memslots[slot_id]
            slot["dirty_logging"] = True
            slot["dirty_bitmap"].clear()
            count = 0
            for gfn, entry in self.ept_table.items():
                if slot["base_gfn"] <= gfn < slot["base_gfn"] + slot["npages"]:
                    entry["w"] = False
                    count += 1
            self.log(f"DIRTY_LOGGING_ENABLED slot={slot_id} write_protected_pages={count}")

    def get_dirty_bitmap(self, slot_id: int) -> list:
        if slot_id in self.memslots:
            slot = self.memslots[slot_id]
            dirty_list = sorted(list(slot["dirty_bitmap"]))
            slot["dirty_bitmap"].clear()
            for gfn in dirty_list:
                if gfn in self.ept_table:
                    self.ept_table[gfn]["w"] = False
            self.log(f"DIRTY_BITMAP_RETRIEVED slot={slot_id} count={len(dirty_list)}")
            return dirty_list
        return []

    def invept(self, invept_type: str = "ALL_CONTEXT"):
        self.stats["tlb_invept_count"] += 1
        self.log(f"INVEPT_EXECUTED type={invept_type}")

    def access_gpa(self, vcpu_id: int, gpa: int, access_type: str) -> dict:
        gfn = gpa >> PAGE_SHIFT
        offset = gpa & (PAGE_SIZE - 1)
        access_type = access_type.upper()

        entry = self.ept_table.get(gfn)

        if entry:
            can_read = entry["r"]
            can_write = entry["w"]
            can_exec = entry["x"]

            allowed = False
            if access_type == "READ" and can_read:
                allowed = True
            elif access_type == "WRITE" and can_write:
                allowed = True
            elif access_type == "EXEC" and can_exec:
                allowed = True

            if allowed:
                hpa = (entry["hfn"] << PAGE_SHIFT) + offset
                res = {
                    "op": "ACCESS_GPA",
                    "vcpu_id": vcpu_id,
                    "gpa": gpa,
                    "access_type": access_type,
                    "status": "EPT_HIT",
                    "hpa": hpa
                }
                self.history.append(res)
                return res

            slot = self.find_memslot(gfn)
            if access_type == "WRITE" and not can_write and slot and slot["dirty_logging"]:
                slot["dirty_bitmap"].add(gfn)
                entry["w"] = True
                entry["dirty"] = True
                self.stats["fast_dirty_logged"] += 1
                self.stats["ept_violations"] += 1
                hpa = (entry["hfn"] << PAGE_SHIFT) + offset
                self.log(f"FAST_PATH_DIRTY_LOGGED vcpu={vcpu_id} gfn={gfn} hpa={hpa}")
                res = {
                    "op": "ACCESS_GPA",
                    "vcpu_id": vcpu_id,
                    "gpa": gpa,
                    "access_type": access_type,
                    "status": "FAST_DIRTY_LOGGED",
                    "hpa": hpa
                }
                self.history.append(res)
                return res

        self.stats["ept_violations"] += 1
        slot = self.find_memslot(gfn)
        if not slot:
            self.stats["mmio_exits"] += 1
            self.log(f"MMIO_EXIT vcpu={vcpu_id} gpa={gpa}")
            res = {
                "op": "ACCESS_GPA",
                "vcpu_id": vcpu_id,
                "gpa": gpa,
                "access_type": access_type,
                "status": "MMIO_EMULATION"
            }
            self.history.append(res)
            return res

        self.stats["slow_path_mapped"] += 1
        hfn = slot["base_hfn"] + (gfn - slot["base_gfn"])
        huge_page = False

        if slot["supports_huge_pages"] and (gfn % 512 == 0) and (hfn % 512 == 0) and (slot["npages"] >= 512):
            huge_page = True
            self.stats["huge_pages_mapped"] += 1

        is_write = (access_type == "WRITE")
        can_write = False if slot["dirty_logging"] else True
        if slot["dirty_logging"] and is_write:
            slot["dirty_bitmap"].add(gfn)
            can_write = True

        new_entry = {
            "gfn": gfn,
            "hfn": hfn,
            "r": True,
            "w": can_write,
            "x": True,
            "huge_page": huge_page,
            "dirty": is_write
        }
        self.ept_table[gfn] = new_entry
        hpa = (hfn << PAGE_SHIFT) + offset
        status = "HUGE_PAGE_MAPPED" if huge_page else "PAGE_MAPPED"
        self.log(f"EPT_MAPPED vcpu={vcpu_id} gfn={gfn} hfn={hfn} huge={huge_page} w={can_write}")

        res = {
            "op": "ACCESS_GPA",
            "vcpu_id": vcpu_id,
            "gpa": gpa,
            "access_type": access_type,
            "status": status,
            "hpa": hpa
        }
        self.history.append(res)
        return res

def run_simulation(input_data: dict) -> dict:
    config = input_data.get("config", {})
    operations = input_data.get("operations", [])

    engine = KVMEPTEngine(config)
    dirty_bitmaps = {}

    for op_info in operations:
        op = op_info.get("op")
        if op == "ACCESS_GPA":
            vcpu = op_info.get("vcpu_id", 0)
            gpa = op_info.get("gpa", 0)
            atype = op_info.get("access_type", "READ")
            engine.access_gpa(vcpu, gpa, atype)
        elif op == "ENABLE_DIRTY_LOGGING":
            sid = op_info.get("slot_id", 0)
            engine.enable_dirty_logging(sid)
        elif op == "GET_DIRTY_BITMAP":
            sid = op_info.get("slot_id", 0)
            dirty_bitmaps[str(sid)] = engine.get_dirty_bitmap(sid)
        elif op == "INVEPT":
            itype = op_info.get("type", "ALL_CONTEXT")
            engine.invept(itype)

    ept_dump = {}
    for gfn in sorted(engine.ept_table.keys()):
        e = engine.ept_table[gfn]
        ept_dump[str(gfn)] = {
            "hfn": e["hfn"],
            "r": e["r"],
            "w": e["w"],
            "x": e["x"],
            "huge_page": e["huge_page"],
            "dirty": e["dirty"]
        }

    return {
        "stats": engine.stats,
        "ept_table": ept_dump,
        "dirty_bitmaps": dirty_bitmaps,
        "history": engine.history,
        "event_log": engine.event_log
    }

if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            sys.stdin.reconfigure(encoding="utf-8")
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    input_text = sys.stdin.read().strip()
    if not input_text:
        sys.exit(0)

    data = json.loads(input_text)
    result = run_simulation(data)
    print(json.dumps(result, ensure_ascii=False))
