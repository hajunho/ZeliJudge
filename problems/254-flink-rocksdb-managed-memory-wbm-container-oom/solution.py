import json
import sys

def simulate_flink_rocksdb(data):
    tm_cfg = data["taskmanager_config"]
    container_limit = tm_cfg.get("container_memory_limit_mb", 8192)
    jvm_heap = tm_cfg.get("jvm_heap_mb", 3072)
    direct_mem = tm_cfg.get("direct_memory_mb", 512)
    overhead = tm_cfg.get("jvm_overhead_mb", 512)
    managed_mem = tm_cfg.get("managed_memory_mb", 4096)
    managed_enabled = tm_cfg.get("rocksdb_memory_managed", True)
    wb_ratio = tm_cfg.get("write_buffer_ratio", 0.5)
    high_prio_ratio = tm_cfg.get("high_priority_pool_ratio", 0.1)
    pin_index_filter = tm_cfg.get("pin_l0_index_and_filter", True)
    num_slots = tm_cfg.get("num_task_slots", 4)
    num_operators = tm_cfg.get("num_stateful_operators", 5)

    num_instances = num_slots * num_operators

    workload = data.get("workload", {})
    write_rate = workload.get("write_throughput_mb_per_sec", 100)
    read_rate = workload.get("read_query_rate_per_sec", 5000)
    working_set_mb = workload.get("state_working_set_mb", 1500)

    if managed_enabled:
        memtable_budget = managed_mem * wb_ratio
        high_prio_budget = managed_mem * high_prio_ratio
        data_block_budget = max(0, managed_mem - memtable_budget - high_prio_budget)
        rocksdb_total_offheap = managed_mem
    else:
        per_instance_mem = 192
        rocksdb_total_offheap = num_instances * per_instance_mem
        memtable_budget = num_instances * 128
        high_prio_budget = 0
        data_block_budget = num_instances * 64

    total_container_usage = jvm_heap + direct_mem + overhead + rocksdb_total_offheap

    container_oomkilled = (total_container_usage > container_limit)
    block_cache_starvation = False
    index_filter_eviction_spike = False
    cache_miss_rate = 0.0
    read_amplification = 1.0

    events = sorted(data.get("events", []), key=lambda e: e.get("time_sec", 0))
    for ev in events:
        ev_type = ev["type"]
        if ev_type == "TRAFFIC_BURST":
            write_rate *= ev.get("write_multiplier", 1.0)
            read_rate *= ev.get("read_multiplier", 1.0)

        elif ev_type == "SCALE_OPERATORS":
            num_operators = ev.get("num_operators", num_operators)
            num_instances = num_slots * num_operators
            if not managed_enabled:
                rocksdb_total_offheap = num_instances * 192
                total_container_usage = jvm_heap + direct_mem + overhead + rocksdb_total_offheap
                if total_container_usage > container_limit:
                    container_oomkilled = True

    if not container_oomkilled:
        if data_block_budget < (working_set_mb * 0.3):
            block_cache_starvation = True
            cache_miss_rate = 0.85
        elif data_block_budget < working_set_mb:
            cache_miss_rate = (working_set_mb - data_block_budget) / float(working_set_mb)
        else:
            cache_miss_rate = 0.05

        if not pin_index_filter or high_prio_ratio == 0:
            index_filter_eviction_spike = True
            read_amplification = 12.5
        else:
            read_amplification = 1.1

    # Diagnosis Hierarchy
    if container_oomkilled:
        root_cause = "TASKMANAGER_CONTAINER_CGROUP_OOMKILLED"
    elif block_cache_starvation:
        root_cause = "BLOCK_CACHE_STARVATION_BY_EXCESSIVE_MEMTABLES"
    elif index_filter_eviction_spike:
        root_cause = "INDEX_FILTER_BLOCK_EVICTION_READ_AMPLIFICATION"
    else:
        root_cause = "STABLE_BALANCED_MANAGED_ROCKSDB_STATE"

    recommendations = []
    if not managed_enabled:
        recommendations.append("ENABLE_ROCKSDB_MANAGED_MEMORY")
    if wb_ratio > 0.6:
        recommendations.append("TUNE_WRITE_BUFFER_RATIO_TO_PRESERVE_BLOCK_CACHE")
    if not pin_index_filter or high_prio_ratio == 0:
        recommendations.append("PIN_L0_INDEX_FILTER_AND_SET_HIGH_PRIORITY_POOL")
    if total_container_usage > (container_limit * 0.9) and managed_enabled:
        recommendations.append("INCREASE_TASKMANAGER_CONTAINER_MEMORY_LIMIT")

    if not recommendations:
        recommendations.append("MAINTAIN_CURRENT_ROCKSDB_MANAGED_CONFIG")

    return {
        "final_state": {
            "total_container_usage_mb": total_container_usage,
            "rocksdb_total_offheap_mb": rocksdb_total_offheap,
            "data_block_budget_mb": int(data_block_budget),
            "memtable_budget_mb": int(memtable_budget),
            "num_rocksdb_instances": num_instances
        },
        "metrics": {
            "container_oomkilled": container_oomkilled,
            "block_cache_starvation": block_cache_starvation,
            "index_filter_eviction_spike": index_filter_eviction_spike,
            "cache_miss_rate": round(cache_miss_rate, 3),
            "read_amplification": read_amplification
        },
        "root_cause": root_cause,
        "recommendations": recommendations
    }

def main():
    try:
        input_data = sys.stdin.read().strip()
        if not input_data:
            return
        data = json.loads(input_data)
        result = simulate_flink_rocksdb(data)
        print(json.dumps(result, indent=2))
    except Exception as e:
        sys.stderr.write(f"Error: {str(e)}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
