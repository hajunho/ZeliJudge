import sys
import heapq

def solve():
    input_text = sys.stdin.read()
    if not input_text.strip():
        return

    lines = input_text.splitlines()
    idx = 0
    timeout_ms = 1000
    max_buf = 100

    while idx < len(lines):
        line = lines[idx].strip()
        idx += 1
        if not line:
            continue
        if line.startswith("BUFFER_TIMEOUT_MS"):
            parts = line.split()
            if len(parts) >= 2:
                timeout_ms = int(parts[1])
        elif line.startswith("MAX_BUFFER_SIZE"):
            parts = line.split()
            if len(parts) >= 2:
                max_buf = int(parts[1])
        elif line == "EVENTS":
            break

    raw_events = []
    ev_idx = 0
    while idx < len(lines):
        rline = lines[idx].strip()
        idx += 1
        if not rline:
            continue
        parts = rline.split()
        raw_events.append({
            'orig_idx': ev_idx,
            'ev_id': parts[0],
            'channel_id': parts[1],
            'seq': int(parts[2]),
            'state': parts[3],
            'timestamp': int(parts[4])
        })
        ev_idx += 1

    raw_events.sort(key=lambda x: (x['timestamp'], x['orig_idx']))

    # --- NAIVE MODEL ---
    naive_channel_seq = {}
    naive_inversions = 0
    naive_jumps = 0
    naive_processed = 0
    naive_statuses = {}

    for ev in raw_events:
        eid = ev['ev_id']
        ch = ev['channel_id']
        seq = ev['seq']

        last_s = naive_channel_seq.get(ch, 0)
        if seq <= last_s:
            naive_inversions += 1
            st = "REGRESSION"
        elif seq > last_s + 1:
            naive_jumps += 1
            st = "JUMPED"
            naive_channel_seq[ch] = seq
        else:
            naive_processed += 1
            st = "PROCESSED"
            naive_channel_seq[ch] = seq

        naive_statuses[eid] = st

    # --- BUFFERED MODEL ---
    buf_expected = {}
    buffers = {}
    timeout_heap = []

    buffered_count = 0
    drained_count = 0
    dropped_stale_count = 0
    timeout_gaps = 0
    overflow_dropped = 0
    buf_statuses = {}

    for ev in raw_events:
        eid = ev['ev_id']
        ch = ev['channel_id']
        seq = ev['seq']
        st = ev['state']
        t = ev['timestamp']

        if ch not in buf_expected:
            buf_expected[ch] = 1
            buffers[ch] = {}

        while timeout_heap and timeout_heap[0][0] <= t:
            deadline, target_ch = heapq.heappop(timeout_heap)
            target_buf = buffers.get(target_ch, {})
            if target_buf:
                oldest_t = min(item['timestamp'] for item in target_buf.values())
                if oldest_t + timeout_ms <= t:
                    min_seq = min(target_buf.keys())
                    timeout_gaps += (min_seq - buf_expected[target_ch])
                    buf_expected[target_ch] = min_seq

                    while buf_expected[target_ch] in target_buf:
                        target_buf.pop(buf_expected[target_ch])
                        buf_expected[target_ch] += 1
                        drained_count += 1

                    if target_buf:
                        new_oldest_t = min(item['timestamp'] for item in target_buf.values())
                        heapq.heappush(timeout_heap, (new_oldest_t + timeout_ms, target_ch))

        exp = buf_expected[ch]
        ch_buf = buffers[ch]

        if seq < exp:
            dropped_stale_count += 1
            buf_statuses[eid] = "DROPPED_STALE"
        elif seq == exp:
            buf_expected[ch] += 1
            drained_here = 0
            while buf_expected[ch] in ch_buf:
                ch_buf.pop(buf_expected[ch])
                buf_expected[ch] += 1
                drained_count += 1
                drained_here += 1

            if drained_here > 0:
                buf_statuses[eid] = f"PROCESSED(DRAINED:{drained_here})"
            else:
                buf_statuses[eid] = "PROCESSED"
        else:
            if len(ch_buf) >= max_buf:
                overflow_dropped += 1
                buf_statuses[eid] = "BUFFER_FULL_DROPPED"
            else:
                was_empty = (len(ch_buf) == 0)
                ch_buf[seq] = {'state': st, 'timestamp': t, 'ev_id': eid}
                buffered_count += 1
                buf_statuses[eid] = "BUFFERED"
                if was_empty:
                    heapq.heappush(timeout_heap, (t + timeout_ms, ch))

    for ev in raw_events:
        eid = ev['ev_id']
        sys.stdout.write(f"EVENT {eid} NAIVE:{naive_statuses[eid]} BUFFERED:{buf_statuses[eid]}\n")

    sys.stdout.write(f"SUMMARY NAIVE PROCESSED:{naive_processed} REGRESSIONS:{naive_inversions} JUMPS:{naive_jumps}\n")
    sys.stdout.write(f"SUMMARY BUFFERED BUFFERED:{buffered_count} DRAINED:{drained_count} DROPPED_STALE:{dropped_stale_count} TIMEOUT_GAPS:{timeout_gaps} OVERFLOW_DROPPED:{overflow_dropped}\n")
    sys.stdout.write(f"SUMMARY ANOMALIES_PREVENTED:{naive_inversions + naive_jumps}\n")

if __name__ == '__main__':
    solve()
