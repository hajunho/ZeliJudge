import sys
import json

class LSMStorageEngine:
    def __init__(self, data):
        c = data.get("config", {})
        self.memtable_capacity = int(c.get("memtable_capacity", 4))
        self.max_immutable_memtables = int(c.get("max_immutable_memtables", 2))
        self.l0_compaction_trigger = int(c.get("l0_compaction_trigger", 3))
        self.l0_slowdown_trigger = int(c.get("l0_slowdown_trigger", 5))
        self.l0_stop_trigger = int(c.get("l0_stop_trigger", 8))

        # Storage components
        self.active_memtable = {} # key -> {"val": v, "tombstone": bool}
        self.immutable_memtables = [] # list of dicts (oldest at index 0)
        self.l0_files = [] # list of dicts (newest at index 0)
        self.l1_storage = {} # key -> {"val": v, "tombstone": bool}

        # Metrics
        self.total_writes = 0
        self.normal_writes = 0
        self.slowdown_writes = 0
        self.stopped_writes = 0
        self.total_reads = 0
        self.total_read_probes = 0
        self.total_compactions = 0

        self.operations = data.get("operations", [])

    def run(self):
        results = []

        for op in self.operations:
            op_type = op.get("type")

            if op_type in ("PUT", "DELETE"):
                k = op.get("key")
                is_del = (op_type == "DELETE")
                v = None if is_del else op.get("val")

                self.total_writes += 1
                l0_count = len(self.l0_files)
                imm_count = len(self.immutable_memtables)

                if l0_count >= self.l0_stop_trigger or imm_count >= self.max_immutable_memtables:
                    status = "WRITE_STALL_STOP"
                    latency_ms = 500.0
                    accepted = False
                    self.stopped_writes += 1
                elif l0_count >= self.l0_slowdown_trigger:
                    status = "WRITE_STALL_SLOWDOWN"
                    latency_ms = 25.0
                    accepted = True
                    self.slowdown_writes += 1
                else:
                    status = "NORMAL"
                    latency_ms = 0.5
                    accepted = True
                    self.normal_writes += 1

                if accepted:
                    self.active_memtable[k] = {"val": v, "tombstone": is_del}
                    if len(self.active_memtable) >= self.memtable_capacity:
                        self.immutable_memtables.append(dict(self.active_memtable))
                        self.active_memtable = {}

                results.append({
                    "op": op_type,
                    "key": k,
                    "status": status,
                    "latency_ms": latency_ms,
                    "accepted": accepted,
                    "l0_count": l0_count,
                    "immutable_count": imm_count
                })

            elif op_type == "GET":
                k = op.get("key")
                self.total_reads += 1

                probes = 0
                found = False
                val = None
                key_resolved = False

                # 1. Active MemTable
                probes += 1
                if k in self.active_memtable:
                    rec = self.active_memtable[k]
                    found = not rec["tombstone"]
                    val = rec["val"]
                    key_resolved = True
                else:
                    # 2. Immutable MemTables (newest to oldest)
                    for imm in reversed(self.immutable_memtables):
                        probes += 1
                        if k in imm:
                            rec = imm[k]
                            found = not rec["tombstone"]
                            val = rec["val"]
                            key_resolved = True
                            break

                    # 3. L0 Files (newest to oldest)
                    if not key_resolved:
                        for l0 in self.l0_files:
                            probes += 1
                            if k in l0:
                                rec = l0[k]
                                found = not rec["tombstone"]
                                val = rec["val"]
                                key_resolved = True
                                break

                    # 4. L1 Storage (sorted non-overlapping run)
                    if not key_resolved:
                        probes += 1
                        if k in self.l1_storage:
                            rec = self.l1_storage[k]
                            found = not rec["tombstone"]
                            val = rec["val"]
                            key_resolved = True

                self.total_read_probes += probes
                results.append({
                    "op": "GET",
                    "key": k,
                    "found": found,
                    "val": val,
                    "read_probes": probes
                })

            elif op_type == "TICK":
                flushed = False
                if self.immutable_memtables:
                    imm = self.immutable_memtables.pop(0)
                    self.l0_files.insert(0, imm)
                    flushed = True

                compacted_files = 0
                if len(self.l0_files) >= self.l0_compaction_trigger:
                    self.total_compactions += 1
                    compacted_files = len(self.l0_files)
                    merged = {}
                    for l0 in reversed(self.l0_files):
                        merged.update(l0)
                    for k_m, rec_m in merged.items():
                        if rec_m["tombstone"]:
                            self.l1_storage.pop(k_m, None)
                        else:
                            self.l1_storage[k_m] = rec_m
                    self.l0_files = []

                results.append({
                    "op": "TICK",
                    "flushed_immutable": flushed,
                    "compacted_l0_files": compacted_files,
                    "remaining_l0": len(self.l0_files),
                    "remaining_imm": len(self.immutable_memtables),
                    "l1_total_keys": len(self.l1_storage)
                })

        avg_probes = round(self.total_read_probes / self.total_reads, 2) if self.total_reads > 0 else 0.0

        return {
            "summary": {
                "total_writes": self.total_writes,
                "normal_writes": self.normal_writes,
                "slowdown_writes": self.slowdown_writes,
                "stopped_writes": self.stopped_writes,
                "write_stall_occurred": (self.slowdown_writes > 0 or self.stopped_writes > 0),
                "total_reads": self.total_reads,
                "avg_read_probes": avg_probes,
                "total_compactions": self.total_compactions,
                "final_l0_files": len(self.l0_files),
                "final_immutable_memtables": len(self.immutable_memtables),
                "final_l1_keys": len(self.l1_storage)
            },
            "results": results
        }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    engine = LSMStorageEngine(data)
    result = engine.run()
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
