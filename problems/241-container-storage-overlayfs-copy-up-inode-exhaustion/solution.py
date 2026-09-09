import sys
import json
from typing import Dict, List, Any

def solve(input_data: Dict[str, Any]) -> Dict[str, Any]:
    fs_config = input_data["fs_config"]
    host_total_inodes = fs_config.get("host_total_inodes", 100000)
    host_used_inodes = fs_config.get("host_used_inodes", 10000)
    host_disk_cap_mb = fs_config.get("host_disk_capacity_mb", 102400)
    host_disk_used_mb = fs_config.get("host_disk_used_mb", 20000)
    io_bw_mb_s = fs_config.get("disk_io_bandwidth_mb_per_sec", 200.0)

    mount_opts = fs_config.get("overlay_mount_options", {})
    opt_index = mount_opts.get("index", "off") == "on"
    opt_xino = mount_opts.get("xino", "off") in ("on", "auto")
    opt_metacopy = mount_opts.get("metacopy", "off") == "on"

    layers = input_data.get("layers", [])
    operations = input_data.get("operations", [])

    lower_files = {}
    for layer in layers:
        l_id = layer.get("layer_id", "lower")
        for f in layer.get("files", []):
            p = f["path"]
            lower_files[p] = {
                "size_mb": f.get("size_mb", 1),
                "origin_dev": f.get("dev_id", 1),
                "origin_ino": f.get("inode", 100),
                "layer": l_id
            }

    upper_files = {}
    tracked_stats = {}
    
    current_inodes = host_used_inodes
    current_disk_mb = host_disk_used_mb
    next_upper_inode = 900000
    upper_dev_id = 99

    copy_up_events = 0
    copy_up_data_mb = 0.0
    max_copy_up_lat_ms = 0.0
    whiteout_count = 0
    inode_mutation_detected = False
    inode_exhausted = False
    large_whiteout_scan_detected = False

    for op_item in operations:
        op = op_item.get("op")
        path = op_item.get("path", "")

        if op == "STAT":
            if path in upper_files:
                u = upper_files[path]
                if u["is_whiteout"]:
                    visible_dev, visible_ino = None, None
                else:
                    if opt_xino:
                        visible_dev = lower_files.get(path, {}).get("origin_dev", u["dev_id"])
                        visible_ino = lower_files.get(path, {}).get("origin_ino", u["inode"])
                    else:
                        visible_dev = u["dev_id"]
                        visible_ino = u["inode"]
            elif path in lower_files:
                l = lower_files[path]
                visible_dev = l["origin_dev"]
                visible_ino = l["origin_ino"]
            else:
                visible_dev, visible_ino = None, None

            if visible_dev is not None:
                if path in tracked_stats:
                    prev_dev, prev_ino = tracked_stats[path]
                    if (prev_dev, prev_ino) != (visible_dev, visible_ino):
                        inode_mutation_detected = True
                tracked_stats[path] = (visible_dev, visible_ino)

        elif op == "WRITE":
            bytes_written_mb = op_item.get("bytes_written_mb", 1)
            is_metadata_only = op_item.get("is_metadata_only", False)

            if path in upper_files and not upper_files[path]["is_whiteout"]:
                upper_files[path]["size_mb"] = max(upper_files[path]["size_mb"], bytes_written_mb)
                current_disk_mb += bytes_written_mb
            elif path in lower_files:
                l = lower_files[path]
                copy_up_events += 1

                if opt_metacopy and is_metadata_only:
                    lat_ms = 1.0
                    copied_mb = 0.0
                else:
                    copied_mb = l["size_mb"]
                    lat_ms = (copied_mb / io_bw_mb_s) * 1000.0
                    copy_up_data_mb += copied_mb
                    current_disk_mb += copied_mb

                if lat_ms > max_copy_up_lat_ms:
                    max_copy_up_lat_ms = lat_ms

                current_inodes += 1
                next_upper_inode += 1

                upper_files[path] = {
                    "size_mb": l["size_mb"] if not (opt_metacopy and is_metadata_only) else 0,
                    "dev_id": upper_dev_id,
                    "inode": next_upper_inode,
                    "is_whiteout": False
                }
            else:
                current_inodes += 1
                next_upper_inode += 1
                current_disk_mb += bytes_written_mb
                upper_files[path] = {
                    "size_mb": bytes_written_mb,
                    "dev_id": upper_dev_id,
                    "inode": next_upper_inode,
                    "is_whiteout": False
                }

        elif op == "DELETE":
            if path in lower_files:
                current_inodes += 1
                whiteout_count += 1
                upper_files[path] = {
                    "size_mb": 0,
                    "dev_id": upper_dev_id,
                    "inode": next_upper_inode + 1,
                    "is_whiteout": True
                }
                next_upper_inode += 1
            elif path in upper_files:
                current_inodes -= 1
                del upper_files[path]

        elif op == "CREATE_BATCH":
            file_count = op_item.get("file_count", 0)
            size_kb = op_item.get("size_per_file_kb", 1)
            total_size_mb = (file_count * size_kb) / 1024.0

            if current_inodes + file_count > host_total_inodes:
                inode_exhausted = True
                current_inodes = host_total_inodes
            else:
                current_inodes += file_count
                current_disk_mb += total_size_mb

        elif op == "READDIR":
            if whiteout_count > 50:
                large_whiteout_scan_detected = True

    inode_util_pct = round((current_inodes / host_total_inodes) * 100.0, 2)
    disk_util_pct = round((current_disk_mb / host_disk_cap_mb) * 100.0, 2)

    anomalies = []
    if max_copy_up_lat_ms >= 1000.0:
        anomalies.append("OVERLAYFS_COPY_UP_LATENCY_SPIKE")

    if inode_mutation_detected:
        anomalies.append("OVERLAYFS_INODE_MUTATION_ANOMALY")

    if inode_exhausted or (inode_util_pct >= 99.0 and disk_util_pct < 90.0):
        anomalies.append("HOST_INODE_EXHAUSTION_ENOSPC")

    if whiteout_count > 50 or large_whiteout_scan_detected:
        anomalies.append("WHITEOUT_ACCUMULATION_DEGRADATION")

    recommendations = []
    if "OVERLAYFS_COPY_UP_LATENCY_SPIKE" in anomalies:
        recommendations.append("USE_PERSISTENT_VOLUME_FOR_MUTABLE_LARGE_FILES")
    if "OVERLAYFS_INODE_MUTATION_ANOMALY" in anomalies:
        recommendations.append("ENABLE_OVERLAYFS_XINO_AND_INDEX_MOUNT_OPTIONS")
    if "HOST_INODE_EXHAUSTION_ENOSPC" in anomalies:
        recommendations.append("CLEANUP_DANGLING_IMAGES_OR_USE_MULTI_STAGE_BUILD")
    if "WHITEOUT_ACCUMULATION_DEGRADATION" in anomalies:
        recommendations.append("SQUASH_IMAGE_LAYERS_AND_AVOID_IN_CONTAINER_DELETION")

    diag_parts = []
    if "OVERLAYFS_COPY_UP_LATENCY_SPIKE" in anomalies:
        diag_parts.append(f"Lowerdir 대용량 파일 수정 시 동기 복사(Copy-up)로 인해 최대 지연시간({round(max_copy_up_lat_ms, 1)}ms) 스파이크 발생.")
    if "OVERLAYFS_INODE_MUTATION_ANOMALY" in anomalies:
        diag_parts.append("Copy-up 이후 (st_dev, st_ino) 식별자가 변경되어 POSIX 파일 동일성 보장 실패 (xino=on 마운트 옵션 필요).")
    if "HOST_INODE_EXHAUSTION_ENOSPC" in anomalies:
        diag_parts.append(f"디스크 용량 여유({100.0 - disk_util_pct:.1f}% 남음)에도 불구하고 소용량 파일 폭증으로 호스트 Inode가 고갈(100%)되어 ENOSPC 발생.")
    if "WHITEOUT_ACCUMULATION_DEGRADATION" in anomalies:
        diag_parts.append(f"하위 레이어 파일 삭제로 인한 Whiteout 디바이스 노드 누적({whiteout_count}개)으로 readdir 디렉터리 스캔 지연 발생.")
    if not anomalies:
        diag_parts.append("OverlayFS 스토리지 레이어가 최적화된 마운트 옵션과 볼륨 분리를 통해 정상적으로 동작 중입니다.")

    diagnosis = " ".join(diag_parts)

    return {
        "total_operations": len(operations),
        "copy_up_events": copy_up_events,
        "copy_up_data_mb": round(copy_up_data_mb, 2),
        "max_copy_up_latency_ms": round(max_copy_up_lat_ms, 2),
        "host_inode_utilization_pct": inode_util_pct,
        "host_disk_utilization_pct": disk_util_pct,
        "inode_mutation_detected": inode_mutation_detected,
        "whiteout_count": whiteout_count,
        "anomalies": anomalies,
        "recommendations": recommendations,
        "diagnosis": diagnosis
    }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    result = solve(data)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
