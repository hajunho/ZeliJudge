import sys
import json

def solve():
    input_data = sys.stdin.read().strip()
    if not input_data:
        return

    data = json.loads(input_data)
    config = data.get("config", {})
    prevote_enabled = bool(config.get("prevote_enabled", True))
    check_quorum_enabled = bool(config.get("check_quorum_enabled", True))

    topology = data.get("topology", {})
    nodes = topology.get("nodes", ["L", "A", "B", "C", "D"])
    initial_leader = topology.get("initial_leader", "L")
    partition_type = topology.get("partition_type", "ASYMMETRIC")

    workload = data.get("workload", {})
    simulation_rounds = int(workload.get("simulation_rounds", 5))
    client_write_requests = int(workload.get("client_write_requests", 1000))

    current_leader = initial_leader
    leader_term = 1
    leader_demotions = 0
    successful_writes = 0
    failed_writes = 0
    split_brain_detected = False
    disruptive_elections = 0

    if partition_type == "HEALTHY":
        status = "SUCCESS"
        verdict = "RAFT_CLUSTER_HEALTHY_STABLE"
        successful_writes = client_write_requests
    elif partition_type == "SYMMETRIC_LEADER_ISOLATION":
        if not check_quorum_enabled:
            split_brain_detected = True
            status = "FAILED"
            verdict = "SPLIT_BRAIN_STALE_LEADER_WRITE_ATTEMPT"
            failed_writes = client_write_requests
        else:
            leader_demotions += 1
            current_leader = "A"
            leader_term = 2
            successful_writes = client_write_requests
            status = "SUCCESS"
            verdict = "LEADER_ISOLATED_VOLUNTARY_STEPDOWN"
    elif partition_type == "ASYMMETRIC":
        for r in range(simulation_rounds):
            if not prevote_enabled:
                d_term = leader_term + 1
                disruptive_elections += 1
                leader_demotions += 1
                leader_term = d_term
                current_leader = "A"
                leader_term += 1
                failed_writes += int(client_write_requests / simulation_rounds)
            else:
                successful_writes = client_write_requests
                disruptive_elections = 0
                leader_demotions = 0
                break

        if not prevote_enabled:
            status = "FAILED"
            verdict = "DISRUPTIVE_SERVER_LEADER_ELECTION_STORM"
        else:
            status = "SUCCESS"
            verdict = "OPTIMAL_PREVOTE_CHECK_QUORUM_DEFENSE"
    else:
        status = "FAILED"
        verdict = "UNKNOWN_PARTITION_TYPE"

    write_success_rate = (successful_writes / max(1, client_write_requests))

    result = {
        "status": status,
        "verdict": verdict,
        "metrics": {
            "leader": current_leader,
            "leader_term": leader_term,
            "leader_demotions": leader_demotions,
            "disruptive_elections": disruptive_elections,
            "write_success_rate": round(write_success_rate, 4),
            "split_brain_detected": split_brain_detected
        }
    }
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    solve()
