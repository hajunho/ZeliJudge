#!/usr/bin/env python3
"""
[ZeliJudge #021] async로 짰는데 왜 1초씩 멈춰요?: 싱글 스레드 이벤트 루프와 블로킹 I/O의 배신
해답 코드: 이산 사건 시뮬레이션 및 이분 탐색 O(N log N)
"""
import sys
from bisect import bisect_right

def solve():
    input_data = sys.stdin.read().splitlines()
    if not input_data:
        return

    first_line = input_data[0].strip()
    if not first_line:
        return
    n = int(first_line)

    busy_until = 0
    blocking_intervals = []
    req_list = []

    for line in input_data[1:n + 1]:
        line = line.strip()
        if not line:
            continue

        parts = line.split()
        # REQ <req_id> <arrive_time> <task_type> <duration>
        req_id = parts[1]
        arrive = int(parts[2])
        task_type = parts[3]
        duration = int(parts[4])

        start = max(arrive, busy_until)

        if task_type == "BLOCK":
            end = start + duration
            busy_until = end
            if blocking_intervals and blocking_intervals[-1][1] == start:
                prev_s, _ = blocking_intervals.pop()
                blocking_intervals.append((prev_s, end))
            else:
                blocking_intervals.append((start, end))

            req_list.append({
                "id": req_id,
                "arrive": arrive,
                "type": task_type,
                "duration": duration,
                "start": start,
                "finish": end
            })
        else:  # ASYNC
            io_done = start + duration
            req_list.append({
                "id": req_id,
                "arrive": arrive,
                "type": task_type,
                "duration": duration,
                "start": start,
                "io_done": io_done
            })

    starts = [b[0] for b in blocking_intervals]
    output = []
    delays = []

    for req in req_list:
        req_id = req["id"]
        arrive = req["arrive"]
        duration = req["duration"]
        start = req["start"]

        if req["type"] == "BLOCK":
            finish = req["finish"]
        else:
            io_done = req["io_done"]
            idx = bisect_right(starts, io_done) - 1
            if idx >= 0:
                s, e = blocking_intervals[idx]
                if s <= io_done < e:
                    finish = e
                else:
                    finish = io_done
            else:
                finish = io_done

        delay = finish - (arrive + duration)
        delays.append(delay)
        output.append(f"EVENT {req_id} START:{start} FINISH:{finish} DELAY:{delay}")

    max_delay = max(delays) if delays else 0
    avg_delay = (sum(delays) / len(delays)) if delays else 0.0
    output.append(f"SUMMARY TOTAL:{len(delays)} MAX_DELAY:{max_delay} AVG_DELAY:{avg_delay:.2f}")

    sys.stdout.write("\n".join(output) + "\n")

if __name__ == "__main__":
    solve()
