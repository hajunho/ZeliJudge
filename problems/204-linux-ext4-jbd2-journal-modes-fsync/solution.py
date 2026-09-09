#!/usr/bin/env python3
"""
ZeliJudge Problem #204: 리눅스 ext4 파일 시스템 저널링: JBD2 저널 모드(data=ordered vs journal vs writeback)와 정전 복구 무결성
Solution Implementation
"""
import sys
import json

def simulate(input_data):
    cfg = input_data.get("mount_config", {})
    journal_mode = cfg.get("journal_mode", "data=ordered")
    barrier_enabled = cfg.get("barrier", True)

    initial_files = input_data.get("files", {})
    operations = input_data.get("operations", [])

    disk_files = {f: data.get("content", "") for f, data in initial_files.items()}
    journaled_metadata = {f: len(disk_files[f]) for f in disk_files}

    tx_running = {
        "metadata": {},
        "journal_data": {},
        "data_pages": {}
    }

    total_user_bytes_written = 0
    disk_data_bytes_written = 0
    journal_data_bytes_written = 0
    journal_metadata_bytes_written = 0
    committed_transactions = 0
    aborted_transactions = 0
    stale_data_leaks_detected = 0

    METADATA_BLOCK_SIZE = 4096

    def flush_transaction(commit_barrier=True):
        nonlocal disk_data_bytes_written, journal_data_bytes_written, journal_metadata_bytes_written, committed_transactions
        if not tx_running["metadata"] and not tx_running["data_pages"]:
            return

        if journal_mode == "data=journal":
            for f, chunks in tx_running["journal_data"].items():
                for offset, data_str in chunks:
                    data_len = len(data_str.encode("utf-8"))
                    journal_data_bytes_written += data_len
            journal_metadata_bytes_written += len(tx_running["metadata"]) * METADATA_BLOCK_SIZE + 512

            for f, chunks in tx_running["data_pages"].items():
                for offset, data_str in chunks:
                    data_len = len(data_str.encode("utf-8"))
                    disk_data_bytes_written += data_len
                    cur = disk_files.get(f, "")
                    if offset > len(cur):
                        cur = cur.ljust(offset, "\x00")
                    cur = cur[:offset] + data_str + cur[offset + len(data_str):]
                    disk_files[f] = cur
            for f, sz in tx_running["metadata"].items():
                journaled_metadata[f] = sz

        elif journal_mode == "data=ordered":
            for f, chunks in tx_running["data_pages"].items():
                for offset, data_str in chunks:
                    data_len = len(data_str.encode("utf-8"))
                    disk_data_bytes_written += data_len
                    cur = disk_files.get(f, "")
                    if offset > len(cur):
                        cur = cur.ljust(offset, "\x00")
                    cur = cur[:offset] + data_str + cur[offset + len(data_str):]
                    disk_files[f] = cur

            journal_metadata_bytes_written += len(tx_running["metadata"]) * METADATA_BLOCK_SIZE + 512
            for f, sz in tx_running["metadata"].items():
                journaled_metadata[f] = sz

        elif journal_mode == "data=writeback":
            journal_metadata_bytes_written += len(tx_running["metadata"]) * METADATA_BLOCK_SIZE + 512
            for f, sz in tx_running["metadata"].items():
                journaled_metadata[f] = sz

            if commit_barrier:
                for f, chunks in tx_running["data_pages"].items():
                    for offset, data_str in chunks:
                        data_len = len(data_str.encode("utf-8"))
                        disk_data_bytes_written += data_len
                        cur = disk_files.get(f, "")
                        if offset > len(cur):
                            cur = cur.ljust(offset, "\x00")
                        cur = cur[:offset] + data_str + cur[offset + len(data_str):]
                        disk_files[f] = cur

        committed_transactions += 1
        tx_running["metadata"].clear()
        tx_running["journal_data"].clear()
        tx_running["data_pages"].clear()

    for op in operations:
        action = op.get("op")

        if action == "write":
            f = op.get("file")
            offset = op.get("offset", 0)
            data_str = op.get("data", "")
            data_len = len(data_str.encode("utf-8"))
            total_user_bytes_written += data_len

            if f not in disk_files:
                disk_files[f] = ""
                journaled_metadata[f] = 0

            cur_max = max(len(disk_files[f]), journaled_metadata.get(f, 0))
            new_size = max(cur_max, offset + len(data_str))
            tx_running["metadata"][f] = new_size
            
            if f not in tx_running["data_pages"]:
                tx_running["data_pages"][f] = []
            tx_running["data_pages"][f].append((offset, data_str))

            if journal_mode == "data=journal":
                if f not in tx_running["journal_data"]:
                    tx_running["journal_data"][f] = []
                tx_running["journal_data"][f].append((offset, data_str))

        elif action == "fsync":
            flush_transaction(commit_barrier=True)

        elif action == "commit_tick":
            flush_transaction(commit_barrier=barrier_enabled)

        elif action == "power_cut_crash":
            if tx_running["metadata"]:
                aborted_transactions += 1

            for f, j_sz in journaled_metadata.items():
                cur_disk_len = len(disk_files.get(f, ""))
                if j_sz > cur_disk_len:
                    stale_data_leaks_detected += (j_sz - cur_disk_len + 4095) // 4096
                    disk_files[f] = disk_files.get(f, "").ljust(j_sz, "\x00")

            tx_running["metadata"].clear()
            tx_running["journal_data"].clear()
            tx_running["data_pages"].clear()
            break

    data_write_amplification_ratio = round(
        (disk_data_bytes_written + journal_data_bytes_written) / max(1, total_user_bytes_written), 2
    )

    unflushed_dirty = sum(
        sum(len(d.encode("utf-8")) for _, d in chunks)
        for chunks in tx_running["data_pages"].values()
    )

    if stale_data_leaks_detected > 0:
        status = "EXT4_WRITEBACK_STALE_DATA_LEAK"
    elif journal_mode == "data=journal" and data_write_amplification_ratio >= 1.90:
        status = "EXT4_DATA_JOURNAL_WRITE_AMPLIFICATION_BOTTLENECK"
    else:
        status = "OPTIMAL_EXT4_ORDERED_JOURNAL_CONSISTENCY"

    root_causes = {
        "EXT4_WRITEBACK_STALE_DATA_LEAK": (
            f"ext4 data=writeback 모드 크래시 무결성 파괴 참사: 메타데이터 저널링과 파일 데이터 플러시 순서가 역전되어, "
            f"정전 후 복구 시 아이노드 크기는 확장되었으나 실제 데이터 블록이 기록되지 않아 {stale_data_leaks_detected}개의 "
            "블록에 이전 삭제 파일 잔여물 및 널 바이트(0x00) 쓰레기 데이터 누출 발생."
        ),
        "EXT4_DATA_JOURNAL_WRITE_AMPLIFICATION_BOTTLENECK": (
            f"ext4 data=journal 모드 2배 쓰기 증폭 병목 참사: 모든 유저 데이터({total_user_bytes_written}B)를 저널링 링버퍼에 1차 기록 후 "
            f"실제 파일 블록에 2차 기록(총 {disk_data_bytes_written + journal_data_bytes_written}B 데이터 물리 쓰기)하여 "
            f"데이터 쓰기 증폭률 {data_write_amplification_ratio}x 발생 및 SSD 수명/디스크 IOPS 고갈."
        ),
        "OPTIMAL_EXT4_ORDERED_JOURNAL_CONSISTENCY": (
            f"ext4 data=ordered 저널링 최적화 완수: 데이터 블록 선(先)플러시 후 메타데이터 저널 커밋 불변식 보장으로 "
            f"데이터 쓰기 증폭 1.0x(물리 데이터 {disk_data_bytes_written}B + 저널 메타데이터 {journal_metadata_bytes_written}B) 및 "
            f"정전 크래시 시에도 쓰레기 누출 0건(100% 무결점 크래시 일관성) 달성."
        )
    }

    return {
        "status": status,
        "metrics": {
            "total_user_bytes_written": total_user_bytes_written,
            "disk_data_bytes_written": disk_data_bytes_written,
            "journal_data_bytes_written": journal_data_bytes_written,
            "journal_metadata_bytes_written": journal_metadata_bytes_written,
            "data_write_amplification_ratio": data_write_amplification_ratio,
            "unflushed_dirty_data_bytes": unflushed_dirty,
            "committed_transactions": committed_transactions,
            "aborted_transactions": aborted_transactions,
            "stale_data_leaks_detected": stale_data_leaks_detected,
            "recovered_files_count": len(disk_files)
        },
        "root_cause_analysis": root_causes.get(status, "")
    }

def main():
    try:
        raw_input = sys.stdin.read().strip()
        if not raw_input:
            return
        input_data = json.loads(raw_input)
        result = simulate(input_data)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
