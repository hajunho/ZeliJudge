import sys
import json
import math
from typing import Dict, List, Any

class PostgresHotSimulator:
    def __init__(self, data: Dict[str, Any]):
        cfg = data.get("system", {})
        self.mode = cfg.get("mode", "OPTIMAL_HOT_TUNED")
        # Supported: "OPTIMAL_HOT_TUNED", "NAIVE_MAX_FILLFACTOR", "INDEXED_COLUMN_UPDATE"
        self.page_size_bytes = int(cfg.get("page_size_bytes", 8192))  # 8KB
        self.fillfactor = int(cfg.get("fillfactor", 100 if self.mode == "NAIVE_MAX_FILLFACTOR" else 75))
        self.num_indexes = int(cfg.get("num_indexes", 5))
        self.indexed_columns = set(cfg.get("indexed_columns", ["id", "created_at", "status"]))

        # Storage state: page_id -> {"free_bytes": int, "tuples": list}
        self.pages: Dict[int, Dict[str, Any]] = {}
        self.row_locations: Dict[str, Dict[str, Any]] = {}  # row_id -> {"page_id": int, "tuple_size": int}
        self.current_page_id = 0

        # Metrics
        self.total_inserts = 0
        self.total_updates = 0
        self.hot_updates_success = 0
        self.hot_updates_failed = 0
        self.table_writes_bytes = 0
        self.index_writes_bytes = 0
        self.index_entries_added = 0
        self.vacuum_reclaims_bytes = 0
        self.event_timeline: List[Dict[str, Any]] = []

    def get_or_create_insert_page(self, tuple_bytes: int) -> int:
        max_initial_fill = int(self.page_size_bytes * (self.fillfactor / 100.0))
        if self.current_page_id in self.pages:
            used = self.page_size_bytes - self.pages[self.current_page_id]["free_bytes"]
            if used + tuple_bytes <= max_initial_fill:
                return self.current_page_id

        # Allocate new page
        self.current_page_id += 1
        self.pages[self.current_page_id] = {
            "free_bytes": self.page_size_bytes,
            "tuples": []
        }
        return self.current_page_id

    def insert(self, row_id: str, tuple_bytes: int, t: float):
        self.total_inserts += 1
        page_id = self.get_or_create_insert_page(tuple_bytes)
        self.pages[page_id]["free_bytes"] -= tuple_bytes
        self.pages[page_id]["tuples"].append({"row_id": row_id, "size": tuple_bytes, "is_dead": False})
        self.row_locations[row_id] = {
            "page_id": page_id,
            "tuple_size": tuple_bytes
        }

        self.table_writes_bytes += tuple_bytes
        idx_write = self.num_indexes * 32
        self.index_writes_bytes += idx_write
        self.index_entries_added += self.num_indexes

        self.event_timeline.append({
            "wallclock_ms": t,
            "op": "INSERT",
            "row_id": row_id,
            "page_id": page_id,
            "index_writes_bytes": idx_write
        })

    def update(self, row_id: str, updated_columns: List[str], new_tuple_bytes: int, t: float):
        self.total_updates += 1
        loc = self.row_locations.get(row_id)
        if not loc:
            return

        old_page_id = loc["page_id"]
        old_page = self.pages[old_page_id]

        indexed_col_touched = any(c in self.indexed_columns for c in updated_columns)
        same_page_fits = (old_page["free_bytes"] >= new_tuple_bytes)
        is_hot = (not indexed_col_touched) and same_page_fits

        if is_hot:
            self.hot_updates_success += 1
            # Mark previous version as dead in page
            for tp in old_page["tuples"]:
                if tp["row_id"] == row_id and not tp["is_dead"]:
                    tp["is_dead"] = True
                    break
            old_page["free_bytes"] -= new_tuple_bytes
            old_page["tuples"].append({"row_id": row_id, "size": new_tuple_bytes, "is_dead": False})
            self.row_locations[row_id]["page_id"] = old_page_id

            self.table_writes_bytes += new_tuple_bytes
            self.event_timeline.append({
                "wallclock_ms": t,
                "op": "UPDATE",
                "row_id": row_id,
                "hot_result": "HOT_SUCCESS",
                "page_id": old_page_id,
                "index_writes_bytes": 0
            })
        else:
            self.hot_updates_failed += 1
            target_page_id = self.get_or_create_insert_page(new_tuple_bytes)
            self.pages[target_page_id]["free_bytes"] -= new_tuple_bytes
            self.pages[target_page_id]["tuples"].append({"row_id": row_id, "size": new_tuple_bytes, "is_dead": False})
            for tp in old_page["tuples"]:
                if tp["row_id"] == row_id and not tp["is_dead"]:
                    tp["is_dead"] = True
                    break
            self.row_locations[row_id]["page_id"] = target_page_id

            self.table_writes_bytes += new_tuple_bytes
            idx_write = self.num_indexes * 32
            self.index_writes_bytes += idx_write
            self.index_entries_added += self.num_indexes

            reason = "INDEXED_COLUMN_MODIFIED" if indexed_col_touched else "PAGE_FULL_NO_FREE_SPACE"
            self.event_timeline.append({
                "wallclock_ms": t,
                "op": "UPDATE",
                "row_id": row_id,
                "hot_result": f"HOT_FAILED_{reason}",
                "page_id": target_page_id,
                "index_writes_bytes": idx_write
            })

    def vacuum_page(self, page_id: int, t: float):
        page = self.pages.get(page_id)
        if not page:
            return
        dead_bytes = sum(tp["size"] for tp in page["tuples"] if tp["is_dead"])
        if dead_bytes > 0:
            page["tuples"] = [tp for tp in page["tuples"] if not tp["is_dead"]]
            page["free_bytes"] += dead_bytes
            self.vacuum_reclaims_bytes += dead_bytes
            self.event_timeline.append({
                "wallclock_ms": t,
                "op": "VACUUM",
                "page_id": page_id,
                "reclaimed_bytes": dead_bytes,
                "current_free_bytes": page["free_bytes"]
            })

    def run(self, workload: List[Dict[str, Any]]) -> Dict[str, Any]:
        for item in workload:
            t = float(item.get("wallclock_ms", 0.0))
            op = item.get("op")
            if op == "INSERT":
                self.insert(item["row_id"], int(item.get("size_bytes", 256)), t)
            elif op == "UPDATE":
                self.update(item["row_id"], list(item.get("columns", ["data"])), int(item.get("size_bytes", 256)), t)
            elif op == "VACUUM":
                self.vacuum_page(int(item["page_id"]), t)

        total_writes = self.table_writes_bytes + self.index_writes_bytes
        hot_rate = round(self.hot_updates_success / self.total_updates, 3) if self.total_updates > 0 else 1.0
        write_amp_ratio = round(total_writes / self.table_writes_bytes, 2) if self.table_writes_bytes > 0 else 1.0

        if self.mode == "NAIVE_MAX_FILLFACTOR" or (self.total_updates >= 5 and hot_rate < 0.2 and self.fillfactor == 100):
            verdict = "INDEX_WRITE_AMPLIFICATION_FILLFACTOR_100_COLLAPSE"
            status = "FAILED"
        elif self.mode == "INDEXED_COLUMN_UPDATE" or (self.total_updates >= 5 and hot_rate < 0.2):
            verdict = "HOT_INELIGIBLE_INDEXED_COLUMN_UPDATE_BLOAT"
            status = "FAILED"
        else:
            verdict = "OPTIMAL_HOT_INDEX_WRITE_MINIMIZED"
            status = "SUCCESS"

        return {
            "status": status,
            "summary": {
                "mode": self.mode,
                "fillfactor": self.fillfactor,
                "num_indexes": self.num_indexes,
                "total_inserts": self.total_inserts,
                "total_updates": self.total_updates,
                "hot_updates_success": self.hot_updates_success,
                "hot_updates_failed": self.hot_updates_failed,
                "hot_success_rate": hot_rate
            },
            "metrics": {
                "total_inserts": self.total_inserts,
                "total_updates": self.total_updates,
                "hot_updates_success": self.hot_updates_success,
                "hot_updates_failed": self.hot_updates_failed,
                "hot_success_rate": hot_rate,
                "table_writes_bytes": self.table_writes_bytes,
                "index_writes_bytes": self.index_writes_bytes,
                "total_writes_bytes": total_writes,
                "index_entries_added": self.index_entries_added,
                "write_amplification_ratio": write_amp_ratio,
                "vacuum_reclaims_bytes": self.vacuum_reclaims_bytes,
                "total_pages_allocated": len(self.pages),
                "verdict": verdict
            },
            "sample_events": self.event_timeline[:15]
        }

def solve():
    raw_data = sys.stdin.read().strip()
    if not raw_data:
        return
    input_data = json.loads(raw_data)
    simulator = PostgresHotSimulator(input_data)
    workload = input_data.get("workload", [])
    output = simulator.run(workload)
    print(json.dumps(output, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    solve()
