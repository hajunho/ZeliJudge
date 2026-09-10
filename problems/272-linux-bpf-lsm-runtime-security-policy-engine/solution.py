import sys
import json
import fnmatch
import ipaddress

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

def match_pattern(pattern, value):
    if pattern is None or pattern == "*":
        return True
    return fnmatch.fnmatch(value, pattern)

def ip_in_cidr(ip_str, cidr_str):
    try:
        ip = ipaddress.ip_address(ip_str)
        net = ipaddress.ip_network(cidr_str, strict=False)
        return ip in net
    except Exception:
        return False

def get_lineage(processes, pid):
    lineage = []
    curr_pid = pid
    visited = set()
    while curr_pid and curr_pid in processes and curr_pid not in visited:
        visited.add(curr_pid)
        p = processes[curr_pid]
        lineage.append({
            "pid": curr_pid,
            "binary_path": p.get("binary_path", ""),
            "comm": p.get("comm", "")
        })
        curr_pid = p.get("ppid", 0)
    return lineage

def evaluate_bpf_lsm(data):
    policies = data.get("policies", [])
    processes = {int(k): v for k, v in data.get("processes", {}).items()}
    events = data.get("events", [])

    terminated_pids = set()
    evaluated_events = []
    blocked_count = 0
    killed_count = 0
    audited_count = 0
    allowed_count = 0

    for ev in events:
        eid = ev["event_id"]
        pid = ev.get("pid", 0)
        hook = ev.get("hook", "")
        details = ev.get("details", {})

        if pid in terminated_pids:
            evaluated_events.append({
                "event_id": eid,
                "pid": pid,
                "hook": hook,
                "verdict": "DROPPED_PROCESS_TERMINATED",
                "ret_code": -3,
                "matched_policy_id": None,
                "action": "NONE",
                "severity": "LOW"
            })
            continue

        p_info = processes.get(pid, {
            "comm": "unknown",
            "binary_path": "",
            "ppid": 0,
            "cgroup": "default",
            "uid": 1000,
            "gid": 1000
        })

        lineage = get_lineage(processes, pid)
        ancestor_binaries = [a["binary_path"] for a in lineage[1:]]

        matched_policy = None

        for pol in policies:
            if pol.get("hook") != hook:
                continue

            m = pol.get("match", {})

            # Cgroup match
            if not match_pattern(m.get("cgroup_pattern", "*"), p_info.get("cgroup", "")):
                continue

            # Process binary match
            if not match_pattern(m.get("process_binary_pattern", "*"), p_info.get("binary_path", "")):
                continue

            # Ancestor binary match (if specified)
            if "ancestor_binary_pattern" in m:
                anc_pattern = m["ancestor_binary_pattern"]
                has_anc_match = any(match_pattern(anc_pattern, anc_bin) for anc_bin in ancestor_binaries)
                if not has_anc_match:
                    continue

            # Hook-specific checks
            if hook == "bpf_lsm_file_open":
                target_path = details.get("path", "")
                if not match_pattern(m.get("target_path_pattern", "*"), target_path):
                    continue
                if "flags" in m and m["flags"]:
                    ev_flags = set(details.get("flags", []))
                    if not any(f in ev_flags for f in m["flags"]):
                        continue

            elif hook == "bpf_lsm_bprm_check_security":
                exec_path = details.get("executable_path", "")
                if not match_pattern(m.get("target_path_pattern", "*"), exec_path):
                    continue

            elif hook == "bpf_lsm_socket_connect":
                dest_ip = details.get("dest_ip", "")
                dest_port = details.get("dest_port", 0)
                if "destination_cidr" in m:
                    if not ip_in_cidr(dest_ip, m["destination_cidr"]):
                        continue
                if "destination_ports" in m and m["destination_ports"]:
                    if dest_port not in m["destination_ports"]:
                        continue

            matched_policy = pol
            break

        if matched_policy:
            action = matched_policy.get("action", "ALLOW")
            pol_id = matched_policy.get("policy_id")
            severity = matched_policy.get("severity", "MEDIUM")

            if action == "ALLOW":
                verdict = "ALLOWED"
                ret_code = 0
                allowed_count += 1
            elif action == "AUDIT":
                verdict = "AUDITED"
                ret_code = 0
                audited_count += 1
            elif action == "BLOCK_EPERM":
                verdict = "BLOCKED"
                ret_code = -1
                blocked_count += 1
            elif action == "BLOCK_EACCES":
                verdict = "BLOCKED"
                ret_code = -13
                blocked_count += 1
            elif action == "KILL_PROCESS":
                verdict = "KILLED"
                ret_code = -1
                killed_count += 1
                terminated_pids.add(pid)
            else:
                verdict = "ALLOWED"
                ret_code = 0
                allowed_count += 1
        else:
            verdict = "ALLOWED"
            ret_code = 0
            action = "DEFAULT_ALLOW"
            pol_id = None
            severity = "NONE"
            allowed_count += 1

        if hook == "bpf_lsm_bprm_check_security" and ret_code == 0:
            new_exec = details.get("executable_path")
            if new_exec and pid in processes:
                processes[pid]["binary_path"] = new_exec
                processes[pid]["comm"] = new_exec.split("/")[-1]

        evaluated_events.append({
            "event_id": eid,
            "pid": pid,
            "hook": hook,
            "verdict": verdict,
            "ret_code": ret_code,
            "matched_policy_id": pol_id,
            "action": action,
            "severity": severity
        })

    return {
        "total_events_evaluated": len(evaluated_events),
        "statistics": {
            "allowed": allowed_count,
            "audited": audited_count,
            "blocked": blocked_count,
            "killed": killed_count,
            "terminated_pids": sorted(list(terminated_pids))
        },
        "evaluated_events": evaluated_events
    }

def solve(data):
    return evaluate_bpf_lsm(data)

def main():
    try:
        raw = sys.stdin.read().strip()
        if not raw:
            return
        data = json.loads(raw)
        res = solve(data)
        print(json.dumps(res, ensure_ascii=False))
    except Exception as e:
        sys.stderr.write(f"Error: {e}\\n")

if __name__ == "__main__":
    main()
