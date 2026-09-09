import json
import sys
import urllib.parse

def get_etld_plus_one(host):
    if not host:
        return ""
    host = host.split(":")[0].lower()
    parts = host.split(".")
    if len(parts) <= 1:
        return host
    if all(p.isdigit() for p in parts) and len(parts) == 4:
        return host
    two_part_tlds = {
        "co.kr", "ne.kr", "or.kr", "re.kr", "pe.kr", "go.kr",
        "co.uk", "org.uk", "ac.uk", "gov.uk", "me.uk",
        "com.au", "net.au", "org.au", "edu.au",
        "co.jp", "ne.jp", "or.jp", "ac.jp", "go.jp"
    }
    if len(parts) >= 3:
        last_two = f"{parts[-2]}.{parts[-1]}"
        if last_two in two_part_tlds:
            return f"{parts[-3]}.{last_two}"
    return f"{parts[-2]}.{parts[-1]}"

def solve(data):
    browser_mode = data.get("browser_mode", "CHROME_80_PLUS")
    stored_cookies = data.get("stored_cookies", [])
    scenarios = data.get("scenarios", [])
    
    scenario_results = []
    
    total_csrf_exploited = 0
    total_csrf_blocked = 0
    total_session_lost = 0
    total_xss_exposed = 0
    total_xss_protected = 0
    
    for sc in scenarios:
        sc_id = sc.get("scenario_id", "")
        action_type = sc.get("action_type", "HTTP_REQUEST")
        
        if action_type == "JS_COOKIE_ACCESS":
            origin = sc.get("page_origin", "")
            parsed_origin = urllib.parse.urlparse(origin)
            page_host = parsed_origin.hostname or ""
            
            readable_cookies = []
            protected_cookies = []
            
            for c in stored_cookies:
                c_domain = c.get("domain", "").lstrip(".")
                if page_host == c_domain or page_host.endswith("." + c_domain):
                    if c.get("http_only", False):
                        protected_cookies.append(c.get("name"))
                    else:
                        readable_cookies.append(c.get("name"))
                        
            if readable_cookies:
                status = "EXPOSED_TO_JS"
                verdict = "XSS_COOKIE_THEFT_POSSIBLE"
                total_xss_exposed += 1
            else:
                status = "PROTECTED_BY_HTTPONLY"
                verdict = "XSS_MITIGATED_BY_HTTPONLY"
                total_xss_protected += 1
                
            scenario_results.append({
                "scenario_id": sc_id,
                "action_type": action_type,
                "status": status,
                "readable_cookies": readable_cookies,
                "protected_cookies": protected_cookies,
                "attached_cookies": [],
                "security_verdict": verdict
            })
            
        elif action_type == "HTTP_REQUEST":
            init_origin = sc.get("initiator_origin")
            target_url = sc.get("target_url", "")
            method = sc.get("method", "GET").upper()
            is_top_level = sc.get("is_top_level_navigation", False)
            csrf_token_present = sc.get("csrf_token_present", False)
            is_callback = sc.get("is_callback", False)
            
            parsed_target = urllib.parse.urlparse(target_url)
            target_protocol = parsed_target.scheme.lower()
            target_host = parsed_target.hostname or ""
            target_path = parsed_target.path or "/"
            
            target_site = get_etld_plus_one(target_host)
            
            if init_origin:
                parsed_init = urllib.parse.urlparse(init_origin)
                init_host = parsed_init.hostname or ""
                init_site = get_etld_plus_one(init_host)
                is_same_site = (init_site == target_site and init_site != "")
            else:
                # Direct navigation from address bar
                is_same_site = True
                
            attached_cookies = []
            blocked_cookies = []
            
            for c in stored_cookies:
                c_name = c.get("name", "")
                c_domain = c.get("domain", "").lstrip(".")
                c_path = c.get("path", "/")
                c_secure = c.get("secure", False)
                raw_same_site = c.get("same_site", "Unspecified")
                
                # Check domain match
                domain_match = (target_host == c_domain or target_host.endswith("." + c_domain))
                if not domain_match:
                    continue
                    
                # Check path match
                if not target_path.startswith(c_path):
                    continue
                    
                # Resolve SameSite
                if raw_same_site == "Unspecified":
                    resolved_same_site = "Lax" if browser_mode == "CHROME_80_PLUS" else "None"
                else:
                    resolved_same_site = raw_same_site
                    
                # Check SameSite=None secure requirement (Chrome 80+)
                if browser_mode == "CHROME_80_PLUS" and resolved_same_site == "None" and not c_secure:
                    blocked_cookies.append({"name": c_name, "reason": "REJECTED_SAMESITE_NONE_REQUIRES_SECURE"})
                    continue
                    
                # Check Secure flag against protocol
                if c_secure and target_protocol != "https":
                    blocked_cookies.append({"name": c_name, "reason": "REJECTED_INSECURE_PROTOCOL"})
                    continue
                    
                # Check SameSite inclusion rules
                if is_same_site:
                    attached_cookies.append(c_name)
                else:
                    # Cross-Site request
                    if resolved_same_site == "Strict":
                        blocked_cookies.append({"name": c_name, "reason": "BLOCKED_BY_SAMESITE_STRICT"})
                    elif resolved_same_site == "Lax":
                        # Lax allows top-level navigation with safe methods (GET, HEAD)
                        if is_top_level and method in ("GET", "HEAD"):
                            attached_cookies.append(c_name)
                        else:
                            blocked_cookies.append({"name": c_name, "reason": "BLOCKED_BY_SAMESITE_LAX"})
                    elif resolved_same_site == "None":
                        attached_cookies.append(c_name)
                        
            # Determine security verdict
            if is_same_site:
                verdict = "NORMAL_SAME_SITE_REQUEST"
            else:
                # Cross-site
                if attached_cookies:
                    if method not in ("GET", "HEAD"):
                        if csrf_token_present:
                            verdict = "CSRF_PREVENTED_BY_TOKEN"
                        else:
                            if is_callback:
                                verdict = "CALLBACK_PROCESSED_WITH_COOKIES"
                            else:
                                verdict = "CSRF_VULNERABILITY_EXPLOITED"
                                total_csrf_exploited += 1
                    else:
                        if is_top_level:
                            verdict = "SAFE_CROSS_SITE_NAVIGATION"
                        else:
                            verdict = "GET_SUBRESOURCE_CSRF_EXPLOITED"
                            total_csrf_exploited += 1
                else:
                    # No cookies attached
                    is_expected_callback = is_callback or any(k in target_path for k in ["callback", "checkout", "oauth"])
                    if is_expected_callback:
                        verdict = "SESSION_COOKIE_BLOCKED_CALLBACK_FAILURE"
                        total_session_lost += 1
                    else:
                        verdict = "CSRF_BLOCKED_BY_SAMESITE"
                        total_csrf_blocked += 1
                        
            scenario_results.append({
                "scenario_id": sc_id,
                "action_type": action_type,
                "is_same_site": is_same_site,
                "attached_cookies": attached_cookies,
                "blocked_cookies": blocked_cookies,
                "security_verdict": verdict
            })
            
    summary = {
        "browser_mode": browser_mode,
        "total_scenarios": len(scenario_results),
        "csrf_vulnerabilities_exploited": total_csrf_exploited,
        "csrf_attacks_blocked": total_csrf_blocked,
        "session_lost_callback_failures": total_session_lost,
        "xss_exposed_cookies": total_xss_exposed,
        "xss_protected_cookies": total_xss_protected
    }
    
    return {
        "summary": summary,
        "scenarios": scenario_results
    }

if __name__ == "__main__":
    try:
        raw_input = sys.stdin.read().strip()
        if not raw_input:
            sys.exit(0)
        input_data = json.loads(raw_input)
        result = solve(input_data)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
