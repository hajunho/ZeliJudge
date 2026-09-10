# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #440 Solution:
Linux Kernel Networking: net/core/skbuff.c GSO / TSO Segmentation & skb_segment Slicing Engine
(net/core/skbuff.c, include/linux/skbuff.h, net/ipv4/tcp_output.c)
"""

import sys
import json
import math

# Ensure UTF-8 streams on Windows
if sys.platform == "win32":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")


class GsoSegmentationEngine:
    def __init__(self, config):
        self.hw_tso_enabled = config.get("hw_tso", False)
        self.default_mss = config.get("default_mss", 1448)
        self.header_len = config.get("header_len", 54)
        
        self.skbs = {}
        
        self.total_gso_skbs = 0
        self.hw_tso_dispatched = 0
        self.sw_gso_segmented = 0
        self.total_wire_packets = 0
        self.total_payload_bytes = 0

    def execute_command(self, cmd):
        op = cmd.get("op")
        if op == "ASSEMBLE_GSO_SKB":
            return self._assemble_gso_skb(cmd)
        elif op == "TRANSMIT_SKB":
            return self._transmit_skb(cmd)
        elif op == "GET_STATS":
            return self._get_stats(cmd)
        else:
            return {"op": op, "status": "UNKNOWN_OP"}

    def _assemble_gso_skb(self, cmd):
        skb_id = cmd["skb_id"]
        gso_size = cmd.get("gso_size", self.default_mss)
        ip_id_start = cmd.get("ip_id_start", 0x1000)
        tcp_seq_start = cmd.get("tcp_seq_start", 100000)
        tcp_flags = cmd.get("tcp_flags", ["ACK"])
        linear_len = cmd.get("linear_data_len", 0)
        frags = cmd.get("frags", [])
        
        frag_bytes = sum(f["size"] for f in frags)
        total_payload = linear_len + frag_bytes
        
        if total_payload == 0:
            gso_segs = 1
        else:
            gso_segs = math.ceil(total_payload / gso_size)
            
        skb_entry = {
            "skb_id": skb_id,
            "gso_size": gso_size,
            "gso_segs": gso_segs,
            "ip_id_start": ip_id_start,
            "tcp_seq_start": tcp_seq_start,
            "tcp_flags": tcp_flags,
            "linear_len": linear_len,
            "frags": frags,
            "total_payload": total_payload
        }
        self.skbs[skb_id] = skb_entry
        self.total_gso_skbs += 1
        
        return {
            "op": "ASSEMBLE_GSO_SKB",
            "skb_id": skb_id,
            "total_payload_bytes": total_payload,
            "gso_size": gso_size,
            "gso_segs": gso_segs,
            "num_frags": len(frags),
            "status": "GSO_SKB_ASSEMBLED"
        }

    def _transmit_skb(self, cmd):
        skb_id = cmd["skb_id"]
        if skb_id not in self.skbs:
            return {"op": "TRANSMIT_SKB", "skb_id": skb_id, "status": "NOT_FOUND"}
            
        skb = self.skbs.pop(skb_id)
        total_payload = skb["total_payload"]
        gso_size = skb["gso_size"]
        gso_segs = skb["gso_segs"]
        ip_id_start = skb["ip_id_start"]
        seq_start = skb["tcp_seq_start"]
        orig_flags = skb["tcp_flags"]
        
        self.total_payload_bytes += total_payload
        self.total_wire_packets += gso_segs
        
        wire_segments = []
        bytes_rem = total_payload
        cur_offset = 0
        
        chunks = []
        if skb["linear_len"] > 0:
            chunks.append({"type": "LINEAR", "pfn": None, "offset": 0, "size": skb["linear_len"]})
        for f in skb["frags"]:
            chunks.append({"type": "PAGE", "pfn": f["page_pfn"], "offset": f["offset"], "size": f["size"]})
            
        chunk_idx = 0
        chunk_sub_offset = 0
        
        for seg_idx in range(gso_segs):
            seg_len = min(gso_size, bytes_rem)
            bytes_rem -= seg_len
            is_last = (seg_idx == gso_segs - 1)
            
            seg_flags = []
            for flg in orig_flags:
                if flg in ("PSH", "FIN"):
                    if is_last:
                        seg_flags.append(flg)
                else:
                    seg_flags.append(flg)
                    
            seg_ip_id = (ip_id_start + seg_idx) & 0xFFFF
            seg_seq = seq_start + cur_offset
            
            seg_frags_used = []
            needed = seg_len
            while needed > 0 and chunk_idx < len(chunks):
                ch = chunks[chunk_idx]
                avail = ch["size"] - chunk_sub_offset
                take = min(needed, avail)
                
                if ch["type"] == "PAGE":
                    seg_frags_used.append({
                        "pfn": ch["pfn"],
                        "offset": ch["offset"] + chunk_sub_offset,
                        "size": take
                    })
                    
                needed -= take
                chunk_sub_offset += take
                if chunk_sub_offset >= ch["size"]:
                    chunk_idx += 1
                    chunk_sub_offset = 0
                    
            wire_segments.append({
                "seg_index": seg_idx,
                "ip_id": seg_ip_id,
                "tcp_seq": seg_seq,
                "payload_len": seg_len,
                "wire_len": seg_len + self.header_len,
                "tcp_flags": seg_flags,
                "is_last_seg": is_last,
                "frags_sliced": len(seg_frags_used)
            })
            cur_offset += seg_len
            
        if self.hw_tso_enabled:
            self.hw_tso_dispatched += 1
            mode = "NIC_HARDWARE_TSO_PASSTHROUGH"
            cpu_cycles_saved_est = gso_segs * 450
        else:
            self.sw_gso_segmented += 1
            mode = "SOFTWARE_GSO_SEGMENTED"
            cpu_cycles_saved_est = 0

        return {
            "op": "TRANSMIT_SKB",
            "skb_id": skb_id,
            "mode": mode,
            "total_payload_bytes": total_payload,
            "segments_emitted": gso_segs,
            "segments": wire_segments,
            "cpu_cycles_saved_est": cpu_cycles_saved_est
        }

    def _get_stats(self, cmd):
        return {
            "op": "GET_STATS",
            "hw_tso_enabled": self.hw_tso_enabled,
            "total_gso_skbs": self.total_gso_skbs,
            "hw_tso_dispatched": self.hw_tso_dispatched,
            "sw_gso_segmented": self.sw_gso_segmented,
            "total_wire_packets": self.total_wire_packets,
            "total_payload_bytes": self.total_payload_bytes
        }

    def run_trace(self, trace):
        results = []
        for cmd in trace:
            res = self.execute_command(cmd)
            results.append(res)
            
        summary = {
            "hw_tso_enabled": self.hw_tso_enabled,
            "total_gso_skbs": self.total_gso_skbs,
            "hw_tso_dispatched": self.hw_tso_dispatched,
            "sw_gso_segmented": self.sw_gso_segmented,
            "total_wire_packets": self.total_wire_packets,
            "total_payload_bytes": self.total_payload_bytes
        }
        return {"events": results, "summary": summary}


def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    trace = data.get("trace", [])
    
    engine = GsoSegmentationEngine(config)
    output = engine.run_trace(trace)
    print(json.dumps(output, separators=(',', ':'), ensure_ascii=False))


if __name__ == "__main__":
    solve()
