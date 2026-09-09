import sys
import json

def solve():
    input_data = sys.stdin.read().strip()
    if not input_data:
        return

    data = json.loads(input_data)
    config = data.get("config", {})
    dedupe_buffer_size_mb = float(config.get("dedupe_buffer_size_mb", 128.0))
    min_cleanable_dirty_ratio = float(config.get("min_cleanable_dirty_ratio", 0.5))
    delete_retention_ms = int(config.get("delete_retention_ms", 86400000))
    max_disk_capacity_mb = float(config.get("max_disk_capacity_mb", 10000.0))
    cleaner_threads = int(config.get("cleaner_threads", 1))

    workload = data.get("workload", {})
    total_messages = int(workload.get("total_messages", 2000000))
    unique_keys_count = int(workload.get("unique_keys_count", 1500000))
    avg_message_size_bytes = int(workload.get("avg_message_size_bytes", 500))
    tombstone_ratio = float(workload.get("tombstone_ratio", 0.1))
    elapsed_time_since_delete_ms = int(workload.get("elapsed_time_since_delete_ms", 3600000))

    raw_volume_mb = (total_messages * avg_message_size_bytes) / (1024.0 * 1024.0)
    needed_offset_map_bytes = unique_keys_count * 24
    needed_offset_map_mb = needed_offset_map_bytes / (1024.0 * 1024.0)

    dirty_ratio = (raw_volume_mb - ((unique_keys_count * avg_message_size_bytes) / (1024.0 * 1024.0))) / max(1.0, raw_volume_mb)
    dirty_ratio = max(0.1, min(1.0, dirty_ratio))

    cleaner_oom = False
    cleaner_skipped = False
    disk_exhausted = False
    tombstone_leak = False

    if cleaner_threads <= 0:
        cleaner_skipped = True
        final_disk_usage_mb = raw_volume_mb
    elif dirty_ratio < min_cleanable_dirty_ratio:
        cleaner_skipped = True
        final_disk_usage_mb = raw_volume_mb
    elif needed_offset_map_mb > dedupe_buffer_size_mb:
        cleaner_oom = True
        final_disk_usage_mb = raw_volume_mb
    else:
        retained_keys = unique_keys_count
        tombstones_count = int(unique_keys_count * tombstone_ratio)
        active_keys_count = retained_keys - tombstones_count

        if elapsed_time_since_delete_ms >= delete_retention_ms:
            surviving_records = active_keys_count
            tombstone_leak = False
        else:
            surviving_records = active_keys_count + tombstones_count
            tombstone_leak = (tombstone_ratio >= 0.3)

        final_disk_usage_mb = (surviving_records * avg_message_size_bytes) / (1024.0 * 1024.0)

    if final_disk_usage_mb > max_disk_capacity_mb:
        disk_exhausted = True

    compaction_ratio = max(0.0, 1.0 - (final_disk_usage_mb / raw_volume_mb))

    if cleaner_oom:
        status = "FAILED"
        verdict = "LOG_CLEANER_OFFSET_MAP_OOM_CRASH"
    elif disk_exhausted:
        status = "FAILED"
        verdict = "COMPACTED_TOPIC_DISK_EXHAUSTION"
    elif cleaner_skipped and dirty_ratio < min_cleanable_dirty_ratio:
        status = "SUCCESS"
        verdict = "CLEANER_DIRTY_RATIO_BELOW_THRESHOLD_SKIPPED"
    elif cleaner_skipped and cleaner_threads <= 0:
        status = "FAILED"
        verdict = "LOG_CLEANER_DISABLED_GROWTH_RISK"
    elif tombstone_leak:
        status = "WARNING"
        verdict = "TOMBSTONE_RETENTION_UNEXPIRED_BLOAT"
    elif compaction_ratio >= 0.4:
        status = "SUCCESS"
        verdict = "OPTIMAL_KAFKA_LOG_COMPACTION_STEADY_STATE"
    else:
        status = "SUCCESS"
        verdict = "STANDARD_LOG_CLEANING_COMPLETE"

    result = {
        "status": status,
        "verdict": verdict,
        "metrics": {
            "raw_volume_mb": round(raw_volume_mb, 2),
            "final_disk_usage_mb": round(final_disk_usage_mb, 2),
            "compaction_ratio": round(compaction_ratio, 4),
            "needed_offset_map_mb": round(needed_offset_map_mb, 2),
            "dedupe_buffer_size_mb": dedupe_buffer_size_mb,
            "dirty_ratio": round(dirty_ratio, 4),
            "cleaner_oom": cleaner_oom,
            "disk_exhausted": disk_exhausted
        }
    }
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    solve()
