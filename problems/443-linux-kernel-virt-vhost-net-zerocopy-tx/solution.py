# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #443 Solution:
Linux Kernel Virtualization: drivers/vhost/net.c vhost-net Zero-Copy TX & ubuf_info Async Completion Callback Engine
(drivers/vhost/net.c, drivers/vhost/vhost.c, include/linux/skbuff.h)
"""

import sys
import json

# Ensure UTF-8 streams on Windows
if sys.platform == "win32":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")


class VhostNetZeroCopyEngine:
    def __init__(self, config):
        self.max_zcopy_inflight = config.get("max_zcopy_inflight", 4)
        self.zcopy_min_threshold = config.get("zcopy_min_threshold", 512)
        self.copy_cost_cycles = config.get("copy_cost_cycles", 0.5)
        
        self.inflight_zcopy_count = 0
        self.active_transfers = {}
        self.used_ring = []
        
        self.total_tx_packets = 0
        self.zcopy_packets = 0
        self.copied_packets = 0
        self.zcopy_fallback_count = 0
        self.total_bytes_transmitted = 0
        self.bytes_copied = 0
        self.bytes_zerocopy = 0
        self.host_cpu_cycles_saved = 0
        self.virtqueue_kicks = 0

    def execute_command(self, cmd):
        op = cmd.get("op")
        if op == "SUBMIT_GUEST_TX":
            return self._submit_guest_tx(cmd)
        elif op == "NIC_DMA_COMPLETE":
            return self._nic_dma_complete(cmd)
        elif op == "FLUSH_USED_RING":
            return self._flush_used_ring(cmd)
        elif op == "GET_STATS":
            return self._get_stats(cmd)
        else:
            return {"op": op, "status": "UNKNOWN_OP"}

    def _submit_guest_tx(self, cmd):
        tx_id = cmd["tx_id"]
        desc_idx = cmd["desc_idx"]
        gpa = cmd.get("gpa", 0x100000)
        length = cmd["len"]
        
        self.total_tx_packets += 1
        self.total_bytes_transmitted += length
        
        if length < self.zcopy_min_threshold:
            mode = "COPY_THRESHOLD"
            self.copied_packets += 1
            self.bytes_copied += length
            self.used_ring.append({"desc_idx": desc_idx, "len": length})
            status = "TX_COPIED_IMMEDIATE_RETURN"
            ubuf_id = None
        else:
            if self.inflight_zcopy_count >= self.max_zcopy_inflight:
                mode = "COPY_FALLBACK"
                self.zcopy_fallback_count += 1
                self.copied_packets += 1
                self.bytes_copied += length
                self.used_ring.append({"desc_idx": desc_idx, "len": length})
                status = "TX_COPIED_FALLBACK"
                ubuf_id = None
            else:
                mode = "ZERO_COPY"
                self.inflight_zcopy_count += 1
                self.zcopy_packets += 1
                self.bytes_zerocopy += length
                ubuf_id = f"ubuf_{tx_id}"
                self.active_transfers[tx_id] = {
                    "tx_id": tx_id,
                    "desc_idx": desc_idx,
                    "gpa": gpa,
                    "len": length,
                    "mode": mode,
                    "ubuf_id": ubuf_id
                }
                status = "TX_ZERO_COPY_IN_FLIGHT"

        return {
            "op": "SUBMIT_GUEST_TX",
            "tx_id": tx_id,
            "desc_idx": desc_idx,
            "mode": mode,
            "len": length,
            "status": status,
            "inflight_zcopy": self.inflight_zcopy_count,
            "used_ring_pending": len(self.used_ring)
        }

    def _nic_dma_complete(self, cmd):
        tx_id = cmd["tx_id"]
        if tx_id not in self.active_transfers:
            return {"op": "NIC_DMA_COMPLETE", "tx_id": tx_id, "status": "ALREADY_COMPLETED_OR_NOT_FOUND"}
            
        trans = self.active_transfers.pop(tx_id)
        self.inflight_zcopy_count = max(0, self.inflight_zcopy_count - 1)
        saved_cycles = int(trans["len"] * self.copy_cost_cycles)
        self.host_cpu_cycles_saved += saved_cycles
        
        self.used_ring.append({"desc_idx": trans["desc_idx"], "len": trans["len"]})
        
        return {
            "op": "NIC_DMA_COMPLETE",
            "tx_id": tx_id,
            "desc_idx": trans["desc_idx"],
            "cycles_saved": saved_cycles,
            "inflight_zcopy": self.inflight_zcopy_count,
            "status": "ZERO_COPY_CALLBACK_COMPLETED"
        }

    def _flush_used_ring(self, cmd):
        count = len(self.used_ring)
        if count > 0:
            self.virtqueue_kicks += 1
            flushed_descs = [e["desc_idx"] for e in self.used_ring]
            self.used_ring.clear()
            status = "USED_RING_KICKED"
        else:
            flushed_descs = []
            status = "USED_RING_EMPTY"
            
        return {
            "op": "FLUSH_USED_RING",
            "descriptors_returned": count,
            "descriptors": flushed_descs,
            "virtqueue_kicks": self.virtqueue_kicks,
            "status": status
        }

    def _get_stats(self, cmd):
        return {
            "op": "GET_STATS",
            "total_tx_packets": self.total_tx_packets,
            "zcopy_packets": self.zcopy_packets,
            "copied_packets": self.copied_packets,
            "zcopy_fallback_count": self.zcopy_fallback_count,
            "total_bytes_transmitted": self.total_bytes_transmitted,
            "bytes_copied": self.bytes_copied,
            "bytes_zerocopy": self.bytes_zerocopy,
            "host_cpu_cycles_saved": self.host_cpu_cycles_saved,
            "inflight_zcopy_count": self.inflight_zcopy_count,
            "pending_used_ring": len(self.used_ring),
            "virtqueue_kicks": self.virtqueue_kicks
        }

    def run_trace(self, trace):
        results = []
        for cmd in trace:
            res = self.execute_command(cmd)
            results.append(res)
            
        summary = {
            "total_tx_packets": self.total_tx_packets,
            "zcopy_packets": self.zcopy_packets,
            "copied_packets": self.copied_packets,
            "zcopy_fallback_count": self.zcopy_fallback_count,
            "total_bytes_transmitted": self.total_bytes_transmitted,
            "bytes_copied": self.bytes_copied,
            "bytes_zerocopy": self.bytes_zerocopy,
            "host_cpu_cycles_saved": self.host_cpu_cycles_saved,
            "virtqueue_kicks": self.virtqueue_kicks
        }
        return {"events": results, "summary": summary}


def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    trace = data.get("trace", [])
    
    engine = VhostNetZeroCopyEngine(config)
    output = engine.run_trace(trace)
    print(json.dumps(output, separators=(',', ':'), ensure_ascii=False))


if __name__ == "__main__":
    solve()
