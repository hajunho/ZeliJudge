import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return

    idx = 0
    assert input_data[idx] == "LIVENESS_FAIL_LIMIT"
    l_limit = int(input_data[idx + 1])
    idx += 2

    assert input_data[idx] == "READINESS_FAIL_LIMIT"
    r_limit = int(input_data[idx + 1])
    idx += 2

    assert input_data[idx] == "READINESS_SUCCESS_LIMIT"
    r_succ = int(input_data[idx + 1])
    idx += 2

    assert input_data[idx] == "EVENTS"
    events_count = int(input_data[idx + 1])
    idx += 2

    naive_pods = {}
    sep_pods = {}

    naive_total_restarts = 0
    sep_total_restarts = 0

    out_lines = []

    for _ in range(events_count):
        cmd = input_data[idx]
        assert cmd == "STATUS"
        ts = input_data[idx + 1]
        pod_id = input_data[idx + 2]
        app_internal = input_data[idx + 3]
        db_dep = input_data[idx + 4]
        idx += 5

        if pod_id not in naive_pods:
            naive_pods[pod_id] = 0  # fail_count
        if pod_id not in sep_pods:
            # [liveness_fail, readiness_fail, readiness_succ, traffic_enabled(1/0)]
            sep_pods[pod_id] = [0, 0, 0, 1]

        # 1. NAIVE Deep Health Check
        n_fail = naive_pods[pod_id]
        if app_internal == "OK" and db_dep == "OK":
            naive_pods[pod_id] = 0
            naive_act = "HEALTHY"
        else:
            n_fail += 1
            if n_fail >= l_limit:
                naive_act = "RESTART"
                naive_total_restarts += 1
                naive_pods[pod_id] = 0
            else:
                naive_pods[pod_id] = n_fail
                naive_act = "FAILING"

        # 2. SEPARATED Probes
        s_pod = sep_pods[pod_id]
        restarted = False

        # Liveness check (internal process health only)
        if app_internal == "OK":
            s_pod[0] = 0
            s_liveness_act = "ALIVE"
        else:
            s_pod[0] += 1
            if s_pod[0] >= l_limit:
                s_liveness_act = "RESTART"
                sep_total_restarts += 1
                s_pod[0] = 0
                restarted = True
            else:
                s_liveness_act = "FAILING"

        # Readiness check (serving readiness including downstream dependencies)
        if restarted:
            s_readiness_act = "UNREADY"
            s_pod[1] = 0  # readiness_fail reset
            s_pod[2] = 0  # readiness_succ reset
            s_pod[3] = 0  # traffic DISABLED
        else:
            if app_internal == "OK" and db_dep == "OK":
                s_readiness_act = "READY"
                s_pod[1] = 0
                s_pod[2] += 1
                if s_pod[2] >= r_succ:
                    s_pod[3] = 1  # traffic ENABLED
            else:
                s_readiness_act = "UNREADY"
                s_pod[2] = 0
                s_pod[1] += 1
                if s_pod[1] >= r_limit:
                    s_pod[3] = 0  # traffic DISABLED

        traffic_str = "ENABLED" if s_pod[3] == 1 else "DISABLED"
        out_lines.append(
            f"STATUS {ts} POD:{pod_id} NAIVE:{naive_act} SEPARATED:LIVENESS={s_liveness_act},READINESS={s_readiness_act},TRAFFIC={traffic_str}"
        )

    saved = naive_total_restarts - sep_total_restarts
    out_lines.append(
        f"SUMMARY TOTAL_EVENTS:{events_count} NAIVE_RESTARTS:{naive_total_restarts} SEPARATED_RESTARTS:{sep_total_restarts} UNNECESSARY_RESTARTS_SAVED:{saved}"
    )

    sys.stdout.write("\n".join(out_lines) + "\n")

if __name__ == "__main__":
    solve()
