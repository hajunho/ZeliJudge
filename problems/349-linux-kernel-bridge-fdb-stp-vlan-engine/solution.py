import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def simulate_bridge_engine(input_data):
    bridge_config = input_data.get("bridge_config", {})
    ageing_time_sec = bridge_config.get("ageing_time_sec", 300)
    vlan_filtering = bridge_config.get("vlan_filtering", False)
    
    ports = {}
    for p_id, p_info in input_data.get("ports", {}).items():
        ports[p_id] = {
            "state": p_info.get("state", "FORWARDING"),
            "pvid": p_info.get("pvid", 1),
            "allowed_vlans": set(p_info.get("allowed_vlans", [1]))
        }
        
    fdb = {}
    for entry in input_data.get("initial_fdb", []):
        key = (entry["mac"].upper(), entry.get("vlan", 1) if vlan_filtering else 1)
        fdb[key] = {
            "port": entry["port"],
            "last_seen_sec": entry.get("last_seen_sec", 0),
            "is_static": entry.get("is_static", True)
        }
        
    events = input_data.get("events", [])
    
    stats = {
        "frames_received": 0,
        "frames_forwarded_unicast": 0,
        "frames_flooded": 0,
        "frames_dropped_port_state": 0,
        "frames_dropped_vlan": 0,
        "frames_filtered_same_port": 0,
        "mac_learned": 0,
        "mac_aged_out": 0,
        "tcn_events": 0
    }
    
    event_logs = []
    
    def purge_aged_fdb(current_time_sec, effective_ageing_sec):
        aged_keys = []
        for key, entry in fdb.items():
            if not entry["is_static"]:
                if (current_time_sec - entry["last_seen_sec"]) >= effective_ageing_sec:
                    aged_keys.append(key)
        for k in aged_keys:
            del fdb[k]
            stats["mac_aged_out"] += 1

    fast_ageing_until = -1

    for ev in events:
        etype = ev.get("type")
        timestamp = ev.get("timestamp_sec", 0)
        
        effective_ageing = 15 if (timestamp <= fast_ageing_until) else ageing_time_sec
        purge_aged_fdb(timestamp, effective_ageing)
        
        if etype == "FRAME_INGRESS":
            stats["frames_received"] += 1
            frame_id = ev["frame_id"]
            in_port = ev["in_port"]
            src_mac = ev["src_mac"].upper()
            dst_mac = ev["dst_mac"].upper()
            vlan_id = ev.get("vlan", 1)
            
            if in_port not in ports:
                continue
            port_state = ports[in_port]["state"]
            
            # 1. Ingress Port State Check
            if port_state in ["DISABLED", "BLOCKING"]:
                stats["frames_dropped_port_state"] += 1
                event_logs.append({
                    "event": "FRAME_INGRESS",
                    "frame_id": frame_id,
                    "in_port": in_port,
                    "action": "DROP_PORT_STATE",
                    "reason": f"Port state is {port_state}"
                })
                continue
                
            # 2. VLAN Ingress Filtering
            if vlan_filtering:
                if vlan_id not in ports[in_port]["allowed_vlans"]:
                    stats["frames_dropped_vlan"] += 1
                    event_logs.append({
                        "event": "FRAME_INGRESS",
                        "frame_id": frame_id,
                        "in_port": in_port,
                        "action": "DROP_VLAN_FILTERING",
                        "vlan": vlan_id
                    })
                    continue
                    
            # 3. Dynamic MAC Learning
            fdb_vlan = vlan_id if vlan_filtering else 1
            fdb_key = (src_mac, fdb_vlan)
            
            if fdb_key not in fdb or not fdb[fdb_key]["is_static"]:
                is_new = fdb_key not in fdb
                fdb[fdb_key] = {
                    "port": in_port,
                    "last_seen_sec": timestamp,
                    "is_static": False
                }
                if is_new:
                    stats["mac_learned"] += 1
                    
            # 4. Forwarding Check
            if port_state != "FORWARDING":
                event_logs.append({
                    "event": "FRAME_INGRESS",
                    "frame_id": frame_id,
                    "in_port": in_port,
                    "action": "LEARNED_NO_FORWARD",
                    "reason": f"Port state is {port_state}"
                })
                continue
                
            # 5. Destination Lookup & Forwarding Decision
            is_broadcast = (dst_mac == "FF:FF:FF:FF:FF:FF")
            is_multicast = dst_mac.startswith("01:00:5E") or dst_mac.startswith("33:33")
            
            target_key = (dst_mac, fdb_vlan)
            
            if is_broadcast or is_multicast or (target_key not in fdb):
                out_ports = []
                for p_id, p_data in ports.items():
                    if p_id != in_port and p_data["state"] == "FORWARDING":
                        if not vlan_filtering or (vlan_id in p_data["allowed_vlans"]):
                            out_ports.append(p_id)
                out_ports.sort()
                stats["frames_flooded"] += 1
                event_logs.append({
                    "event": "FRAME_INGRESS",
                    "frame_id": frame_id,
                    "in_port": in_port,
                    "action": "FLOOD",
                    "out_ports": out_ports,
                    "reason": "BROADCAST" if is_broadcast else ("MULTICAST" if is_multicast else "UNKNOWN_UNICAST")
                })
            else:
                dest_port = fdb[target_key]["port"]
                if dest_port == in_port:
                    stats["frames_filtered_same_port"] += 1
                    event_logs.append({
                        "event": "FRAME_INGRESS",
                        "frame_id": frame_id,
                        "in_port": in_port,
                        "action": "FILTER_SAME_PORT",
                        "reason": "Source and destination on same bridge port"
                    })
                else:
                    p_data = ports[dest_port]
                    if p_data["state"] != "FORWARDING":
                        stats["frames_dropped_port_state"] += 1
                        event_logs.append({
                            "event": "FRAME_INGRESS",
                            "frame_id": frame_id,
                            "in_port": in_port,
                            "action": "DROP_EGRESS_PORT_STATE",
                            "dest_port": dest_port
                        })
                    elif vlan_filtering and (vlan_id not in p_data["allowed_vlans"]):
                        stats["frames_dropped_vlan"] += 1
                        event_logs.append({
                            "event": "FRAME_INGRESS",
                            "frame_id": frame_id,
                            "in_port": in_port,
                            "action": "DROP_EGRESS_VLAN",
                            "dest_port": dest_port
                        })
                    else:
                        stats["frames_forwarded_unicast"] += 1
                        event_logs.append({
                            "event": "FRAME_INGRESS",
                            "frame_id": frame_id,
                            "in_port": in_port,
                            "action": "FORWARD_UNICAST",
                            "dest_port": dest_port
                        })
                        
        elif etype == "SET_PORT_STATE":
            p_id = ev["port"]
            new_state = ev["new_state"]
            if p_id in ports:
                ports[p_id]["state"] = new_state
                event_logs.append({
                    "event": "SET_PORT_STATE",
                    "port": p_id,
                    "new_state": new_state
                })
                
        elif etype == "TOPOLOGY_CHANGE_NOTIFICATION":
            forward_delay = ev.get("forward_delay_sec", 15)
            fast_ageing_until = timestamp + forward_delay
            stats["tcn_events"] += 1
            purge_aged_fdb(timestamp, 15)
            event_logs.append({
                "event": "TOPOLOGY_CHANGE_NOTIFICATION",
                "timestamp_sec": timestamp,
                "fast_ageing_until_sec": fast_ageing_until
            })

    fdb_dump = []
    for (mac, vlan), data in sorted(fdb.items(), key=lambda x: (x[0][1], x[0][0])):
        fdb_dump.append({
            "mac": mac,
            "vlan": vlan,
            "port": data["port"],
            "is_static": data["is_static"],
            "last_seen_sec": data["last_seen_sec"]
        })

    return {
        "stats": stats,
        "fdb_count": len(fdb_dump),
        "fdb": fdb_dump,
        "ports": {p: d["state"] for p, d in ports.items()},
        "event_logs": event_logs
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    result = simulate_bridge_engine(data)
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
