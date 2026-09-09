import sys
import json

def solve():
    input_data = sys.stdin.read().strip()
    if not input_data:
        return

    data = json.loads(input_data)
    config = data.get("config", {})
    dns_arch = config.get("dns_architecture", "CORE_DNS_CLUSTERIP")
    resolv_opts = config.get("resolv_options", "DEFAULT")
    conntrack_max = int(config.get("conntrack_max", 131072))
    conntrack_count = int(config.get("conntrack_count", 45000))
    kube_proxy_mode = config.get("kube_proxy_mode", "IPTABLES")
    dns_timeout_sec = float(config.get("dns_timeout_sec", 5.0))

    workload = data.get("workload", {})
    total_lookups = int(workload.get("total_dns_lookups", 10000))
    parallel_queries = bool(workload.get("parallel_a_aaaa_queries", True))
    concurrency = int(workload.get("traffic_concurrency", 200))

    new_conntrack_entries = 0 if dns_arch == "NODELOCAL_DNSCACHE" else total_lookups * 2
    if conntrack_count + new_conntrack_entries >= conntrack_max:
        result = {
            "status": "FAILED",
            "verdict": "CONNTRACK_TABLE_EXHAUSTION_PACKET_DROP",
            "metrics": {
                "conntrack_usage_pct": round(((conntrack_count + new_conntrack_entries) / conntrack_max) * 100.0, 1),
                "five_second_stalls_count": int(total_lookups * 0.40),
                "avg_dns_latency_ms": 2500.0,
                "p99_dns_latency_ms": 5005.0,
                "conntrack_entries_created": new_conntrack_entries,
                "netfilter_race_drops": int(total_lookups * 0.40)
            }
        }
        print(json.dumps(result, ensure_ascii=False))
        return

    if dns_arch == "NODELOCAL_DNSCACHE":
        result = {
            "status": "SUCCESS",
            "verdict": "OPTIMAL_NODELOCAL_DNSCACHE_DEFENSE",
            "metrics": {
                "conntrack_usage_pct": round((conntrack_count / conntrack_max) * 100.0, 1),
                "five_second_stalls_count": 0,
                "avg_dns_latency_ms": 0.4,
                "p99_dns_latency_ms": 0.8,
                "conntrack_entries_created": 0,
                "netfilter_race_drops": 0
            }
        }
        print(json.dumps(result, ensure_ascii=False))
        return

    conntrack_usage_pct = round(((conntrack_count + new_conntrack_entries) / conntrack_max) * 100.0, 1)

    if resolv_opts == "SINGLE_REQUEST_REOPEN":
        result = {
            "status": "WARNING",
            "verdict": "SINGLE_REQUEST_REOPEN_SERIAL_LATENCY_WORKAROUND",
            "metrics": {
                "conntrack_usage_pct": conntrack_usage_pct,
                "five_second_stalls_count": 0,
                "avg_dns_latency_ms": 6.5,
                "p99_dns_latency_ms": 14.5,
                "conntrack_entries_created": new_conntrack_entries,
                "netfilter_race_drops": 0
            }
        }
        print(json.dumps(result, ensure_ascii=False))
        return

    if not parallel_queries:
        result = {
            "status": "SUCCESS",
            "verdict": "IPV4_ONLY_NO_AAAA_COLLISION",
            "metrics": {
                "conntrack_usage_pct": conntrack_usage_pct,
                "five_second_stalls_count": 0,
                "avg_dns_latency_ms": 2.5,
                "p99_dns_latency_ms": 5.0,
                "conntrack_entries_created": new_conntrack_entries,
                "netfilter_race_drops": 0
            }
        }
        print(json.dumps(result, ensure_ascii=False))
        return

    if kube_proxy_mode == "IPTABLES":
        race_drop_ratio = 0.035 if concurrency >= 100 else 0.005
        five_sec_drops = int(total_lookups * race_drop_ratio)
        avg_latency = round((1.0 - race_drop_ratio) * 2.5 + race_drop_ratio * (dns_timeout_sec * 1000.0), 1)
        p99_latency = dns_timeout_sec * 1000.0 + 5.0
        result = {
            "status": "FAILED",
            "verdict": "KUBERNETES_5S_DNS_CONNTRACK_RACE_DISASTER",
            "metrics": {
                "conntrack_usage_pct": conntrack_usage_pct,
                "five_second_stalls_count": five_sec_drops,
                "avg_dns_latency_ms": avg_latency,
                "p99_dns_latency_ms": p99_latency,
                "conntrack_entries_created": new_conntrack_entries,
                "netfilter_race_drops": five_sec_drops
            }
        }
        print(json.dumps(result, ensure_ascii=False))
        return
    else:
        race_drop_ratio = 0.012
        five_sec_drops = int(total_lookups * race_drop_ratio)
        avg_latency = round((1.0 - race_drop_ratio) * 1.8 + race_drop_ratio * (dns_timeout_sec * 1000.0), 1)
        p99_latency = dns_timeout_sec * 1000.0 + 3.0
        result = {
            "status": "FAILED",
            "verdict": "IPVS_UDP_CONNTRACK_RACE_INTERMITTENT_STALL",
            "metrics": {
                "conntrack_usage_pct": conntrack_usage_pct,
                "five_second_stalls_count": five_sec_drops,
                "avg_dns_latency_ms": avg_latency,
                "p99_dns_latency_ms": p99_latency,
                "conntrack_entries_created": new_conntrack_entries,
                "netfilter_race_drops": five_sec_drops
            }
        }
        print(json.dumps(result, ensure_ascii=False))
        return

if __name__ == "__main__":
    solve()
