import sys
import json

PAGE_SIZE_4K = 4096
PAGE_SIZE_2M = 2097152

def simulate_dax_pmem(input_data):
    config = input_data.get("config", {})
    eadr_supported = config.get("eadr_supported", False)
    t_load_store = config.get("t_load_store_ns", 10)
    t_clwb = config.get("t_clwb_ns", 40)
    t_sfence = config.get("t_sfence_ns", 20)
    t_page_fault_4k = config.get("t_page_fault_4k_ns", 800)
    t_page_fault_2m = config.get("t_page_fault_2m_ns", 1200)

    extents = input_data.get("extents", [])
    page_table = {}
    dirty_pfns = set()
    volatile_cachelines = set()
    
    operations = input_data.get("operations", [])
    op_results = []
    
    metrics = {
        "operations_total": len(operations),
        "total_latency_ns": 0,
        "pte_faults_4k": 0,
        "pmd_faults_2m": 0,
        "direct_memory_reads": 0,
        "direct_memory_writes": 0,
        "cachelines_flushed_clwb": 0,
        "sfence_barriers_issued": 0,
        "msync_fsync_commits": 0,
        "persistence_violations": 0
    }
    
    for op in operations:
        op_type = op.get("type")
        
        if op_type == "MMAP_FAULT":
            va = op.get("va")
            file_offset = op.get("offset")
            fault_size = op.get("fault_size", 4096)
            
            matched_pfn = None
            for ext in extents:
                start = ext.get("offset")
                length = ext.get("length")
                if start <= file_offset < start + length:
                    offset_within_ext = file_offset - start
                    matched_pfn = ext.get("pfn_start") + (offset_within_ext // 4096)
                    break
                    
            if matched_pfn is not None:
                if fault_size == PAGE_SIZE_2M:
                    metrics["pmd_faults_2m"] += 1
                    metrics["total_latency_ns"] += t_page_fault_2m
                    page_table[va] = {"pfn": matched_pfn, "size": PAGE_SIZE_2M}
                else:
                    metrics["pte_faults_4k"] += 1
                    metrics["total_latency_ns"] += t_page_fault_4k
                    page_table[va] = {"pfn": matched_pfn, "size": PAGE_SIZE_4K}
                    
                op_results.append({
                    "op_id": op.get("id"),
                    "type": op_type,
                    "status": "PFN_MAPPED",
                    "va": va,
                    "pfn": matched_pfn,
                    "fault_size": fault_size
                })
            else:
                op_results.append({
                    "op_id": op.get("id"),
                    "type": op_type,
                    "status": "FAULT_SIGBUS",
                    "va": va
                })

        elif op_type in ("DIRECT_READ", "DIRECT_WRITE"):
            va = op.get("va")
            size = op.get("size", 64)
            
            base_va = None
            entry = None
            for v, ent in page_table.items():
                if v <= va < v + ent["size"]:
                    base_va = v
                    entry = ent
                    break
                    
            if entry is None:
                op_results.append({
                    "op_id": op.get("id"),
                    "type": op_type,
                    "status": "UNMAPPED_FAULT",
                    "va": va
                })
                continue
                
            pfn = entry["pfn"] + ((va - base_va) // 4096)
            offset_in_page = (va - base_va) % 4096
            cacheline_idx = (pfn << 6) + (offset_in_page // 64)
            
            metrics["total_latency_ns"] += t_load_store
            if op_type == "DIRECT_READ":
                metrics["direct_memory_reads"] += 1
                op_results.append({
                    "op_id": op.get("id"),
                    "type": op_type,
                    "status": "DAX_READ_SUCCESS",
                    "pfn": pfn,
                    "cache_hit": cacheline_idx in volatile_cachelines
                })
            else:
                metrics["direct_memory_writes"] += 1
                volatile_cachelines.add(cacheline_idx)
                dirty_pfns.add(pfn)
                op_results.append({
                    "op_id": op.get("id"),
                    "type": op_type,
                    "status": "DAX_WRITE_SUCCESS",
                    "pfn": pfn,
                    "cacheline_dirtied": cacheline_idx
                })

        elif op_type == "CLWB":
            va = op.get("va")
            base_va = None
            entry = None
            for v, ent in page_table.items():
                if v <= va < v + ent["size"]:
                    base_va = v
                    entry = ent
                    break
            if entry is not None:
                pfn = entry["pfn"] + ((va - base_va) // 4096)
                offset_in_page = (va - base_va) % 4096
                cacheline_idx = (pfn << 6) + (offset_in_page // 64)
                
                if not eadr_supported:
                    metrics["total_latency_ns"] += t_clwb
                    metrics["cachelines_flushed_clwb"] += 1
                    if cacheline_idx in volatile_cachelines:
                        volatile_cachelines.remove(cacheline_idx)
                        
                op_results.append({
                    "op_id": op.get("id"),
                    "type": op_type,
                    "status": "CLWB_FLUSHED" if not eadr_supported else "EADR_BYPASSED",
                    "cacheline": cacheline_idx
                })

        elif op_type == "SFENCE":
            metrics["total_latency_ns"] += t_sfence
            metrics["sfence_barriers_issued"] += 1
            op_results.append({
                "op_id": op.get("id"),
                "type": op_type,
                "status": "SFENCE_ORDERED"
            })

        elif op_type == "MSYNC":
            metrics["msync_fsync_commits"] += 1
            flushed_count = 0
            if not eadr_supported:
                for cl in list(volatile_cachelines):
                    volatile_cachelines.remove(cl)
                    flushed_count += 1
                    metrics["cachelines_flushed_clwb"] += 1
                    metrics["total_latency_ns"] += t_clwb
                metrics["total_latency_ns"] += t_sfence
                metrics["sfence_barriers_issued"] += 1
            dirty_pfns.clear()
            op_results.append({
                "op_id": op.get("id"),
                "type": op_type,
                "status": "MSYNC_COMMITTED",
                "flushed_cachelines": flushed_count
            })

        elif op_type == "POWER_FAILURE_SIM":
            lost_count = len(volatile_cachelines)
            if lost_count > 0 and not eadr_supported:
                metrics["persistence_violations"] += lost_count
                status = "DATA_LOST_DUE_TO_UNFLUSHED_CACHELINE"
            else:
                status = "PERSISTED_SAFE"
            volatile_cachelines.clear()
            dirty_pfns.clear()
            op_results.append({
                "op_id": op.get("id"),
                "type": op_type,
                "status": status,
                "unpersisted_cachelines_lost": lost_count
            })

    return {
        "metrics": metrics,
        "active_mappings_count": len(page_table),
        "dirty_pfns_remaining": len(dirty_pfns),
        "op_results": op_results
    }

def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    result = simulate_dax_pmem(data)
    sys.stdout.write(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
