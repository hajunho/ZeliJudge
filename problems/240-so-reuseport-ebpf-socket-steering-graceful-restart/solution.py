import sys
import json
import zlib
from typing import Dict, List, Any

def calc_hash(src_ip: str, src_port: int) -> int:
    key = f"{src_ip}:{src_port}".encode("utf-8")
    return zlib.crc32(key)

def solve(input_data: Dict[str, Any]) -> Dict[str, Any]:
    mode = input_data["mode"]
    num_workers = input_data["num_workers"]
    worker_cpus = input_data.get("worker_cpus", list(range(num_workers)))
    max_backlog = input_data.get("max_backlog", 128)
    load_watermark_pct = input_data.get("load_watermark_pct", 0.8)
    events = input_data.get("events", [])

    workers = {}
    for i in range(num_workers):
        w_id = i
        cpu = worker_cpus[i % len(worker_cpus)]
        workers[w_id] = {
            "worker_id": w_id,
            "cpu_id": cpu,
            "state": "ACTIVE",
            "backlog": [],
            "peak_backlog": 0,
            "syn_received": 0,
            "accepted": 0,
            "dropped_overflow": 0,
            "dropped_rst": 0
        }

    total_syn = 0
    total_accepted = 0
    total_overflow = 0
    total_rst = 0
    cross_core_count = 0
    old_worker_syn_after_reload = 0
    reload_started = False

    for ev in events:
        ev_type = ev.get("type")

        if ev_type == "SYN_PACKET":
            total_syn += 1
            conn_id = ev["conn_id"]
            src_ip = ev["src_ip"]
            src_port = ev["src_port"]
            pkt_cpu = ev.get("cpu_id", 0)

            target_worker_id = None

            if mode == "KERNEL_DEFAULT_REUSEPORT":
                avail_workers = [wid for wid, w in workers.items() if w["state"] in ("ACTIVE", "DRAINING")]
                if not avail_workers:
                    total_overflow += 1
                    continue
                avail_workers.sort()
                h = calc_hash(src_ip, src_port)
                idx = h % len(avail_workers)
                target_worker_id = avail_workers[idx]

                if reload_started and workers[target_worker_id]["state"] == "DRAINING":
                    old_worker_syn_after_reload += 1

            elif mode == "EBPF_CPU_AFFINITY":
                avail_workers = [w for w in workers.values() if w["state"] == "ACTIVE"]
                matched = [w for w in avail_workers if w["cpu_id"] == pkt_cpu]
                if matched:
                    target_worker_id = matched[0]["worker_id"]
                else:
                    if avail_workers:
                        avail_workers.sort(key=lambda w: w["worker_id"])
                        h = calc_hash(src_ip, src_port)
                        target_worker_id = avail_workers[h % len(avail_workers)]["worker_id"]
                    else:
                        total_overflow += 1
                        continue

            elif mode == "EBPF_LOAD_AWARE":
                avail_workers = [w for w in workers.values() if w["state"] == "ACTIVE"]
                if not avail_workers:
                    total_overflow += 1
                    continue
                avail_workers.sort(key=lambda w: w["worker_id"])
                matched = [w for w in avail_workers if w["cpu_id"] == pkt_cpu]
                primary = matched[0] if matched else avail_workers[calc_hash(src_ip, src_port) % len(avail_workers)]
                
                watermark_threshold = int(max_backlog * load_watermark_pct)
                if len(primary["backlog"]) >= watermark_threshold:
                    least_loaded = min(avail_workers, key=lambda w: len(w["backlog"]))
                    target_worker_id = least_loaded["worker_id"]
                else:
                    target_worker_id = primary["worker_id"]

            elif mode == "EBPF_GRACEFUL_RELOAD":
                avail_workers = [w for w in workers.values() if w["state"] == "ACTIVE"]
                if not avail_workers:
                    total_overflow += 1
                    continue
                matched = [w for w in avail_workers if w["cpu_id"] == pkt_cpu]
                if matched:
                    target_worker_id = matched[0]["worker_id"]
                else:
                    avail_workers.sort(key=lambda w: w["worker_id"])
                    target_worker_id = avail_workers[calc_hash(src_ip, src_port) % len(avail_workers)]["worker_id"]

            target_worker = workers[target_worker_id]
            target_worker["syn_received"] += 1

            if target_worker["cpu_id"] != pkt_cpu:
                cross_core_count += 1

            if len(target_worker["backlog"]) >= max_backlog:
                target_worker["dropped_overflow"] += 1
                total_overflow += 1
            else:
                target_worker["backlog"].append(conn_id)
                if len(target_worker["backlog"]) > target_worker["peak_backlog"]:
                    target_worker["peak_backlog"] = len(target_worker["backlog"])

        elif ev_type == "WORKER_ACCEPT":
            wid = ev["worker_id"]
            batch_size = ev.get("batch_size", 1)
            if wid in workers and workers[wid]["state"] != "DEAD":
                w = workers[wid]
                num_to_accept = min(len(w["backlog"]), batch_size)
                w["backlog"] = w["backlog"][num_to_accept:]
                w["accepted"] += num_to_accept
                total_accepted += num_to_accept

        elif ev_type == "RELOAD_START":
            reload_started = True
            old_wids = ev.get("old_workers", [])
            new_wids = ev.get("new_workers", [])
            new_cpus = ev.get("new_worker_cpus", [])

            for owid in old_wids:
                if owid in workers:
                    workers[owid]["state"] = "DRAINING"

            for idx, nwid in enumerate(new_wids):
                cpu = new_cpus[idx % len(new_cpus)] if new_cpus else idx
                workers[nwid] = {
                    "worker_id": nwid,
                    "cpu_id": cpu,
                    "state": "ACTIVE",
                    "backlog": [],
                    "peak_backlog": 0,
                    "syn_received": 0,
                    "accepted": 0,
                    "dropped_overflow": 0,
                    "dropped_rst": 0
                }

        elif ev_type == "CLOSE_SOCKET":
            wid = ev["worker_id"]
            if wid in workers and workers[wid]["state"] != "DEAD":
                w = workers[wid]
                w["state"] = "DEAD"
                dropped = len(w["backlog"])
                if dropped > 0:
                    w["dropped_rst"] += dropped
                    total_rst += dropped
                    w["backlog"] = []

    anomalies = []
    if total_overflow > 0:
        worker_peaks = [w["peak_backlog"] for w in workers.values()]
        if any(w["dropped_overflow"] > 0 for w in workers.values()) and any(p < (max_backlog * 0.5) for p in worker_peaks):
            anomalies.append("REUSEPORT_HASH_SKEW_QUEUE_OVERFLOW")
        else:
            anomalies.append("BACKLOG_CAPACITY_EXCEEDED")

    if total_rst > 0:
        anomalies.append("REUSEPORT_RELOAD_RST_UNACCEPTED_DROP")

    if old_worker_syn_after_reload > 0:
        anomalies.append("OLD_WORKER_DRAIN_STARVATION")

    if mode == "KERNEL_DEFAULT_REUSEPORT" and total_syn > 0 and (cross_core_count / total_syn) > 0.40:
        anomalies.append("CROSS_CORE_NUMA_CACHE_THRASHING")

    diag_parts = []
    if "REUSEPORT_HASH_SKEW_QUEUE_OVERFLOW" in anomalies:
        diag_parts.append("SO_REUSEPORT의 단순 4-튜플 해싱으로 인해 특정 워커 큐로 SYN 집중 및 오버플로우 드롭 발생 (eBPF 큐 깊이 기반 동적 스티어링 필요).")
    if "REUSEPORT_RELOAD_RST_UNACCEPTED_DROP" in anomalies:
        diag_parts.append("프로세스 재로드 중 소켓 종료 시 백로그 큐에 남아있던 미수락(unaccepted) 연결에 대해 커널 RST가 전송되어 연결 강제 종료됨.")
    if "OLD_WORKER_DRAIN_STARVATION" in anomalies:
        diag_parts.append("종료 대기 중인(Draining) 구버전 워커로 신규 SYN 패킷이 계속 분배되어 Graceful Shutdown 불가능.")
    if "CROSS_CORE_NUMA_CACHE_THRASHING" in anomalies:
        diag_parts.append(f"NIC RSS 인터럽트 처리 코어와 워커 코어 불일치율({cross_core_count}/{total_syn})로 인한 캐시 미스 및 인터-코어 락 경합 유발 (eBPF CPU Affinity 적용 권장).")
    if not anomalies:
        diag_parts.append("eBPF 소켓 스티어링을 통해 CPU 로컬리티 최적화 및 무중단 재로드(Zero-downtime drain)가 안정적으로 완료되었습니다.")

    diagnosis = " ".join(diag_parts)

    worker_stats = {}
    for wid, w in workers.items():
        worker_stats[str(wid)] = {
            "cpu_id": w["cpu_id"],
            "state": w["state"],
            "syn_received": w["syn_received"],
            "accepted": w["accepted"],
            "dropped_overflow": w["dropped_overflow"],
            "dropped_rst": w["dropped_rst"],
            "peak_backlog": w["peak_backlog"],
            "remaining_backlog": len(w["backlog"])
        }

    return {
        "mode": mode,
        "total_syn_packets": total_syn,
        "accepted_connections": total_accepted,
        "dropped_overflow": total_overflow,
        "dropped_rst_on_close": total_rst,
        "cross_core_dispatches": cross_core_count,
        "worker_stats": worker_stats,
        "anomalies": anomalies,
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
