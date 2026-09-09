# scratch/sim_184.py
import json
import sys
from typing import Dict, List, Any, Optional, Set, Tuple

class LogRecord:
    def __init__(self, lsn: int, tx_id: Optional[str], type: str, page_id: Optional[str] = None,
                 prev_lsn: int = 0, undo_next_lsn: Optional[int] = None,
                 old_val: Optional[str] = None, new_val: Optional[str] = None,
                 dpt: Optional[Dict[str, int]] = None,
                 active_transactions: Optional[Dict[str, Dict[str, Any]]] = None):
        self.lsn = lsn
        self.tx_id = tx_id
        self.type = type # UPDATE, COMMIT, ABORT, END, CLR, FLUSH_PAGE, CHECKPOINT
        self.page_id = page_id
        self.prev_lsn = prev_lsn
        self.undo_next_lsn = undo_next_lsn
        self.old_val = old_val
        self.new_val = new_val
        self.dpt = dpt or {}
        self.active_transactions = active_transactions or {}

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "lsn": self.lsn,
            "tx_id": self.tx_id,
            "type": self.type,
            "page_id": self.page_id,
            "prev_lsn": self.prev_lsn
        }
        if self.undo_next_lsn is not None:
            d["undo_next_lsn"] = self.undo_next_lsn
        if self.old_val is not None:
            d["old_val"] = self.old_val
        if self.new_val is not None:
            d["new_val"] = self.new_val
        if self.dpt:
            d["dpt"] = self.dpt
        if self.active_transactions:
            d["active_transactions"] = self.active_transactions
        return d

class DiskPage:
    def __init__(self, page_id: str, page_lsn: int = 0, content: str = ""):
        self.page_id = page_id
        self.page_lsn = page_lsn
        self.content = content

    def to_dict(self) -> Dict[str, Any]:
        return {
            "page_id": self.page_id,
            "page_lsn": self.page_lsn,
            "content": self.content
        }

