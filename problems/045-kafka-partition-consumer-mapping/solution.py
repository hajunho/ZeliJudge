import sys

def assign_partitions(consumers, p_count, strategy):
    c_count = len(consumers)
    assignment = {c: [] for c in consumers}
    if c_count == 0:
        return assignment

    if strategy == "ROUND_ROBIN":
        for p in range(p_count):
            c = consumers[p % c_count]
            assignment[c].append(p)
    elif strategy == "RANGE":
        num_per_c = p_count // c_count
        remainder = p_count % c_count
        cur_p = 0
        for i in range(c_count):
            cnt = num_per_c + (1 if i < remainder else 0)
            for _ in range(cnt):
                assignment[consumers[i]].append(cur_p)
                cur_p += 1
    else:
        raise ValueError(f"Unknown strategy: {strategy}")

    return assignment

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return

    idx = 0
    assert input_data[idx] == "TOPIC_PARTITIONS"
    p_count = int(input_data[idx + 1])
    idx += 2

    assert input_data[idx] == "STRATEGY"
    strategy = input_data[idx + 1]
    idx += 2

    assert input_data[idx] == "EVENTS"
    events_count = int(input_data[idx + 1])
    idx += 2

    partition_lag = [0] * p_count
    consumer_set = set()
    assignment = {}
    
    total_published = 0
    total_consumed = 0
    max_idle_observed = 0

    out_lines = []

    for _ in range(events_count):
        cmd = input_data[idx]
        if cmd == "JOIN":
            c_id = input_data[idx + 1]
            idx += 2
            consumer_set.add(c_id)
            consumers = sorted(list(consumer_set))
            assignment = assign_partitions(consumers, p_count, strategy)

            active_cnt = sum(1 for c in consumers if len(assignment[c]) > 0)
            idle_cnt = len(consumers) - active_cnt
            if idle_cnt > max_idle_observed:
                max_idle_observed = idle_cnt

            out_lines.append(
                f"REBALANCE STRATEGY:{strategy} ACTIVE_CONSUMERS:{active_cnt} IDLE_CONSUMERS:{idle_cnt}"
            )
            for c in consumers:
                if assignment[c]:
                    parts_str = ",".join(str(p) for p in sorted(assignment[c]))
                    out_lines.append(f"ASSIGNMENT {c} -> [{parts_str}]")
                else:
                    out_lines.append(f"ASSIGNMENT {c} -> NONE")

        elif cmd == "LEAVE":
            c_id = input_data[idx + 1]
            idx += 2
            if c_id in consumer_set:
                consumer_set.remove(c_id)
            consumers = sorted(list(consumer_set))
            assignment = assign_partitions(consumers, p_count, strategy)

            active_cnt = sum(1 for c in consumers if len(assignment[c]) > 0)
            idle_cnt = len(consumers) - active_cnt
            if idle_cnt > max_idle_observed:
                max_idle_observed = idle_cnt

            out_lines.append(
                f"REBALANCE STRATEGY:{strategy} ACTIVE_CONSUMERS:{active_cnt} IDLE_CONSUMERS:{idle_cnt}"
            )
            for c in consumers:
                if assignment[c]:
                    parts_str = ",".join(str(p) for p in sorted(assignment[c]))
                    out_lines.append(f"ASSIGNMENT {c} -> [{parts_str}]")
                else:
                    out_lines.append(f"ASSIGNMENT {c} -> NONE")

        elif cmd == "PUBLISH":
            p_id = int(input_data[idx + 1])
            msg_cnt = int(input_data[idx + 2])
            idx += 3

            partition_lag[p_id] += msg_cnt
            total_published += msg_cnt
            total_lag = sum(partition_lag)
            out_lines.append(
                f"PUBLISH PARTITION:{p_id} ADDED:{msg_cnt} TOTAL_LAG:{total_lag}"
            )

        elif cmd == "CONSUME":
            max_per_c = int(input_data[idx + 1])
            idx += 2

            consumers = sorted(list(consumer_set))
            active_cnt = sum(1 for c in consumers if len(assignment.get(c, [])) > 0)
            consumed_round = 0

            for c in consumers:
                parts = assignment.get(c, [])
                for p in parts:
                    take = min(partition_lag[p], max_per_c)
                    partition_lag[p] -= take
                    consumed_round += take

            total_consumed += consumed_round
            total_lag = sum(partition_lag)
            out_lines.append(
                f"CONSUME ACTIVE_WORKERS:{active_cnt} PROCESSED:{consumed_round} REMAINING_LAG:{total_lag}"
            )
        else:
            raise ValueError(f"Unknown command: {cmd}")

    final_lag = sum(partition_lag)
    wasted = "YES" if max_idle_observed > 0 else "NO"
    out_lines.append(
        f"SUMMARY TOTAL_PARTITIONS:{p_count} TOTAL_MESSAGES_PUBLISHED:{total_published} TOTAL_MESSAGES_CONSUMED:{total_consumed} FINAL_LAG:{final_lag} MAX_IDLE_CONSUMERS_OBSERVED:{max_idle_observed} WASTED_CONSUMER_RESOURCES_DETECTED:{wasted}"
    )

    sys.stdout.write("\n".join(out_lines) + "\n")

if __name__ == "__main__":
    solve()
