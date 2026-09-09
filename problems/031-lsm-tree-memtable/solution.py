#!/usr/bin/env python3
import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return

    it = iter(input_data)

    # 1. ?? ??: CONFIG MEMTABLE_CAPACITY:<C> COMPACTION_THRESHOLD:<T>
    cmd = next(it)  # CONFIG
    c_token = next(it)
    t_token = next(it)

    C = int(c_token.split(':')[1])
    T = int(t_token.split(':')[1])

    Q = int(next(it))

    # ??? ??
    memtable = {}
    sstables = []  # [(sst_name, dict_data)]
    sst_counter = 1
    compact_counter = 1
    total_flushes = 0
    total_compactions = 0

    def check_compaction():
        nonlocal compact_counter, total_compactions, sstables
        if len(sstables) == T:
            total_compactions += 1
            merged_name = f"SST-Merged-{compact_counter}"
            compact_counter += 1

            merged_data = {}
            for _, sst_data in sstables:
                merged_data.update(sst_data)

            sorted_merged = dict(sorted(merged_data.items(), key=lambda x: x[0]))
            print(f"[COMPACT] Merged {T} SSTables -> {merged_name} FINAL_KEYS:{len(sorted_merged)}")
            sstables = [(merged_name, sorted_merged)]

    def check_flush():
        nonlocal sst_counter, total_flushes
        if len(memtable) == C:
            sst_name = f"SST-{sst_counter}"
            sst_counter += 1
            total_flushes += 1

            sorted_items = sorted(memtable.items(), key=lambda x: x[0])
            sst_data = dict(sorted_items)
            sstables.append((sst_name, sst_data))
            print(f"[FLUSH] MemTable -> {sst_name} KEYS:{len(sorted_items)}")
            memtable.clear()
            check_compaction()

    for _ in range(Q):
        op = next(it)
        if op == "PUT":
            key = next(it)
            val = next(it)
            memtable[key] = val
            check_flush()
        elif op == "DELETE":
            key = next(it)
            memtable[key] = "__DELETED__"
            check_flush()
        elif op == "GET":
            key = next(it)
            if key in memtable:
                val = memtable[key]
                if val == "__DELETED__":
                    print(f"GET {key} FOUND_IN:MEMTABLE STATUS:DELETED")
                else:
                    print(f"GET {key} FOUND_IN:MEMTABLE VALUE:{val}")
            else:
                found = False
                for sst_name, sst_data in reversed(sstables):
                    if key in sst_data:
                        val = sst_data[key]
                        if val == "__DELETED__":
                            print(f"GET {key} FOUND_IN:{sst_name} STATUS:DELETED")
                        else:
                            print(f"GET {key} FOUND_IN:{sst_name} VALUE:{val}")
                        found = True
                        break
                if not found:
                    print(f"GET {key} STATUS:NOT_FOUND")

    print(
        f"SUMMARY TOTAL_FLUSHES:{total_flushes} TOTAL_COMPACTIONS:{total_compactions} ACTIVE_SSTABLES:{len(sstables)} FINAL_MEMTABLE_KEYS:{len(memtable)}"
    )

if __name__ == '__main__':
    solve()
