import sys
import heapq

def solve():
    input_data = sys.stdin.read().splitlines()
    if not input_data:
        return

    ttl_ms = 1000
    db_query_ms = 50

    idx = 0
    while idx < len(input_data):
        line = input_data[idx].strip()
        idx += 1
        if not line:
            continue
        parts = line.split()
        if parts[0] == "TTL_MS":
            ttl_ms = int(parts[1])
        elif parts[0] == "DB_QUERY_MS":
            db_query_ms = int(parts[1])
        elif parts[0] == "EVENTS":
            break

    requests = []
    while idx < len(input_data):
        line = input_data[idx].strip()
        idx += 1
        if not line:
            continue
        parts = line.split()
        if parts[0] == "REQ":
            client_id = parts[1]
            t = int(parts[2])
            requests.append((t, client_id))

    # Priority queue for simulation events
    # Orders at same timestamp:
    # 0: DB finish events (NAIVE_FINISH, MUTEX_FINISH, STALE_FINISH)
    # 1: REQ events
    heap = []
    req_seq = 0
    for t, client_id in requests:
        req_seq += 1
        heapq.heappush(heap, (t, 1, 'REQ', req_seq, client_id))

    # NAIVE state
    naive_cached_until = 0
    naive_db_queries = 0
    naive_total_lat = 0

    # MUTEX state
    mutex_cached_until = 0
    mutex_busy_until = 0
    mutex_db_queries = 0
    mutex_total_lat = 0

    # STALE state
    stale_cached_until = 0
    stale_busy_until = 0
    has_stale_data = False
    stale_db_queries = 0
    stale_total_lat = 0

    total_reqs = 0

    while heap:
        ev = heapq.heappop(heap)
        ev_t, ev_order, ev_type = ev[0], ev[1], ev[2]

        if ev_type == 'NAIVE_FINISH':
            new_exp = ev[3]
            if new_exp > naive_cached_until:
                naive_cached_until = new_exp

        elif ev_type == 'MUTEX_FINISH':
            new_exp = ev[3]
            if new_exp > mutex_cached_until:
                mutex_cached_until = new_exp

        elif ev_type == 'STALE_FINISH':
            new_exp = ev[3]
            if new_exp > stale_cached_until:
                stale_cached_until = new_exp
            has_stale_data = True

        elif ev_type == 'REQ':
            req_seq, client_id = ev[3], ev[4]
            total_reqs += 1

            # 1. NAIVE
            if ev_t < naive_cached_until:
                n_status = "HIT"
                n_lat = 1
            else:
                n_status = "DB_DIRECT"
                n_lat = db_query_ms
                naive_db_queries += 1
                finish_t = ev_t + db_query_ms
                heapq.heappush(heap, (finish_t, 0, 'NAIVE_FINISH', finish_t + ttl_ms))
            naive_total_lat += n_lat

            # 2. MUTEX
            if ev_t < mutex_cached_until:
                m_status = "HIT"
                m_lat = 1
            else:
                if ev_t >= mutex_busy_until:
                    m_status = "LOCK_FETCH"
                    m_lat = db_query_ms
                    mutex_db_queries += 1
                    finish_t = ev_t + db_query_ms
                    mutex_busy_until = finish_t
                    heapq.heappush(heap, (finish_t, 0, 'MUTEX_FINISH', finish_t + ttl_ms))
                else:
                    m_status = "LOCK_WAIT"
                    m_lat = mutex_busy_until - ev_t
            mutex_total_lat += m_lat

            # 3. STALE (stale-while-revalidate)
            if ev_t < stale_cached_until:
                s_status = "HIT"
                s_lat = 1
            else:
                if not has_stale_data:
                    # Cold start period
                    if ev_t >= stale_busy_until:
                        s_status = "COLD_FETCH"
                        s_lat = db_query_ms
                        stale_db_queries += 1
                        finish_t = ev_t + db_query_ms
                        stale_busy_until = finish_t
                        heapq.heappush(heap, (finish_t, 0, 'STALE_FINISH', finish_t + ttl_ms))
                    else:
                        s_status = "COLD_WAIT"
                        s_lat = stale_busy_until - ev_t
                else:
                    # Stale data exists
                    if ev_t >= stale_busy_until:
                        s_status = "STALE_REVALIDATE"
                        s_lat = 1
                        stale_db_queries += 1
                        finish_t = ev_t + db_query_ms
                        stale_busy_until = finish_t
                        heapq.heappush(heap, (finish_t, 0, 'STALE_FINISH', finish_t + ttl_ms))
                    else:
                        s_status = "STALE_HIT"
                        s_lat = 1
            stale_total_lat += s_lat

            print(f"REQ {client_id} AT:{ev_t} NAIVE:{n_status},LAT:{n_lat}ms MUTEX:{m_status},LAT:{m_lat}ms STALE:{s_status},LAT:{s_lat}ms")

    n_avg_lat = naive_total_lat / total_reqs if total_reqs > 0 else 0.0
    m_avg_lat = mutex_total_lat / total_reqs if total_reqs > 0 else 0.0
    s_avg_lat = stale_total_lat / total_reqs if total_reqs > 0 else 0.0

    m_saved = ((naive_db_queries - mutex_db_queries) / naive_db_queries * 100.0) if naive_db_queries > 0 else 0.0
    s_saved = ((naive_db_queries - stale_db_queries) / naive_db_queries * 100.0) if naive_db_queries > 0 else 0.0

    print(f"SUMMARY TOTAL_REQS:{total_reqs}")
    print(f"NAIVE DB_QUERIES:{naive_db_queries} AVG_LATENCY:{n_avg_lat:.2f}ms")
    print(f"MUTEX DB_QUERIES:{mutex_db_queries} AVG_LATENCY:{m_avg_lat:.2f}ms DB_SAVED:{m_saved:.2f}%")
    print(f"STALE DB_QUERIES:{stale_db_queries} AVG_LATENCY:{s_avg_lat:.2f}ms DB_SAVED:{s_saved:.2f}%")

if __name__ == "__main__":
    solve()
