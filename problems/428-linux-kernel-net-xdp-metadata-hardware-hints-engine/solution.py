import sys
import json

class XDPMetadataHintsEngine:
    def __init__(self, config=None):
        config = config or {}
        self.default_headroom = config.get("headroom", 64)
        
        self.packets = {}
        
        self.packets_received = 0
        self.meta_adjusted_count = 0
        self.xdp_pass_count = 0
        self.xdp_drop_count = 0
        self.xdp_redirect_count = 0
        self.hardware_csum_offloaded = 0
        self.software_csum_fallbacks = 0
        self.headroom_exhaustions = 0
        
        self.forwarded_skbs = []
        self.event_logs = []

    def nic_rx_packet(self, current_time, pkt_id, data_len, hw_csum_valid, hw_rx_hash, hw_timestamp_ns, vlan_tag=None):
        self.packets[pkt_id] = {
            "pkt_id": pkt_id,
            "data_len": data_len,
            "hw_csum_valid": hw_csum_valid,
            "hw_rx_hash": hw_rx_hash,
            "hw_timestamp_ns": hw_timestamp_ns,
            "vlan_tag": vlan_tag,
            "headroom": self.default_headroom,
            "meta_len": 0,
            "meta_payload": {}
        }
        self.packets_received += 1
        self.event_logs.append({
            "time": current_time,
            "event": "NIC_RX_PACKET",
            "pkt_id": pkt_id,
            "len": data_len,
            "hw_csum_valid": hw_csum_valid
        })

    def bpf_xdp_adjust_meta(self, current_time, pkt_id, delta):
        if pkt_id not in self.packets:
            return -1
        pkt = self.packets[pkt_id]
        needed = abs(delta)
        if delta < 0:
            if needed > pkt["headroom"]:
                self.headroom_exhaustions += 1
                self.event_logs.append({
                    "time": current_time,
                    "event": "XDP_META_ERROR",
                    "pkt_id": pkt_id,
                    "error": "ENOSPC_HEADROOM_EXHAUSTED",
                    "needed": needed,
                    "available": pkt["headroom"]
                })
                return -28
            pkt["headroom"] -= needed
            pkt["meta_len"] += needed
            self.meta_adjusted_count += 1
            self.event_logs.append({
                "time": current_time,
                "event": "BPF_XDP_ADJUST_META_SUCCESS",
                "pkt_id": pkt_id,
                "meta_len": pkt["meta_len"],
                "remaining_headroom": pkt["headroom"]
            })
            return 0
        else:
            if delta > pkt["meta_len"]:
                return -22
            pkt["meta_len"] -= delta
            pkt["headroom"] += delta
            return 0

    def populate_metadata_hints(self, current_time, pkt_id, fields):
        if pkt_id not in self.packets:
            return
        pkt = self.packets[pkt_id]
        if pkt["meta_len"] == 0:
            self.event_logs.append({
                "time": current_time,
                "event": "XDP_META_ERROR",
                "pkt_id": pkt_id,
                "error": "NO_METADATA_SPACE_ALLOCATED"
            })
            return
            
        for f in fields:
            if f == "RX_CSUM":
                pkt["meta_payload"]["csum_valid"] = pkt["hw_csum_valid"]
            elif f == "RX_HASH":
                pkt["meta_payload"]["rx_hash"] = pkt["hw_rx_hash"]
            elif f == "TIMESTAMP":
                pkt["meta_payload"]["timestamp_ns"] = pkt["hw_timestamp_ns"]
            elif f == "VLAN":
                pkt["meta_payload"]["vlan_tag"] = pkt["vlan_tag"]
                
        self.event_logs.append({
            "time": current_time,
            "event": "METADATA_HINTS_POPULATED",
            "pkt_id": pkt_id,
            "populated_fields": sorted(list(pkt["meta_payload"].keys()))
        })

    def xdp_return(self, current_time, pkt_id, action):
        if pkt_id not in self.packets:
            return
        pkt = self.packets[pkt_id]
        
        if action == "XDP_DROP":
            self.xdp_drop_count += 1
            self.event_logs.append({
                "time": current_time,
                "event": "XDP_ACTION_DROP",
                "pkt_id": pkt_id
            })
        elif action == "XDP_REDIRECT":
            self.xdp_redirect_count += 1
            self.event_logs.append({
                "time": current_time,
                "event": "XDP_ACTION_REDIRECT",
                "pkt_id": pkt_id,
                "meta_forwarded": pkt["meta_len"] > 0
            })
        elif action == "XDP_PASS":
            self.xdp_pass_count += 1
            skb = {
                "pkt_id": pkt_id,
                "len": pkt["data_len"],
                "ip_summed": "CHECKSUM_NONE",
                "hash": None,
                "timestamp_ns": None,
                "vlan_tag": None
            }
            
            if pkt["meta_payload"].get("csum_valid") is True:
                skb["ip_summed"] = "CHECKSUM_UNNECESSARY"
                self.hardware_csum_offloaded += 1
            else:
                skb["ip_summed"] = "CHECKSUM_NONE"
                self.software_csum_fallbacks += 1
                
            if "rx_hash" in pkt["meta_payload"]:
                skb["hash"] = pkt["meta_payload"]["rx_hash"]
            if "timestamp_ns" in pkt["meta_payload"]:
                skb["timestamp_ns"] = pkt["meta_payload"]["timestamp_ns"]
            if "vlan_tag" in pkt["meta_payload"]:
                skb["vlan_tag"] = pkt["meta_payload"]["vlan_tag"]
                
            self.forwarded_skbs.append(skb)
            self.event_logs.append({
                "time": current_time,
                "event": "XDP_PASS_SKB_ALLOCATED",
                "pkt_id": pkt_id,
                "ip_summed": skb["ip_summed"],
                "csum_offloaded": skb["ip_summed"] == "CHECKSUM_UNNECESSARY"
            })

    def run_trace(self, trace):
        for ev in trace:
            t = ev.get("time", 0)
            ev_type = ev.get("type")
            if ev_type == "NIC_RX_PACKET":
                self.nic_rx_packet(t, ev["pkt_id"], ev["data_len"], ev["hw_csum_valid"], ev["hw_rx_hash"], ev["hw_timestamp_ns"], ev.get("vlan_tag"))
            elif ev_type == "BPF_XDP_ADJUST_META":
                self.bpf_xdp_adjust_meta(t, ev["pkt_id"], ev["delta"])
            elif ev_type == "POPULATE_METADATA_HINTS":
                self.populate_metadata_hints(t, ev["pkt_id"], ev["fields"])
            elif ev_type == "XDP_RETURN":
                self.xdp_return(t, ev["pkt_id"], ev["action"])

    def get_result(self):
        return {
            "summary": {
                "packets_received": self.packets_received,
                "meta_adjusted_count": self.meta_adjusted_count,
                "xdp_pass_count": self.xdp_pass_count,
                "xdp_drop_count": self.xdp_drop_count,
                "xdp_redirect_count": self.xdp_redirect_count,
                "hardware_csum_offloaded": self.hardware_csum_offloaded,
                "software_csum_fallbacks": self.software_csum_fallbacks,
                "headroom_exhaustions": self.headroom_exhaustions
            },
            "forwarded_skbs": self.forwarded_skbs,
            "event_logs": self.event_logs
        }

def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    
    engine = XDPMetadataHintsEngine(data.get("config", {}))
    engine.run_trace(data.get("trace", []))
    res = engine.get_result()
    print(json.dumps(res, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
