"""
Problem 224: Distributed Consensus: Raft Non-Voting Learner Node Catch-Up & Dynamic Quorum Reconfiguration vs Availability Cliff
"""
import sys
import json

def simulate_raft_reconfiguration(data):
    config = data.get("config", {})
    add_as_learner = bool(config.get("add_as_learner_first", True))
    catchup_threshold = int(config.get("catchup_threshold_entries", 100))
    max_catchup_rounds = int(config.get("max_catchup_rounds", 10))

    cluster = data.get("cluster", {})
    initial_voters = list(cluster.get("initial_voters", ["N1", "N2", "N3"]))
    initial_commit_index = int(cluster.get("commit_index", 50000))
    snapshot_index = int(cluster.get("snapshot_applied_index", 0))
    node_to_add = cluster.get("node_to_add", "N4")
    other_node_failure = cluster.get("concurrent_node_failure", None)

    replication = data.get("replication", {})
    leader_write_rate = float(replication.get("leader_write_rate_entries_per_sec", 1000.0))
    learner_ingest_rate = float(replication.get("learner_ingest_rate_entries_per_sec", 2500.0))
    learner_network_status = replication.get("learner_network_status", "HEALTHY")

    current_voters = list(initial_voters)

    # Case 1: Naive Direct Addition as VOTER
    if not add_as_learner:
        current_voters.append(node_to_add)
        new_quorum = (len(current_voters) // 2) + 1
        available_voters = [n for n in initial_voters if n != other_node_failure]
        if len(available_voters) < new_quorum:
            return {
                "status": "FAILED",
                "verdict": "PREMATURE_VOTING_MEMBER_QUORUM_COLLAPSE",
                "metrics": {
                    "add_as_learner_first": False,
                    "final_voters_count": len(current_voters),
                    "required_quorum": new_quorum,
                    "available_responsive_voters": len(available_voters),
                    "catchup_rounds_completed": 0,
                    "final_learner_match_index": 0,
                    "quorum_availability_maintained": False
                }
            }
        else:
            return {
                "status": "SUCCESS",
                "verdict": "VOTER_ADDED_WITHOUT_LEARNER_RISKY",
                "metrics": {
                    "add_as_learner_first": False,
                    "final_voters_count": len(current_voters),
                    "required_quorum": new_quorum,
                    "available_responsive_voters": len(available_voters),
                    "catchup_rounds_completed": 0,
                    "final_learner_match_index": 0,
                    "quorum_availability_maintained": True
                }
            }

    # Case 2: Learner Node Catch-Up Phase
    if learner_network_status == "PARTITIONED":
        return {
            "status": "FAILED",
            "verdict": "LEARNER_UNREACHABLE_TIMEOUT",
            "metrics": {
                "add_as_learner_first": True,
                "final_voters_count": len(initial_voters),
                "required_quorum": (len(initial_voters) // 2) + 1,
                "available_responsive_voters": len([n for n in initial_voters if n != other_node_failure]),
                "catchup_rounds_completed": 1,
                "final_learner_match_index": snapshot_index,
                "quorum_availability_maintained": True
            }
        }

    learner_match_index = snapshot_index
    current_gap = initial_commit_index - snapshot_index
    total_leader_entries = initial_commit_index
    rounds = 0
    caught_up = False

    while rounds < max_catchup_rounds:
        rounds += 1
        duration_sec = current_gap / learner_ingest_rate if learner_ingest_rate > 0 else float("inf")
        learner_match_index += current_gap

        new_writes = int(leader_write_rate * duration_sec)
        total_leader_entries += new_writes
        current_gap = new_writes

        if current_gap <= catchup_threshold:
            caught_up = True
            break

    if not caught_up:
        return {
            "status": "FAILED",
            "verdict": "LEARNER_CATCHUP_STARVATION_LOOP",
            "metrics": {
                "add_as_learner_first": True,
                "final_voters_count": len(initial_voters),
                "required_quorum": (len(initial_voters) // 2) + 1,
                "available_responsive_voters": len([n for n in initial_voters if n != other_node_failure]),
                "catchup_rounds_completed": rounds,
                "final_learner_match_index": int(learner_match_index),
                "quorum_availability_maintained": True
            }
        }

    # Caught up! Atomic promotion to VOTER
    current_voters.append(node_to_add)
    final_quorum = (len(current_voters) // 2) + 1
    responsive_voters = [n for n in current_voters if n != other_node_failure]
    quorum_ok = len(responsive_voters) >= final_quorum

    return {
        "status": "SUCCESS" if quorum_ok else "FAILED",
        "verdict": "OPTIMAL_LEARNER_PROMOTION_DYNAMIC_MEMBERSHIP" if quorum_ok else "PROMOTION_FAILED_INSUFFICIENT_QUORUM",
        "metrics": {
            "add_as_learner_first": True,
            "final_voters_count": len(current_voters),
            "required_quorum": final_quorum,
            "available_responsive_voters": len(responsive_voters),
            "catchup_rounds_completed": rounds,
            "final_learner_match_index": int(learner_match_index),
            "quorum_availability_maintained": quorum_ok
        }
    }

def main():
    try:
        raw_input = sys.stdin.read()
        if not raw_input.strip():
            return
        data = json.loads(raw_input)
        result = simulate_raft_reconfiguration(data)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
