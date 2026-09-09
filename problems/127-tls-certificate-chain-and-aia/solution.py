import sys
import json
import copy

def validate_tls_chain(data):
    data = copy.deepcopy(data)
    trust_stores = data.get("client_trust_stores", {})
    aia_repo = data.get("intermediate_ca_repository", {})
    scenarios = data.get("scenarios", [])
    
    results = []
    
    for sc in scenarios:
        sc_id = sc.get("scenario_id", "")
        client_type = sc.get("client_type", "modern_browser")
        allow_aia = sc.get("allow_aia_fetching", False)
        current_time = sc.get("current_time", 0)
        server_chain = sc.get("server_sent_chain", [])
        
        trust_store = trust_stores.get(client_type, [])
        
        if not server_chain:
            results.append({
                "scenario_id": sc_id,
                "client_type": client_type,
                "status": "VERIFICATION_FAILED",
                "error": "EMPTY_SERVER_CHAIN",
                "error_detail": "Server did not send any certificates in TLS handshake",
                "resolved_chain": [],
                "aia_downloads": []
            })
            continue
            
        leaf_cert = server_chain[0]
        resolved_chain = []
        aia_downloads = []
        
        curr = leaf_cert
        failed = False
        error_msg = None
        error_detail = None
        
        visited_subjects = set()
        
        while True:
            # Check validity period of curr
            v_from = curr.get("valid_from", 0)
            v_to = curr.get("valid_to", float("inf"))
            
            if current_time < v_from:
                failed = True
                error_msg = "CERTIFICATE_NOT_YET_VALID"
                error_detail = f"Certificate {curr.get('subject')} is not valid until {v_from}"
                resolved_chain.append(curr.get("subject"))
                break
            if current_time > v_to:
                failed = True
                error_msg = "CERTIFICATE_EXPIRED"
                error_detail = f"Certificate {curr.get('subject')} expired at {v_to}"
                resolved_chain.append(curr.get("subject"))
                break
                
            resolved_chain.append(curr.get("subject"))
            visited_subjects.add(curr.get("subject"))
            
            # Check if curr is in client trust store
            trusted_root = next((r for r in trust_store if r.get("subject") == curr.get("subject")), None)
            if trusted_root:
                # Reached trust anchor!
                r_to = trusted_root.get("valid_to", float("inf"))
                if current_time > r_to:
                    failed = True
                    error_msg = "ROOT_CA_EXPIRED"
                    error_detail = f"Root CA {trusted_root.get('subject')} expired at {r_to}"
                break
                
            # If self-signed but not in trust store
            if curr.get("issuer") == curr.get("subject"):
                failed = True
                error_msg = "UNTRUSTED_ROOT_CA"
                error_detail = f"Self-signed root {curr.get('subject')} is not in client trust store"
                break
                
            # Look for issuer in server_chain
            issuer_subject = curr.get("issuer")
            next_cert = next((c for c in server_chain if c.get("subject") == issuer_subject), None)
            
            if not next_cert:
                # Check if trust store has a root matching issuer directly
                trusted_root = next((r for r in trust_store if r.get("subject") == issuer_subject), None)
                if trusted_root:
                    resolved_chain.append(trusted_root.get("subject"))
                    r_to = trusted_root.get("valid_to", float("inf"))
                    if current_time > r_to:
                        failed = True
                        error_msg = "ROOT_CA_EXPIRED"
                        error_detail = f"Trust anchor {trusted_root.get('subject')} expired at {r_to}"
                    break
                    
                # If not in trust store, try AIA fetching
                aia_url = curr.get("aia_ca_issuers_url")
                if allow_aia and aia_url and aia_url in aia_repo:
                    fetched = aia_repo[aia_url]
                    aia_downloads.append({"url": aia_url, "downloaded_subject": fetched.get("subject")})
                    next_cert = fetched
                else:
                    failed = True
                    error_msg = "MISSING_INTERMEDIATE_CA"
                    error_detail = f"Unable to find intermediate CA for {issuer_subject} (AIA fetching: {allow_aia})"
                    break
                    
            if next_cert.get("subject") in visited_subjects:
                failed = True
                error_msg = "CERTIFICATE_LOOP_DETECTED"
                error_detail = f"Loop detected at {next_cert.get('subject')}"
                break
                
            curr = next_cert
            
        results.append({
            "scenario_id": sc_id,
            "client_type": client_type,
            "status": "VERIFICATION_FAILED" if failed else "VERIFICATION_SUCCESS",
            "error": error_msg,
            "error_detail": error_detail,
            "resolved_chain": resolved_chain,
            "aia_downloads": aia_downloads
        })
        
    summary = {
        "total_scenarios": len(results),
        "successful_verifications": sum(1 for r in results if r["status"] == "VERIFICATION_SUCCESS"),
        "failed_verifications": sum(1 for r in results if r["status"] == "VERIFICATION_FAILED"),
        "missing_intermediate_ca_errors": sum(1 for r in results if r["error"] == "MISSING_INTERMEDIATE_CA"),
        "expired_certificate_errors": sum(1 for r in results if r["error"] in ("CERTIFICATE_EXPIRED", "ROOT_CA_EXPIRED"))
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
    out = validate_tls_chain(data)
    print(json.dumps(out, indent=2))

if __name__ == "__main__":
    main()
