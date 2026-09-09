#!/usr/bin/env python3
import sys
import json

def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)

    config = input_data["system_config"]
    steps = input_data["simulation_steps"]

    nic_driver = config.get("nic_driver", "generic")
    driver_zerocopy_supported = config.get("driver_zerocopy_supported", False)
    umem_total_chunks = config.get("umem_total_chunks", 4096)
    chunk_size_bytes = config.get("chunk_size_bytes", 2048)
    headroom_bytes = config.get("headroom_bytes", 256)
    fill_ring_size = config.get("fill_ring_size", 1024)
    rx_ring_size = config.get("rx_ring_size", 1024)
    tx_ring_size = config.get("tx_ring_size", 1024)
    completion_ring_size = config.get("completion_ring_size", 1024)
    bind_flags = config.get("bind_flags", [])
    initial_fill_chunks = config.get("initial_fill_chunks", 1024)
    replenish_batch_size = config.get("replenish_batch_size", 128)
    replenish_watermark = config.get("replenish_watermark", 256)

    # Max payload capacity
    max_payload = chunk_size_bytes - headroom_bytes

    # Bind check
    is_bind_failed = False
    mode = "COPY"

    if "XDP_ZEROCOPY" in bind_flags:
        if not driver_zerocopy_supported:
            if "XDP_COPY" in bind_flags:
                mode = "COPY"
            else:
                is_bind_failed = True
                mode = "NONE"
        else:
            mode = "ZEROCOPY"
    elif "XDP_COPY" in bind_flags:
        mode = "COPY"
    else:
        if driver_zerocopy_supported:
            mode = "ZEROCOPY"
        else:
            mode = "COPY"

    if is_bind_failed:
        output = {
            "status": "BIND_FAILURE_DRIVER_INCOMPATIBLE",
            "mode": mode,
            "metrics": {
                "total_rx_ingress": 0,
                "rx_received": 0,
                "total_rx_processed": 0,
                "fill_ring_starvation_drops": 0,
                "rx_ring_overflow_drops": 0,
                "mtu_exceeded_drops": 0,
                "tx_queued": 0,
                "tx_completed": 0,
                "tx_ring_overflow_drops": 0,
                "tx_no_buffer_drops": 0,
                "total_copy_bytes": 0,
                "min_fill_ring_occupancy": 0,
                "max_rx_ring_occupancy": 0
            },
            "diagnostics": [
                f"Socket bind failed: Driver '{nic_driver}' does not support XDP_ZEROCOPY and no copy fallback allowed."
            ],
            "recommended_tuning": {
                "bind_flags": ["XDP_COPY"],
                "suggestion": "Enable XDP_COPY fallback or use native zero-copy supported NIC driver (e.g., mlx5_core, i40e, ice)."
            }
        }
        print(json.dumps(output, ensure_ascii=False))
        return

    # Free chunk pool
    free_chunks = list(range(umem_total_chunks))

    # Fill Ring initialization
    fill_ring = []
    initial_alloc = min(initial_fill_chunks, fill_ring_size, len(free_chunks))
    for _ in range(initial_alloc):
        fill_ring.append(free_chunks.pop())

    rx_ring = [] # holds dict(packet_id, size_bytes, chunk_addr)
    tx_ring = [] # holds dict(packet_id, size_bytes, chunk_addr)
    completion_ring = [] # holds chunk_addr

    total_rx_ingress = 0
    rx_received = 0
    total_rx_processed = 0
    fill_ring_starvation_drops = 0
    rx_ring_overflow_drops = 0
    mtu_exceeded_drops = 0
    tx_queued = 0
    tx_completed = 0
    tx_ring_overflow_drops = 0
    tx_no_buffer_drops = 0
    total_copy_bytes = 0

    min_fill_ring_occupancy = len(fill_ring)
    max_rx_ring_occupancy = len(rx_ring)

    for step in steps:
        step_id = step.get("step_id", 0)
        incoming_rx = step.get("incoming_rx_packets", [])
        rx_budget = step.get("userspace_rx_budget", 0)
        outgoing_tx = step.get("outgoing_tx_packets", [])
        tx_comp_budget = step.get("driver_tx_completion_budget", 0)

        # Phase A: Driver Tx Completion
        comp_count = min(len(tx_ring), tx_comp_budget)
        for _ in range(comp_count):
            tx_pkt = tx_ring.pop(0)
            chunk_addr = tx_pkt["chunk_addr"]
            if len(completion_ring) < completion_ring_size:
                completion_ring.append(chunk_addr)
            else:
                free_chunks.append(chunk_addr)
            tx_completed += 1

        # Userspace reclaims from completion ring
        while completion_ring:
            free_chunks.append(completion_ring.pop(0))

        # Phase B: Driver Rx Packet Ingestion (NIC DMA)
        for pkt in incoming_rx:
            total_rx_ingress += 1
            pkt_id = pkt["packet_id"]
            pkt_size = pkt["size_bytes"]

            if pkt_size > max_payload:
                mtu_exceeded_drops += 1
                continue

            if len(fill_ring) == 0:
                fill_ring_starvation_drops += 1
                continue

            if len(rx_ring) >= rx_ring_size:
                rx_ring_overflow_drops += 1
                continue

            chunk = fill_ring.pop(0)
            rx_ring.append({"packet_id": pkt_id, "size_bytes": pkt_size, "chunk_addr": chunk})
            rx_received += 1

            if mode == "COPY":
                total_copy_bytes += pkt_size

        # Record occupancy after ingestion
        min_fill_ring_occupancy = min(min_fill_ring_occupancy, len(fill_ring))
        max_rx_ring_occupancy = max(max_rx_ring_occupancy, len(rx_ring))

        # Phase C: Userspace Rx Packet Processing
        proc_count = min(len(rx_ring), rx_budget)
        for _ in range(proc_count):
            rx_item = rx_ring.pop(0)
            free_chunks.append(rx_item["chunk_addr"])
            total_rx_processed += 1

        # Phase D: Userspace Tx Queueing
        for pkt in outgoing_tx:
            pkt_id = pkt["packet_id"]
            pkt_size = pkt["size_bytes"]

            if pkt_size > max_payload:
                continue

            if not free_chunks:
                tx_no_buffer_drops += 1
                continue

            if len(tx_ring) >= tx_ring_size:
                tx_ring_overflow_drops += 1
                continue

            chunk = free_chunks.pop()
            tx_ring.append({"packet_id": pkt_id, "size_bytes": pkt_size, "chunk_addr": chunk})
            tx_queued += 1

            if mode == "COPY":
                total_copy_bytes += pkt_size

        # Phase E: Userspace Fill Ring Replenishment
        if len(fill_ring) <= replenish_watermark and free_chunks:
            slots_available = fill_ring_size - len(fill_ring)
            to_add = min(replenish_batch_size, slots_available, len(free_chunks))
            for _ in range(to_add):
                fill_ring.append(free_chunks.pop())

        min_fill_ring_occupancy = min(min_fill_ring_occupancy, len(fill_ring))

    # Evaluate Status
    diagnostics = []
    recommended_tuning = {}

    if mtu_exceeded_drops > 0:
        status = "MTU_CHUNK_MISMATCH_TRUNCATION"
        diagnostics.append(f"{mtu_exceeded_drops} packets exceeded UMEM chunk payload limit ({max_payload} bytes).")
        recommended_tuning["chunk_size_bytes"] = 4096
        recommended_tuning["suggestion"] = "Increase chunk_size_bytes to 4096 or configure multi-buffer AF_XDP for jumbo frames."
    elif fill_ring_starvation_drops > 0:
        status = "FILL_RING_STARVATION_COLLAPSE"
        diagnostics.append(f"{fill_ring_starvation_drops} packets dropped due to Fill Ring starvation (NIC driver ran out of receive chunks).")
        recommended_tuning["replenish_watermark"] = max(replenish_watermark * 2, fill_ring_size // 2)
        recommended_tuning["replenish_batch_size"] = max(replenish_batch_size * 2, 256)
        recommended_tuning["suggestion"] = "Raise replenish_watermark and increase replenish_batch_size to eagerly replenish Fill Ring before burst arrival."
    elif rx_ring_overflow_drops > 0:
        status = "RX_RING_OVERFLOW_BACKPRESSURE"
        diagnostics.append(f"{rx_ring_overflow_drops} packets dropped due to Rx Ring overflow (userspace consumption slower than packet ingress).")
        recommended_tuning["rx_ring_size"] = rx_ring_size * 2
        recommended_tuning["suggestion"] = "Increase rx_ring_size and optimize userspace polling budget (e.g. enable SO_BUSY_POLL and scale worker cores)."
    elif mode == "COPY":
        status = "UNSUPPORTED_COPY_MODE_DEGRADED"
        diagnostics.append(f"Operating in XDP_COPY mode. Total copy overhead: {total_copy_bytes} bytes. Native zero-copy DMA unavailable.")
        recommended_tuning["bind_flags"] = ["XDP_ZEROCOPY"]
        recommended_tuning["suggestion"] = "Upgrade to NIC driver supporting XSK zero-copy (e.g. mlx5, i40e, ice) and set bind flag XDP_ZEROCOPY."
    else:
        status = "HEALTHY_ZEROCOPY_LINE_RATE"
        diagnostics.append("AF_XDP operating at healthy line rate with zero-copy DMA. No packet drops or ring starvation detected.")
        recommended_tuning["suggestion"] = "Optimal configuration maintained."

    output = {
        "status": status,
        "mode": mode,
        "metrics": {
            "total_rx_ingress": total_rx_ingress,
            "rx_received": rx_received,
            "total_rx_processed": total_rx_processed,
            "fill_ring_starvation_drops": fill_ring_starvation_drops,
            "rx_ring_overflow_drops": rx_ring_overflow_drops,
            "mtu_exceeded_drops": mtu_exceeded_drops,
            "tx_queued": tx_queued,
            "tx_completed": tx_completed,
            "tx_ring_overflow_drops": tx_ring_overflow_drops,
            "tx_no_buffer_drops": tx_no_buffer_drops,
            "total_copy_bytes": total_copy_bytes,
            "min_fill_ring_occupancy": min_fill_ring_occupancy,
            "max_rx_ring_occupancy": max_rx_ring_occupancy
        },
        "diagnostics": diagnostics,
        "recommended_tuning": recommended_tuning
    }
    print(json.dumps(output, ensure_ascii=False))

if __name__ == "__main__":
    solve()