class AriesRecoveryEngine:
    def __init__(self, data: Dict[str, Any]):
        config = data.get("config", {})
        self.buffer_policy = config.get("buffer_pool_policy", {"steal": True, "force": False})
        self.recovery_mode = config.get("recovery_mode", "FULL_ARIES")
        # FULL_ARIES, NO_REDO, NO_UNDO, CRASH_DURING_UNDO
        self.crash_at_clr_count = config.get("crash_at_clr_count", 1)
        self.checkpoint_lsn = config.get("checkpoint_lsn", 0)

        # Initialize persistent disk state
        self.disk_pages: Dict[str, DiskPage] = {}
        for pid, pdata in data.get("initial_disk", {}).items():
            self.disk_pages[pid] = DiskPage(pid, pdata.get("page_lsn", 0), pdata.get("content", ""))

        # Parse WAL log
        self.wal_log: List[LogRecord] = []
        for r in data.get("wal_log", []):
            self.wal_log.append(LogRecord(
                lsn=r["lsn"],
                tx_id=r.get("tx_id"),
                type=r["type"],
                page_id=r.get("page_id"),
                prev_lsn=r.get("prev_lsn", 0),
                undo_next_lsn=r.get("undo_next_lsn"),
                old_val=r.get("old_val"),
                new_val=r.get("new_val"),
                dpt=r.get("dpt"),
                active_transactions=r.get("active_transactions")
            ))

        self.dpt: Dict[str, int] = {} # page_id -> recLSN
        self.transaction_table: Dict[str, Dict[str, Any]] = {} # tx_id -> {"status": ..., "lastLSN": ...}
        self.losers: Set[str] = set()

        self.metrics = {
            "analysis_records_scanned": 0,
            "smallest_rec_lsn": 0,
            "redo_applied_count": 0,
            "redo_skipped_count": 0,
            "undo_clr_written": 0,
            "active_losers_count": 0,
            "crash_during_recovery": False,
            "verdict": ""
        }
        self.generated_clrs: List[Dict[str, Any]] = []

    def run_recovery(self) -> Dict[str, Any]:
        # Phase 1: Analysis Phase
        self._run_analysis()

        # Phase 2: Redo Phase ("Repeating History")
        if self.recovery_mode == "NO_REDO":
            self.metrics["verdict"] = "NO_FORCE_DIRTY_PAGE_DATA_LOSS_CORRUPTION"
            return self._build_result()

        self._run_redo()

        # Phase 3: Undo Phase
        if self.recovery_mode == "NO_UNDO":
            self.metrics["verdict"] = "STEAL_UNCOMMITTED_DIRTY_LEAK_CORRUPTION"
            return self._build_result()

        self._run_undo()

        if self.metrics["crash_during_recovery"]:
            self.metrics["verdict"] = "REPEATING_CRASH_DURING_UNDO_IDEMPOTENT_CLR"
        else:
            self.metrics["verdict"] = "ARIES_RECOVERY_SUCCESS"

        return self._build_result()

    def _run_analysis(self):
        start_idx = 0
        if self.checkpoint_lsn > 0:
            for i, r in enumerate(self.wal_log):
                if r.lsn >= self.checkpoint_lsn:
                    start_idx = i
                    break

        for record in self.wal_log[start_idx:]:
            self.metrics["analysis_records_scanned"] += 1
            tx_id = record.tx_id

            if tx_id:
                if tx_id not in self.transaction_table:
                    self.transaction_table[tx_id] = {"status": "ACTIVE", "lastLSN": record.lsn}
                self.transaction_table[tx_id]["lastLSN"] = record.lsn

            if record.type == "COMMIT":
                if tx_id:
                    self.transaction_table[tx_id]["status"] = "COMMITTED"
            elif record.type == "END":
                if tx_id in self.transaction_table:
                    del self.transaction_table[tx_id]
            elif record.type == "UPDATE":
                if record.page_id:
                    if record.page_id not in self.dpt:
                        self.dpt[record.page_id] = record.lsn
            elif record.type == "CLR":
                if record.page_id:
                    if record.page_id not in self.dpt:
                        self.dpt[record.page_id] = record.lsn
            elif record.type == "CHECKPOINT":
                if record.dpt:
                    for pid, rlsn in record.dpt.items():
                        if pid not in self.dpt:
                            self.dpt[pid] = rlsn
                if record.active_transactions:
                    for tid, tinfo in record.active_transactions.items():
                        if tid not in self.transaction_table:
                            self.transaction_table[tid] = dict(tinfo)
            elif record.type == "FLUSH_PAGE":
                if record.page_id:
                    if record.page_id in self.disk_pages:
                        self.disk_pages[record.page_id].page_lsn = record.lsn
                        if record.new_val:
                            self.disk_pages[record.page_id].content = record.new_val
                    if record.page_id in self.dpt:
                        del self.dpt[record.page_id]

        for tx_id, info in list(self.transaction_table.items()):
            if info["status"] != "COMMITTED":
                self.losers.add(tx_id)

        self.metrics["active_losers_count"] = len(self.losers)
        if self.dpt:
            self.metrics["smallest_rec_lsn"] = min(self.dpt.values())
        else:
            self.metrics["smallest_rec_lsn"] = self.checkpoint_lsn

    def _run_redo(self):
        redo_start = self.metrics["smallest_rec_lsn"]
        for record in self.wal_log:
            if record.lsn < redo_start:
                continue
            if record.type not in ("UPDATE", "CLR"):
                continue

            pid = record.page_id
            if not pid or pid not in self.disk_pages:
                continue

            disk_page = self.disk_pages[pid]

            # Redo Optimization Checks
            if pid not in self.dpt:
                self.metrics["redo_skipped_count"] += 1
                continue
            if record.lsn < self.dpt[pid]:
                self.metrics["redo_skipped_count"] += 1
                continue
            if disk_page.page_lsn >= record.lsn:
                self.metrics["redo_skipped_count"] += 1
                continue

            # Apply REDO
            disk_page.content = record.new_val if record.new_val is not None else disk_page.content
            disk_page.page_lsn = record.lsn
            self.metrics["redo_applied_count"] += 1

    def _run_undo(self):
        log_by_lsn = {r.lsn: r for r in self.wal_log}
        next_clr_lsn = max(r.lsn for r in self.wal_log) + 10 if self.wal_log else 100

        to_undo: Set[int] = set()
        for tx_id in self.losers:
            to_undo.add(self.transaction_table[tx_id]["lastLSN"])

        while to_undo:
            max_lsn = max(to_undo)
            to_undo.remove(max_lsn)

            if max_lsn not in log_by_lsn:
                continue

            record = log_by_lsn[max_lsn]

            if record.type == "UPDATE":
                pid = record.page_id
                if pid and pid in self.disk_pages:
                    self.disk_pages[pid].content = record.old_val if record.old_val is not None else ""
                    self.disk_pages[pid].page_lsn = next_clr_lsn

                clr = LogRecord(
                    lsn=next_clr_lsn,
                    tx_id=record.tx_id,
                    type="CLR",
                    page_id=pid,
                    prev_lsn=self.transaction_table[record.tx_id]["lastLSN"],
                    undo_next_lsn=record.prev_lsn,
                    new_val=record.old_val
                )
                self.transaction_table[record.tx_id]["lastLSN"] = next_clr_lsn
                self.generated_clrs.append(clr.to_dict())
                self.metrics["undo_clr_written"] += 1
                log_by_lsn[next_clr_lsn] = clr
                next_clr_lsn += 10

                if self.recovery_mode == "CRASH_DURING_UNDO" and self.metrics["undo_clr_written"] == self.crash_at_clr_count:
                    self.metrics["crash_during_recovery"] = True
                    return

                if record.prev_lsn > 0:
                    to_undo.add(record.prev_lsn)
                else:
                    if record.tx_id in self.transaction_table:
                        del self.transaction_table[record.tx_id]

            elif record.type == "CLR":
                # Encountered CLR: Never undo CLRs, jump directly to undo_next_lsn
                if record.undo_next_lsn and record.undo_next_lsn > 0:
                    to_undo.add(record.undo_next_lsn)
                else:
                    if record.tx_id in self.transaction_table:
                        del self.transaction_table[record.tx_id]

    def _build_result(self) -> Dict[str, Any]:
        final_disk = {}
        for pid in sorted(self.disk_pages.keys()):
            final_disk[pid] = self.disk_pages[pid].to_dict()

        return {
            "status": "SUCCESS",
            "recovery_mode": self.recovery_mode,
            "metrics": dict(self.metrics),
            "final_disk": final_disk,
            "dirty_page_table": dict(sorted(self.dpt.items())),
            "loser_transactions": sorted(list(self.losers)),
            "generated_clrs": self.generated_clrs
        }

def solve(data: Dict[str, Any]) -> Dict[str, Any]:
    engine = AriesRecoveryEngine(data)
    return engine.run_recovery()

def main():
    raw_data = sys.stdin.read().strip()
    if not raw_data:
        return
    req = json.loads(raw_data)
    res = solve(req)
    print(json.dumps(res, indent=2))

if __name__ == "__main__":
    main()
