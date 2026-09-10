import sys
import json

# Windows 콘솔 UTF-8 입출력 호환성 보장
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

PAGE_SIZE = 4096

def determine_fullness(used: int, total: int) -> str:
    if used == 0:
        return "ZS_EMPTY"
    if used == total:
        return "ZS_FULL"
    ratio = used / total
    if ratio < 0.5:
        return "ZS_ALMOST_EMPTY"
    return "ZS_ALMOST_FULL"

class ZsPage:
    def __init__(self, zspage_id: int, class_size: int, pages_count: int):
        self.zspage_id = zspage_id
        self.class_size = class_size
        self.pages_count = pages_count
        self.total_slots = (pages_count * PAGE_SIZE) // class_size
        self.slots = [None] * self.total_slots
        self.fullness = "ZS_EMPTY"

    @property
    def used_count(self):
        return sum(1 for s in self.slots if s is not None)

    @property
    def free_count(self):
        return self.total_slots - self.used_count

    def update_fullness(self):
        self.fullness = determine_fullness(self.used_count, self.total_slots)
        return self.fullness

    def find_free_slot(self):
        for i, s in enumerate(self.slots):
            if s is None:
                return i
        return -1

class ZsSizeClass:
    def __init__(self, size: int, pages_per_zspage: int = 1):
        self.size = size
        self.pages_per_zspage = pages_per_zspage
        self.fullness_lists = {
            "ZS_ALMOST_FULL": [],
            "ZS_ALMOST_EMPTY": [],
            "ZS_FULL": [],
            "ZS_EMPTY": []
        }
        self.all_zspages = {}

    def add_zspage(self, zspage: ZsPage):
        self.all_zspages[zspage.zspage_id] = zspage
        zspage.update_fullness()
        self.fullness_lists[zspage.fullness].append(zspage)

    def move_zspage_fullness(self, zspage: ZsPage, old_fullness: str):
        if zspage in self.fullness_lists[old_fullness]:
            self.fullness_lists[old_fullness].remove(zspage)
        zspage.update_fullness()
        self.fullness_lists[zspage.fullness].append(zspage)

    def get_candidate_zspage(self):
        if self.fullness_lists["ZS_ALMOST_FULL"]:
            return self.fullness_lists["ZS_ALMOST_FULL"][0]
        if self.fullness_lists["ZS_ALMOST_EMPTY"]:
            return self.fullness_lists["ZS_ALMOST_EMPTY"][0]
        return None

