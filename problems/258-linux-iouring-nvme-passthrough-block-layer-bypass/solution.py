import sys
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

def simulate_iouring_nvme(config):
    sq_size = config.get("sq_size", 1024)
    cq_size = config.get("cq_size", 2048)
    io_count = config.get("io_count", 500000)
    use_nvme_passthrough = config.get("use_nvme_passthrough", False)
    use_fixed_buffers = config.get("use_fixed_buffers", False)
    use_iopoll = config.get("use_iopoll", False)
    reap_batch_size = config.get("reap_batch_size", 64)
    reap_interval_us = config.get("reap_interval_us", 10)
    nvme_queue_depth = config.get("nvme_queue_depth", 1024)

    bio_allocations = 0
    blk_mq_spinlock_contention_pct = 0.0
    page_pin_unpin_cycles = 0
    cqe_overflow_count = 0
    sq_stall_count = 0
    completed_iops = 0
    p99_latency_us = 0.0
    status = ""
    diagnostics = []

    # Scenario 1: Classical Block Layer
    if not use_nvme_passthrough:
        bio_allocations = io_count
        blk_mq_spinlock_contention_pct = 38.5
        page_pin_unpin_cycles = io_count * 2
        status = "CLASSICAL_BLOCK_LAYER_BIO_OVERHEAD_BOTTLENECK"
        completed_iops = 780000
        p99_latency_us = 45.8
        diagnostics.append("io_uring이 전통적 VFS 및 blk-mq 블록 레이어를 경유하면서 매 I/O마다 bio 구조체 할당/해제 오버헤드가 발생했습니다.")
        diagnostics.append(f"bio 할당 횟수: {bio_allocations:,}회, blk-mq 스핀락 경합률: {blk_mq_spinlock_contention_pct}%. IOPS가 78만 수준에 머무릅니다.")
        recommendation = "IORING_OP_URING_CMD NVMe Passthrough를 활성화하여 커널 블록 레이어(bio/blk-mq)를 완전히 바이패스하십시오."

    # Scenario 2: NVMe Passthrough without Fixed Buffers
    elif not use_fixed_buffers:
        bio_allocations = 0
        blk_mq_spinlock_contention_pct = 0.0
        page_pin_unpin_cycles = io_count * 2
        status = "DYNAMIC_PAGE_PINNING_TLB_SHOOTDOWN_STALL"
        completed_iops = 1650000
        p99_latency_us = 24.5
        diagnostics.append("NVMe Passthrough는 활성화되었으나 고정 버퍼(IORING_REGISTER_BUFFERS)가 등록되지 않았습니다.")
        diagnostics.append(f"매 I/O마다 get_user_pages_fast() 및 unpin_user_page()가 반복({page_pin_unpin_cycles:,}회)되어 mmap_lock 경합 및 TLB shootdown 지연이 발생합니다.")
        recommendation = "IORING_REGISTER_BUFFERS를 통해 거대 페이지(HugePage)를 사전에 메모리에 고정(Pinning)하여 런타임 락을 제거하십시오."

    # Scenario 3: IOPOLL Starvation
    elif use_iopoll and reap_interval_us > 50:
        bio_allocations = 0
        blk_mq_spinlock_contention_pct = 0.0
        page_pin_unpin_cycles = 0
        sq_stall_count = int(io_count * 0.15)
        status = "IOPOLL_COMPLETION_REAPING_STARVATION"
        completed_iops = 1420000
        p99_latency_us = 68.2
        diagnostics.append(f"IORING_SETUP_IOPOLL 모드에서 유저스페이스의 폴링 수거 간격({reap_interval_us}us)이 너무 길어 NVMe 하드웨어 완료 큐가 회수되지 못했습니다.")
        diagnostics.append(f"제출 큐(SQ) 고갈 및 스톨({sq_stall_count:,}회)이 발생하여 P99 지연시간이 68.2us로 폭증했습니다.")
        recommendation = "전용 폴링 스레드(Dedicated Poller)를 구성하고 reap_interval을 5us 이하로 단축하거나 Adaptive Polling을 적용하십시오."

    # Scenario 4: CQE Overflow
    elif cq_size < sq_size * 2 and io_count > 200000:
        bio_allocations = 0
        blk_mq_spinlock_contention_pct = 0.0
        page_pin_unpin_cycles = 0
        cqe_overflow_count = int((io_count * 0.08))
        status = "CQE_RING_OVERFLOW_AUXILIARY_LIST_BLOAT"
        completed_iops = 2100000
        p99_latency_us = 35.4
        diagnostics.append(f"CQ 링 크기({cq_size})가 SQ 크기({sq_size}) 대비 부족하여 완료 이벤트가 커널 내부 보조 연결 리스트(cq_overflow_list)로 유출되었습니다.")
        diagnostics.append(f"CQE 오버플로우 {cqe_overflow_count:,}건 발생. 보조 리스트 순회 및 동적 메모리 할당으로 제로카피 무잠금 원칙이 훼손되었습니다.")
        recommendation = "CQ 링 크기를 최소 SQ 크기의 2배 이상(IORING_SETUP_CQSIZE)으로 확장하고 역압(Backpressure)을 적용하십시오."

    # Scenario 5: Optimal NVMe Passthrough Pipeline
    else:
        bio_allocations = 0
        blk_mq_spinlock_contention_pct = 0.0
        page_pin_unpin_cycles = 0
        cqe_overflow_count = 0
        sq_stall_count = 0
        status = "OPTIMAL_NVME_PASSTHROUGH_ZERO_COPY_PIPELINE"
        completed_iops = 3850000
        p99_latency_us = 4.8
        diagnostics.append("커널 블록 레이어 완전 바이패스(bio/blk-mq 0건), 고정 버퍼 DMA 사전 핀닝, 락리스 IOPOLL 전용 수거 파이프라인이 완벽히 가동 중입니다.")
        diagnostics.append(f"초당 385만 IOPS(3.85M IOPS) 달성 및 P99 극저지연(4.8us) 사수 성공. CQE 오버플로우 0건.")
        recommendation = "최적의 초고성능 NVMe io_uring 패스스루 아키텍처 상태 유지."

    return {
        "status": status,
        "io_performance": {
            "completed_iops": completed_iops,
            "p99_latency_us": p99_latency_us,
            "bio_allocations": bio_allocations,
            "blk_mq_spinlock_contention_pct": blk_mq_spinlock_contention_pct,
            "page_pin_unpin_cycles": page_pin_unpin_cycles,
            "cqe_overflow_count": cqe_overflow_count,
            "sq_stall_count": sq_stall_count
        },
        "diagnostics": diagnostics,
        "recommendation": recommendation
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    result = simulate_iouring_nvme(data)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
