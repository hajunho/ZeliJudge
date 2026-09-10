import json
import sys

# Ensure UTF-8 input/output on Windows
if hasattr(sys.stdin, "reconfigure"):
    try:
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception:
        pass
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

def simulate():
    raw_data = sys.stdin.read().strip()
    if not raw_data:
        return
        
    payload = json.loads(raw_data)
    initial_state = payload.get("initial_state", {})
    events = payload.get("events", [])
    
    interfaces = {}
    init_ifaces = initial_state.get("interfaces", ["eth0", "eth1", "veth0"])
    for iface in init_ifaces:
        interfaces[iface] = {
            "ingress_filters": [],
            "egress_filters": [],
            "stats": {"rx_packets": 0, "tx_packets": 0, "dropped": 0, "redirected": 0, "mangled": 0}
        }
        
    history = []
    
    def process_skb(pkt, iface, hook):
        filters = interfaces[iface]["ingress_filters"] if hook == "INGRESS" else interfaces[iface]["egress_filters"]
        curr_pkt = dict(pkt)
        action = "TC_ACT_OK"
        target_iface = iface
        mangled = False
        dropped = False
        
        for flt in filters:
            for rule in flt.get("rules", []):
                match = True
                match_spec = rule.get("match", {})
                
                if "src_ip" in match_spec and curr_pkt.get("src_ip") != match_spec["src_ip"]:
                    match = False
                if "dst_ip" in match_spec and curr_pkt.get("dst_ip") != match_spec["dst_ip"]:
                    match = False
                if "dst_port" in match_spec and curr_pkt.get("dst_port") != match_spec["dst_port"]:
                    match = False
                if "protocol" in match_spec and curr_pkt.get("protocol") != match_spec["protocol"]:
                    match = False
                if "vlan_id" in match_spec and curr_pkt.get("vlan_id") != match_spec["vlan_id"]:
                    match = False
                    
                if match:
                    act_spec = rule.get("action", {})
                    action_type = act_spec.get("type", "TC_ACT_OK")
                    
                    if "set_dst_ip" in act_spec:
                        curr_pkt["dst_ip"] = act_spec["set_dst_ip"]
                        mangled = True
                    if "set_src_ip" in act_spec:
                        curr_pkt["src_ip"] = act_spec["set_src_ip"]
                        mangled = True
                    if "set_mark" in act_spec:
                        curr_pkt["mark"] = act_spec["set_mark"]
                        mangled = True
                    if "set_priority" in act_spec:
                        curr_pkt["priority"] = act_spec["set_priority"]
                        mangled = True
                    if "vlan_pop" in act_spec and act_spec["vlan_pop"]:
                        curr_pkt["vlan_id"] = None
                        mangled = True
                    if "vlan_push" in act_spec:
                        curr_pkt["vlan_id"] = act_spec["vlan_push"]
                        mangled = True
                        
                    action = action_type
                    if action_type == "TC_ACT_SHOT":
                        dropped = True
                        return action, target_iface, mangled, dropped, curr_pkt
                    elif action_type == "TC_ACT_REDIRECT":
                        target_iface = act_spec.get("target_iface", iface)
                        return action, target_iface, mangled, dropped, curr_pkt
                    elif action_type == "TC_ACT_OK":
                        return action, target_iface, mangled, dropped, curr_pkt
                        
        return action, target_iface, mangled, dropped, curr_pkt

    for ep_idx, ev in enumerate(events):
        ev_type = ev["type"]
        ev_params = ev.get("params", {})
        
        status = "OK"
        detail = ""
        
        if ev_type == "ATTACH_FILTER":
            iface = ev_params["iface"]
            hook = ev_params.get("hook", "INGRESS")
            filter_name = ev_params["filter_name"]
            rules = ev_params.get("rules", [])
            
            if iface in interfaces:
                target_list = interfaces[iface]["ingress_filters"] if hook == "INGRESS" else interfaces[iface]["egress_filters"]
                target_list.append({"name": filter_name, "rules": rules})
                status = "FILTER_ATTACHED"
                detail = f"cls_bpf filter {filter_name} attached to {iface} {hook}."
            else:
                status = "IFACE_NOT_FOUND"
                
        elif ev_type == "DETACH_FILTER":
            iface = ev_params["iface"]
            hook = ev_params.get("hook", "INGRESS")
            filter_name = ev_params["filter_name"]
            
            if iface in interfaces:
                target_list = interfaces[iface]["ingress_filters"] if hook == "INGRESS" else interfaces[iface]["egress_filters"]
                interfaces[iface]["ingress_filters" if hook == "INGRESS" else "egress_filters"] = [
                    f for f in target_list if f["name"] != filter_name
                ]
                status = "FILTER_DETACHED"
                detail = f"cls_bpf filter {filter_name} detached from {iface} {hook}."
            else:
                status = "IFACE_NOT_FOUND"
                
        elif ev_type == "INGRESS_PACKET":
            iface = ev_params["iface"]
            pkt = ev_params["packet"]
            
            if iface in interfaces:
                interfaces[iface]["stats"]["rx_packets"] += 1
                action, target_iface, mangled, dropped, out_pkt = process_skb(pkt, iface, "INGRESS")
                
                if mangled:
                    interfaces[iface]["stats"]["mangled"] += 1
                    
                if dropped:
                    interfaces[iface]["stats"]["dropped"] += 1
                    status = "PACKET_DROPPED"
                    detail = f"Packet {pkt.get('id')} dropped by TC_ACT_SHOT on {iface} INGRESS."
                elif action == "TC_ACT_REDIRECT":
                    interfaces[iface]["stats"]["redirected"] += 1
                    if target_iface in interfaces:
                        interfaces[target_iface]["stats"]["tx_packets"] += 1
                    status = "PACKET_REDIRECTED"
                    detail = f"Packet {pkt.get('id')} redirected to {target_iface}."
                else:
                    status = "PACKET_PASSED"
                    detail = f"Packet {pkt.get('id')} passed through {iface} INGRESS (mangled={mangled})."
            else:
                status = "IFACE_NOT_FOUND"
                
        elif ev_type == "EGRESS_PACKET":
            iface = ev_params["iface"]
            pkt = ev_params["packet"]
            
            if iface in interfaces:
                action, target_iface, mangled, dropped, out_pkt = process_skb(pkt, iface, "EGRESS")
                
                if mangled:
                    interfaces[iface]["stats"]["mangled"] += 1
                    
                if dropped:
                    interfaces[iface]["stats"]["dropped"] += 1
                    status = "PACKET_DROPPED"
                    detail = f"Packet {pkt.get('id')} dropped by TC_ACT_SHOT on {iface} EGRESS."
                elif action == "TC_ACT_REDIRECT":
                    interfaces[iface]["stats"]["redirected"] += 1
                    if target_iface in interfaces:
                        interfaces[target_iface]["stats"]["tx_packets"] += 1
                    status = "PACKET_REDIRECTED"
                    detail = f"Packet {pkt.get('id')} redirected to {target_iface}."
                else:
                    interfaces[iface]["stats"]["tx_packets"] += 1
                    status = "PACKET_TRANSMITTED"
                    detail = f"Packet {pkt.get('id')} transmitted on {iface} EGRESS (mangled={mangled})."
            else:
                status = "IFACE_NOT_FOUND"
                
        history.append({
            "epoch": ep_idx + 1,
            "event": ev_type,
            "status": status,
            "detail": detail
        })
        
    result = {
        "interfaces": {
            if_name: {
                "stats": if_data["stats"],
                "ingress_filter_count": len(if_data["ingress_filters"]),
                "egress_filter_count": len(if_data["egress_filters"])
            } for if_name, if_data in sorted(interfaces.items())
        },
        "total_dropped": sum(d["stats"]["dropped"] for d in interfaces.values()),
        "total_redirected": sum(d["stats"]["redirected"] for d in interfaces.values()),
        "total_mangled": sum(d["stats"]["mangled"] for d in interfaces.values()),
        "history": history
    }
    
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    simulate()
