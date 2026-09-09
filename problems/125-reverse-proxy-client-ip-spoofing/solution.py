import sys
import json
import ipaddress
import re

def clean_ip_str(raw):
    s = str(raw).strip()
    if s.startswith("[") and "]" in s:
        close_idx = s.find("]")
        return s[1:close_idx]
    if ":" in s and s.count(":") == 1:
        return s.split(":")[0]
    return s

def is_ip_in_list(ip_str, network_list):
    cleaned = clean_ip_str(ip_str)
    try:
        ip = ipaddress.ip_address(cleaned)
    except ValueError:
        return False
        
    for net_str in network_list:
        s = str(net_str).strip()
        try:
            if "/" in s:
                net = ipaddress.ip_network(s, strict=False)
                if ip in net:
                    return True
            else:
                target_ip = ipaddress.ip_address(clean_ip_str(s))
                if ip == target_ip:
                    return True
        except ValueError:
            continue
    return False

def extract_xff_ips(headers):
    # Check X-Forwarded-For
    xff = headers.get("X-Forwarded-For") or headers.get("x-forwarded-for")
    if xff:
        parts = [clean_ip_str(p) for p in str(xff).split(",") if p.strip()]
        return parts
        
    # Check RFC 7239 Forwarded header
    fwd = headers.get("Forwarded") or headers.get("forwarded")
    if fwd:
        matches = re.findall(r'for=(?:"?\[?([0-9a-zA-Z.:]+)\]?"?)', str(fwd), re.IGNORECASE)
        if matches:
            return [clean_ip_str(m) for m in matches if m.strip()]
            
    return []

def resolve_client_ip(socket_remote_addr, xff_ips, trusted_proxies):
    clean_socket = clean_ip_str(socket_remote_addr)
    naive_client_ip = clean_ip_str(xff_ips[0]) if xff_ips else clean_socket
    
    hop_trace = []
    is_socket_trusted = is_ip_in_list(clean_socket, trusted_proxies)
    hop_trace.append({"ip": clean_socket, "trusted": is_socket_trusted})
    
    if not is_socket_trusted:
        resolved_client_ip = clean_socket
        hop_trace[-1]["decision"] = "REAL_CLIENT"
    else:
        resolved_client_ip = clean_socket
        found_client = False
        for raw_ip in reversed(xff_ips):
            ip = clean_ip_str(raw_ip)
            is_trusted = is_ip_in_list(ip, trusted_proxies)
            hop_trace.append({"ip": ip, "trusted": is_trusted})
            if not is_trusted:
                resolved_client_ip = ip
                hop_trace[-1]["decision"] = "REAL_CLIENT"
                found_client = True
                break
        if not found_client and xff_ips:
            resolved_client_ip = clean_ip_str(xff_ips[0])
            hop_trace[-1]["decision"] = "REAL_CLIENT_ALL_TRUSTED"
            
    is_spoofing_detected = (naive_client_ip != resolved_client_ip) and bool(xff_ips)
    return resolved_client_ip, naive_client_ip, is_spoofing_detected, hop_trace

def process_security_inspection(data):
    trusted_proxies = data.get("trusted_proxies", [])
    admin_whitelist = data.get("admin_whitelist", [])
    requests = data.get("requests", [])
    
    results = []
    for req in requests:
        req_id = req.get("request_id", "")
        endpoint = req.get("target_endpoint", "/")
        socket_remote = req.get("socket_remote_addr", "127.0.0.1")
        headers = req.get("headers", {})
        
        xff_ips = extract_xff_ips(headers)
        resolved_ip, naive_ip, is_spoof, trace = resolve_client_ip(socket_remote, xff_ips, trusted_proxies)
        
        is_admin = endpoint.startswith("/admin")
        secure_admin_allowed = is_ip_in_list(resolved_ip, admin_whitelist)
        naive_admin_allowed = is_ip_in_list(naive_ip, admin_whitelist)
        
        if is_admin:
            if secure_admin_allowed:
                access_granted = True
                reason = "ADMIN_AUTHORIZED"
            else:
                access_granted = False
                reason = "ADMIN_FORBIDDEN"
        else:
            access_granted = True
            reason = "PUBLIC_ACCESS"
            
        spoof_prevented = bool(is_admin and naive_admin_allowed and not secure_admin_allowed)
        
        results.append({
            "request_id": req_id,
            "target_endpoint": endpoint,
            "socket_remote_addr": socket_remote,
            "resolved_client_ip": resolved_ip,
            "naive_client_ip": naive_ip,
            "is_spoofing_detected": is_spoof,
            "spoof_prevented": spoof_prevented,
            "access_granted": access_granted,
            "reason": reason,
            "hop_trace": trace
        })
        
    summary = {
        "total_requests": len(results),
        "admin_requests": sum(1 for r in results if r["target_endpoint"].startswith("/admin")),
        "admin_authorized": sum(1 for r in results if r["reason"] == "ADMIN_AUTHORIZED"),
        "admin_forbidden": sum(1 for r in results if r["reason"] == "ADMIN_FORBIDDEN"),
        "spoofing_attempts_detected": sum(1 for r in results if r["is_spoofing_detected"]),
        "spoofing_attacks_prevented": sum(1 for r in results if r["spoof_prevented"])
    }
    
    return {
        "summary": summary,
        "results": results
    }

def main():
    input_data = sys.stdin.read().strip()
    if not input_data:
        return
    data = json.loads(input_data)
    out = process_security_inspection(data)
    print(json.dumps(out, indent=2))

if __name__ == "__main__":
    main()
