import sys
import json

class HvoEngine:
    def __init__(self, config):
        self.page_size = config.get("page_size", 4096)
        self.struct_page_size = config.get("struct_page_size", 64)
        self.hvo_enabled = config.get("hvo_enabled", True)
        self.buddy_free_pages = config.get("buddy_free_pages", 100000)
        self.hugepages = {}
        self.dissolve_failures = 0

    def alloc_hugepage(self, hugepage_id, page_type):
        if hugepage_id in self.hugepages:
            return {"status": "ERROR_ALREADY_EXISTS", "hugepage_id": hugepage_id}

        if page_type == "2MB":
            subpages = 512
            vmemmap_pages = (subpages * self.struct_page_size) // self.page_size
            opt_freed = 7 if self.hvo_enabled else 0
        elif page_type == "1GB":
            subpages = 262144
            vmemmap_pages = (subpages * self.struct_page_size) // self.page_size
            opt_freed = 4095 if self.hvo_enabled else 0
        else:
            return {"status": "ERROR_UNKNOWN_TYPE", "page_type": page_type}

        self.buddy_free_pages += opt_freed
        self.hugepages[hugepage_id] = {
            "page_type": page_type,
            "hvo_applied": self.hvo_enabled,
            "freed_pages": opt_freed,
            "subpages": subpages,
            "vmemmap_pages": vmemmap_pages
        }

        return {
            "status": "ALLOCATED",
            "hugepage_id": hugepage_id,
            "page_type": page_type,
            "hvo_applied": self.hvo_enabled,
            "freed_vmemmap_pages": opt_freed,
            "net_saved_bytes": opt_freed * self.page_size
        }

    def dissolve_hugepage(self, hugepage_id):
        if hugepage_id not in self.hugepages:
            return {"status": "ERROR_NOT_FOUND", "hugepage_id": hugepage_id}

        hp = self.hugepages[hugepage_id]
        freed_vmemmap = hp["freed_pages"]

        if hp["hvo_applied"] and freed_vmemmap > 0:
            if self.buddy_free_pages < freed_vmemmap:
                self.dissolve_failures += 1
                return {
                    "status": "ENOMEM_RESTORE_VMEMMAP",
                    "hugepage_id": hugepage_id,
                    "needed_pages": freed_vmemmap,
                    "buddy_free_pages": self.buddy_free_pages
                }
            self.buddy_free_pages -= freed_vmemmap

        del self.hugepages[hugepage_id]
        return {
            "status": "DISSOLVED",
            "hugepage_id": hugepage_id,
            "restored_vmemmap_pages": freed_vmemmap
        }

    def access_struct_page(self, hugepage_id, subpage_index, access_type):
        if hugepage_id not in self.hugepages:
            return {"status": "ERROR_NOT_FOUND", "hugepage_id": hugepage_id}

        hp = self.hugepages[hugepage_id]
        if subpage_index >= hp["subpages"]:
            return {"status": "ERROR_INDEX_OUT_OF_BOUNDS", "subpage_index": subpage_index}

        byte_offset = subpage_index * self.struct_page_size
        vmemmap_page_idx = byte_offset // self.page_size

        if hp["hvo_applied"]:
            if vmemmap_page_idx >= 1:
                if access_type == "WRITE":
                    return {
                        "status": "PAGE_FAULT_RO",
                        "hugepage_id": hugepage_id,
                        "vmemmap_page_idx": vmemmap_page_idx,
                        "subpage_index": subpage_index
                    }
                else:
                    return {
                        "status": "READ_SUCCESS",
                        "hugepage_id": hugepage_id,
                        "is_shared_tail": True,
                        "vmemmap_page_idx": vmemmap_page_idx
                    }
            else:
                return {
                    "status": "ACCESS_SUCCESS",
                    "hugepage_id": hugepage_id,
                    "is_head_page": True,
                    "access_type": access_type
                }
        else:
            return {
                "status": "ACCESS_SUCCESS",
                "hugepage_id": hugepage_id,
                "is_head_page": (vmemmap_page_idx == 0),
                "access_type": access_type
            }

    def query_stats(self):
        total_saved_pages = sum(hp["freed_pages"] for hp in self.hugepages.values())
        return {
            "total_hugepages": len(self.hugepages),
            "total_saved_vmemmap_pages": total_saved_pages,
            "total_saved_bytes": total_saved_pages * self.page_size,
            "buddy_free_pages": self.buddy_free_pages,
            "dissolve_failures": self.dissolve_failures
        }

def solve():
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    raw = sys.stdin.read().strip()
    if not raw:
        return

    input_data = json.loads(raw)
    config = input_data.get("config", {})
    engine = HvoEngine(config)
    results = []

    for op in input_data.get("operations", []):
        cmd = op.get("op")
        if cmd == "ALLOC_HUGEPAGE":
            res = engine.alloc_hugepage(op["hugepage_id"], op["page_type"])
            results.append(res)
        elif cmd == "DISSOLVE_HUGEPAGE":
            res = engine.dissolve_hugepage(op["hugepage_id"])
            results.append(res)
        elif cmd == "ACCESS_STRUCT_PAGE":
            res = engine.access_struct_page(op["hugepage_id"], op["subpage_index"], op["access_type"])
            results.append(res)
        elif cmd == "QUERY_STATS":
            res = engine.query_stats()
            results.append(res)

    out_obj = {"results": results}
    print(json.dumps(out_obj, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    solve()