class ZsmallocPool:
    def __init__(self, pool_name: str, class_configs: list):
        self.pool_name = pool_name
        self.size_classes = {}
        for cfg in sorted(class_configs, key=lambda x: x["size"]):
            sz = cfg["size"]
            pages = cfg.get("pages_per_zspage", 1)
            self.size_classes[sz] = ZsSizeClass(sz, pages)

        self.handles = {}
        self.next_zspage_id = 1
        self.total_pages_allocated = 0
        self.total_pages_freed = 0
        self.total_mallocs = 0
        self.total_frees = 0
        self.total_compactions = 0
        self.total_objects_migrated = 0

    def _find_size_class(self, size: int):
        for sz in sorted(self.size_classes.keys()):
            if sz >= size:
                return self.size_classes[sz]
        return None

    def zs_malloc(self, handle_id: str, size: int):
        sc = self._find_size_class(size)
        if not sc:
            return {"status": "ERROR_SIZE_TOO_LARGE", "handle_id": handle_id, "size": size}

        if handle_id in self.handles:
            return {"status": "ERROR_HANDLE_EXISTS", "handle_id": handle_id}

        zspage = sc.get_candidate_zspage()
        is_new_zspage = False

        if not zspage:
            zspage_id = self.next_zspage_id
            self.next_zspage_id += 1
            zspage = ZsPage(zspage_id, sc.size, sc.pages_per_zspage)
            sc.add_zspage(zspage)
            self.total_pages_allocated += sc.pages_per_zspage
            is_new_zspage = True

        old_fullness = zspage.fullness
        slot_idx = zspage.find_free_slot()
        zspage.slots[slot_idx] = handle_id
        sc.move_zspage_fullness(zspage, old_fullness)

        self.handles[handle_id] = {
            "class_size": sc.size,
            "zspage_id": zspage.zspage_id,
            "slot_idx": slot_idx,
            "req_size": size
        }
        self.total_mallocs += 1

        return {
            "status": "ALLOCATED",
            "handle_id": handle_id,
            "class_size": sc.size,
            "zspage_id": zspage.zspage_id,
            "slot_idx": slot_idx,
            "fullness": zspage.fullness,
            "is_new_zspage": is_new_zspage
        }

    def zs_free(self, handle_id: str):
        info = self.handles.get(handle_id)
        if not info:
            return {"status": "ERROR_INVALID_HANDLE", "handle_id": handle_id}

        sc = self.size_classes[info["class_size"]]
        zspage = sc.all_zspages[info["zspage_id"]]
        slot_idx = info["slot_idx"]

        old_fullness = zspage.fullness
        zspage.slots[slot_idx] = None
        sc.move_zspage_fullness(zspage, old_fullness)
        del self.handles[handle_id]
        self.total_frees += 1

        freed_pages = 0
        if zspage.fullness == "ZS_EMPTY":
            sc.fullness_lists["ZS_EMPTY"].remove(zspage)
            del sc.all_zspages[zspage.zspage_id]
            freed_pages = zspage.pages_count
            self.total_pages_freed += freed_pages

        return {
            "status": "FREED",
            "handle_id": handle_id,
            "zspage_id": zspage.zspage_id,
            "fullness": zspage.fullness if freed_pages == 0 else "RELEASED_TO_OS",
            "pages_freed": freed_pages
        }

    def zs_compact(self, target_class_size: int = None):
        self.total_compactions += 1
        migrated = 0
        pages_freed = 0

        classes_to_compact = [self.size_classes[target_class_size]] if target_class_size else list(self.size_classes.values())

        for sc in classes_to_compact:
            while True:
                sources = sorted(sc.fullness_lists["ZS_ALMOST_EMPTY"], key=lambda p: p.used_count)
                targets = sorted(sc.fullness_lists["ZS_ALMOST_FULL"] + [p for p in sc.fullness_lists["ZS_ALMOST_EMPTY"] if p not in sources[:1]],
                                 key=lambda p: p.free_count)

                if not sources or not targets:
                    break

                src = sources[0]
                tgt = targets[0]
                if src == tgt:
                    break

                moved_in_round = 0
                for s_idx, h_id in enumerate(src.slots):
                    if h_id is not None:
                        t_idx = tgt.find_free_slot()
                        if t_idx == -1:
                            break
                        src.slots[s_idx] = None
                        tgt.slots[t_idx] = h_id
                        self.handles[h_id]["zspage_id"] = tgt.zspage_id
                        self.handles[h_id]["slot_idx"] = t_idx
                        migrated += 1
                        self.total_objects_migrated += 1
                        moved_in_round += 1

                src.update_fullness()
                tgt.update_fullness()

                for flist in sc.fullness_lists.values():
                    flist.clear()
                for p in sc.all_zspages.values():
                    p.update_fullness()
                    sc.fullness_lists[p.fullness].append(p)

                if src.fullness == "ZS_EMPTY":
                    sc.fullness_lists["ZS_EMPTY"].remove(src)
                    del sc.all_zspages[src.zspage_id]
                    pages_freed += src.pages_count
                    self.total_pages_freed += src.pages_count

                if moved_in_round == 0:
                    break

        return {
            "status": "COMPACTION_COMPLETE",
            "objects_migrated": migrated,
            "pages_freed": pages_freed,
            "active_pages": self.total_pages_allocated - self.total_pages_freed
        }

    def inspect_pool(self):
        class_stats = {}
        total_used_slots = 0
        total_slots_avail = 0

        for sz, sc in self.size_classes.items():
            zspages_count = len(sc.all_zspages)
            used_s = sum(p.used_count for p in sc.all_zspages.values())
            total_s = sum(p.total_slots for p in sc.all_zspages.values())
            total_used_slots += used_s
            total_slots_avail += total_s

            class_stats[str(sz)] = {
                "zspages_count": zspages_count,
                "used_slots": used_s,
                "total_slots": total_s,
                "fullness": {
                    "ALMOST_FULL": len(sc.fullness_lists["ZS_ALMOST_FULL"]),
                    "ALMOST_EMPTY": len(sc.fullness_lists["ZS_ALMOST_EMPTY"]),
                    "FULL": len(sc.fullness_lists["ZS_FULL"]),
                    "EMPTY": len(sc.fullness_lists["ZS_EMPTY"])
                }
            }

        active_pages = self.total_pages_allocated - self.total_pages_freed
        mem_utilization = (total_used_slots / total_slots_avail) if total_slots_avail > 0 else 0.0

        return {
            "pool_name": self.pool_name,
            "active_pages": active_pages,
            "total_objects": len(self.handles),
            "memory_utilization": round(mem_utilization, 4),
            "class_stats": class_stats,
            "stats": {
                "total_pages_allocated": self.total_pages_allocated,
                "total_pages_freed": self.total_pages_freed,
                "total_mallocs": self.total_mallocs,
                "total_frees": self.total_frees,
                "total_compactions": self.total_compactions,
                "total_objects_migrated": self.total_objects_migrated
            }
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return

    commands = json.loads(raw_input)
    pool = None
    results = []

    for cmd in commands:
        op = cmd.get("op")
        if op == "INIT_POOL":
            pool = ZsmallocPool(cmd["pool_name"], cmd["classes"])
            results.append({"op": "INIT_POOL", "status": "OK", "pool_name": cmd["pool_name"]})
        elif op == "ZS_MALLOC":
            res = pool.zs_malloc(cmd["handle_id"], cmd["size"])
            results.append({"op": "ZS_MALLOC", "result": res})
        elif op == "ZS_FREE":
            res = pool.zs_free(cmd["handle_id"])
            results.append({"op": "ZS_FREE", "result": res})
        elif op == "ZS_COMPACT":
            res = pool.zs_compact(cmd.get("target_class"))
            results.append({"op": "ZS_COMPACT", "result": res})
        elif op == "INSPECT_POOL":
            res = pool.inspect_pool()
            results.append({"op": "INSPECT_POOL", "result": res})
        else:
            results.append({"op": op, "status": "UNKNOWN_OP"})

    print(json.dumps(results, separators=(',', ':')))

if __name__ == "__main__":
    main()
