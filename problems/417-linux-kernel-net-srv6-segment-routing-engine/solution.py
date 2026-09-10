import sys
import json
import copy

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class SRv6Engine:
    def __init__(self, config):
        self.interfaces = config.get("interfaces", {})
        self.local_sids = config.get("local_sids", {})
        self.vrf_tables = config.get("vrf_tables", {})
        
        self.total_packets = 0
        self.srv6_encapsulated = 0
        self.srv6_decapsulated = 0
        self.sl_decremented = 0
        self.packets_forwarded = 0
        self.packets_dropped = 0
        self.vrf_routes_resolved = 0
        
        self.packet_logs = []
        self.event_logs = []

    def process_packet(self, current_time, pkt):
        self.total_packets += 1
        pkt = copy.deepcopy(pkt)
        pkt_id = pkt.get("id", self.total_packets)
        in_iface = pkt.get("in_iface", "eth0")
        
        encap_policy = pkt.get("encap_policy")
        if encap_policy:
            segments = encap_policy["segments"]
            sl = len(segments) - 1
            da = segments[sl]
            srh_size = 8 + 16 * len(segments)
            outer_ipv6_size = 40 + srh_size
            
            pkt["outer_ipv6"] = {
                "src": encap_policy.get("src", "fc00:0::1"),
                "dst": da,
                "srh": {
                    "segments": segments,
                    "segments_left": sl
                }
            }
            pkt["size"] = pkt.get("size", 100) + outer_ipv6_size
            self.srv6_encapsulated += 1
            self.event_logs.append({
                "time": current_time,
                "event": "SRV6_ENCAP",
                "pkt_id": pkt_id,
                "da": da,
                "sl": sl,
                "segments": segments
            })

        outer = pkt.get("outer_ipv6")
        if outer:
            da = outer["dst"]
            srh = outer.get("srh")
            
            if da in self.local_sids:
                sid_info = self.local_sids[da]
                action = sid_info["action"]
                
                if action == "End":
                    if srh and srh["segments_left"] > 0:
                        srh["segments_left"] -= 1
                        self.sl_decremented += 1
                        new_da = srh["segments"][srh["segments_left"]]
                        outer["dst"] = new_da
                        out_iface = sid_info.get("out_iface", "eth1")
                        self._forward(current_time, pkt_id, pkt, out_iface, f"End -> Next SID {new_da}")
                    else:
                        out_iface = sid_info.get("out_iface", "lo")
                        self._forward(current_time, pkt_id, pkt, out_iface, "End -> SL=0 Destination Reached")
                        
                elif action == "End.X":
                    if srh and srh["segments_left"] > 0:
                        srh["segments_left"] -= 1
                        self.sl_decremented += 1
                        new_da = srh["segments"][srh["segments_left"]]
                        outer["dst"] = new_da
                        out_iface = sid_info.get("out_iface", "eth2")
                        self._forward(current_time, pkt_id, pkt, out_iface, f"End.X -> Nexthop {sid_info.get('nexthop')} via {out_iface}")
                    else:
                        self._drop(current_time, pkt_id, pkt, "END_X_SL_UNDERFLOW")
                        
                elif action == "End.DT4":
                    vrf_name = sid_info.get("vrf", "default")
                    inner_payload = pkt.get("payload", {})
                    inner_dst = inner_payload.get("dst_ip", "10.0.0.1")
                    
                    pkt.pop("outer_ipv6", None)
                    self.srv6_decapsulated += 1
                    
                    out_iface = self._lookup_vrf(vrf_name, inner_dst)
                    if out_iface:
                        self.vrf_routes_resolved += 1
                        self._forward(current_time, pkt_id, pkt, out_iface, f"End.DT4 -> Decap & Forward via VRF {vrf_name} to {out_iface}")
                    else:
                        self._drop(current_time, pkt_id, pkt, f"VRF_ROUTE_NOT_FOUND_{vrf_name}")
                        
                elif action == "End.DX6":
                    pkt.pop("outer_ipv6", None)
                    self.srv6_decapsulated += 1
                    out_iface = sid_info.get("out_iface", "eth3")
                    self._forward(current_time, pkt_id, pkt, out_iface, f"End.DX6 -> Decap & Cross-connect to {out_iface}")
                else:
                    self._drop(current_time, pkt_id, pkt, f"UNKNOWN_SID_ACTION_{action}")
            else:
                out_iface = "eth1"
                self._forward(current_time, pkt_id, pkt, out_iface, f"Transit IPv6 routing to {da}")
        else:
            out_iface = "eth0"
            self._forward(current_time, pkt_id, pkt, out_iface, "Plain L3 Forward")

    def _lookup_vrf(self, vrf_name, dst_ip):
        routes = self.vrf_tables.get(vrf_name, [])
        for r in routes:
            prefix = r["prefix"]
            if dst_ip.startswith(prefix):
                return r["out_iface"]
        return None

    def _forward(self, current_time, pkt_id, pkt, out_iface, detail):
        if out_iface in self.interfaces:
            mtu = self.interfaces[out_iface].get("mtu", 1500)
            if pkt.get("size", 100) > mtu:
                self._drop(current_time, pkt_id, pkt, f"MTU_EXCEEDED (Size {pkt.get('size')} > MTU {mtu} on {out_iface})")
                return
                
        self.packets_forwarded += 1
        self.packet_logs.append({
            "time": current_time,
            "pkt_id": pkt_id,
            "status": "FORWARDED",
            "out_iface": out_iface,
            "detail": detail,
            "size": pkt.get("size", 100)
        })

    def _drop(self, current_time, pkt_id, pkt, reason):
        self.packets_dropped += 1
        self.packet_logs.append({
            "time": current_time,
            "pkt_id": pkt_id,
            "status": "DROPPED",
            "reason": reason,
            "size": pkt.get("size", 100)
        })

    def run_trace(self, trace):
        for ev in trace:
            t = ev.get("time", 0)
            if ev.get("type") == "PROCESS_PACKET":
                self.process_packet(t, ev["packet"])

    def get_result(self):
        return {
            "summary": {
                "total_packets": self.total_packets,
                "packets_forwarded": self.packets_forwarded,
                "packets_dropped": self.packets_dropped,
                "srv6_encapsulated": self.srv6_encapsulated,
                "srv6_decapsulated": self.srv6_decapsulated,
                "sl_decremented": self.sl_decremented,
                "vrf_routes_resolved": self.vrf_routes_resolved
            },
            "packet_logs": self.packet_logs,
            "event_logs": self.event_logs
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    trace = data.get("trace", [])
    
    engine = SRv6Engine(config)
    engine.run_trace(trace)
    result = engine.get_result()
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
