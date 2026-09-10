import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)
    
    pf_config = input_data.get("pf_config", {})
    total_vfs = pf_config.get("total_vfs", 8)
    num_vfs_enabled = pf_config.get("num_vfs_enabled", 0)
    max_queues_total = pf_config.get("max_queues_total", 64)
    mbx_rate_limit = pf_config.get("mbx_rate_limit", 10)
    
    vfs = {}
    vf_admin_configs = input_data.get("vf_configurations", [])
    for cfg in vf_admin_configs:
        vfid = cfg.get("vf_id")
        vfs[vfid] = {
            "vf_id": vfid,
            "mac": cfg.get("mac", f"52:54:00:12:34:{vfid:02x}"),
            "vlan": cfg.get("vlan", 0),
            "spoofcheck": cfg.get("spoofcheck", True),
            "trust": cfg.get("trust", False),
            "link_state": cfg.get("link_state", "auto"),
            "promisc": False,
            "admin_mac_locked": bool(cfg.get("mac")),
            "admin_vlan_locked": (cfg.get("vlan", 0) != 0)
        }
        
    queues_per_vf = max_queues_total // (num_vfs_enabled + 1) if num_vfs_enabled > 0 else 0
    
    transactions = input_data.get("transactions", [])
    results = []
    
    vf_txn_count = {}
    spoof_drops = 0
    promisc_denials = 0
    mac_denials = 0
    mbx_floods = 0
    ack_count = 0
    nack_count = 0
    
    for txn in transactions:
        tid = txn.get("txn_id")
        vfid = txn.get("vf_id")
        msg_type = txn.get("msg_type")
        params = txn.get("params", {})
        
        if vfid >= num_vfs_enabled:
            results.append({
                "txn_id": tid,
                "vf_id": vfid,
                "status": "NACK",
                "err_code": -19,
                "reason": "VF_NOT_ENABLED"
            })
            nack_count += 1
            continue
            
        vf = vfs.get(vfid)
        if not vf:
            results.append({
                "txn_id": tid,
                "vf_id": vfid,
                "status": "NACK",
                "err_code": -22,
                "reason": "VF_CONFIG_NOT_FOUND"
            })
            nack_count += 1
            continue
            
        count = vf_txn_count.get(vfid, 0)
        if count >= mbx_rate_limit:
            mbx_floods += 1
            results.append({
                "txn_id": tid,
                "vf_id": vfid,
                "status": "NACK",
                "err_code": -16,
                "reason": "MBX_RATE_LIMIT_EXCEEDED"
            })
            nack_count += 1
            continue
        vf_txn_count[vfid] = count + 1
        
        if msg_type == "VF_RESET":
            vf["promisc"] = False
            results.append({
                "txn_id": tid,
                "vf_id": vfid,
                "status": "ACK",
                "err_code": 0,
                "data": {"queues_allocated": queues_per_vf, "link_up": (vf["link_state"] != "disable")}
            })
            ack_count += 1
            
        elif msg_type == "VF_GET_QUEUES":
            results.append({
                "txn_id": tid,
                "vf_id": vfid,
                "status": "ACK",
                "err_code": 0,
                "data": {
                    "num_queues": queues_per_vf,
                    "default_vlan": vf["vlan"],
                    "spoofcheck": vf["spoofcheck"],
                    "trust": vf["trust"]
                }
            })
            ack_count += 1
            
        elif msg_type == "VF_SET_MAC":
            req_mac = params.get("mac")
            if not vf["trust"] and vf["admin_mac_locked"] and req_mac.lower() != vf["mac"].lower():
                mac_denials += 1
                results.append({
                    "txn_id": tid,
                    "vf_id": vfid,
                    "status": "NACK",
                    "err_code": -1,
                    "reason": "MAC_CHANGE_DENIED_UNTRUSTED_VF"
                })
                nack_count += 1
            else:
                vf["mac"] = req_mac
                results.append({
                    "txn_id": tid,
                    "vf_id": vfid,
                    "status": "ACK",
                    "err_code": 0,
                    "data": {"configured_mac": req_mac}
                })
                ack_count += 1
                
        elif msg_type == "VF_SET_VLAN":
            req_vlan = params.get("vlan", 0)
            if not vf["trust"] and vf["admin_vlan_locked"] and req_vlan != vf["vlan"]:
                results.append({
                    "txn_id": tid,
                    "vf_id": vfid,
                    "status": "NACK",
                    "err_code": -1,
                    "reason": "VLAN_CHANGE_DENIED_ADMIN_ASSIGNED"
                })
                nack_count += 1
            else:
                vf["vlan"] = req_vlan
                results.append({
                    "txn_id": tid,
                    "vf_id": vfid,
                    "status": "ACK",
                    "err_code": 0,
                    "data": {"vlan": req_vlan}
                })
                ack_count += 1
                
        elif msg_type == "VF_SET_PROMISC":
            req_promisc = params.get("promisc", True)
            if not vf["trust"]:
                promisc_denials += 1
                results.append({
                    "txn_id": tid,
                    "vf_id": vfid,
                    "status": "NACK",
                    "err_code": -1,
                    "reason": "PROMISCUOUS_MODE_DENIED_UNTRUSTED_VF"
                })
                nack_count += 1
            else:
                vf["promisc"] = req_promisc
                results.append({
                    "txn_id": tid,
                    "vf_id": vfid,
                    "status": "ACK",
                    "err_code": 0,
                    "data": {"promisc": req_promisc}
                })
                ack_count += 1
                
        elif msg_type == "VF_SEND_PACKET":
            src_mac = params.get("src_mac", "")
            if vf["link_state"] == "disable":
                results.append({
                    "txn_id": tid,
                    "vf_id": vfid,
                    "status": "NACK",
                    "err_code": -100,
                    "reason": "LINK_DOWN_ADMINISTRATIVELY_DISABLED"
                })
                nack_count += 1
            elif vf["spoofcheck"] and src_mac.lower() != vf["mac"].lower():
                spoof_drops += 1
                results.append({
                    "txn_id": tid,
                    "vf_id": vfid,
                    "status": "NACK",
                    "err_code": -111,
                    "reason": "PACKET_DROPPED_SPOOFCHECK_VIOLATION"
                })
                nack_count += 1
            else:
                results.append({
                    "txn_id": tid,
                    "vf_id": vfid,
                    "status": "ACK",
                    "err_code": 0,
                    "data": {"packet_forwarded": True, "vlan_tagged": vf["vlan"]}
                })
                ack_count += 1
        else:
            results.append({
                "txn_id": tid,
                "vf_id": vfid,
                "status": "NACK",
                "err_code": -22,
                "reason": "UNKNOWN_MAILBOX_COMMAND"
            })
            nack_count += 1
            
    if spoof_drops > 0 or promisc_denials > 0 or mac_denials > 0 or mbx_floods > 0:
        verdict = "VF_SECURITY_VIOLATION_CONTAINED"
    elif nack_count == 0 and ack_count > 0:
        verdict = "SRIOV_FABRIC_OPTIMAL"
    else:
        verdict = "SRIOV_CONFIGURATION_FAULT"
        
    output = {
        "engine": "pcie_sriov_pf_vf_mailbox",
        "metrics": {
            "total_transactions": len(transactions),
            "acks_issued": ack_count,
            "nacks_issued": nack_count,
            "spoof_drops": spoof_drops,
            "promisc_denials": promisc_denials,
            "mac_denials": mac_denials,
            "mbx_rate_limit_mitigations": mbx_floods,
            "queues_per_vf": queues_per_vf
        },
        "verdict": verdict,
        "results": results
    }
    
    print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))

if __name__ == "__main__":
    solve()
