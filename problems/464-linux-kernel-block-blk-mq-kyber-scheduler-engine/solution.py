import sys
import json
import math
import heapq

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

def run_simulation(data):
    config = data['config']
    nr_hw = config['nr_hw_queues']
    queue_depth = config['queue_depth']
    scheduler = config.get('scheduler', 'none')
    read_target_us = config.get('read_target_us', 2000)
    write_target_us = config.get('write_target_us', 10000)
    init_tokens = config.get('initial_write_tokens', queue_depth // 2 or 1)
    min_tokens = config.get('min_write_tokens', 1)
    max_tokens = config.get('max_write_tokens', queue_depth)
    
    write_tokens = {h: init_tokens for h in range(nr_hw)}
    hctx_in_flight = {h: 0 for h in range(nr_hw)}
    hctx_write_in_flight = {h: 0 for h in range(nr_hw)}
    
    staging_fifo = {h: [] for h in range(nr_hw)}
    staging_reads = {h: [] for h in range(nr_hw)}
    staging_writes = {h: [] for h in range(nr_hw)}
    
    window_reads = {h: [] for h in range(nr_hw)}
    window_writes = {h: [] for h in range(nr_hw)}
    
    all_requests = {}
    completed_requests = {}
    dispatched_count = 0
    current_time = 0
    comp_pq = []
    seq = 0
    
    def advance_time(target_time):
        nonlocal current_time, seq
        while comp_pq and comp_pq[0][0] <= target_time:
            c_time, _, req = heapq.heappop(comp_pq)
            current_time = c_time
            h = req['hctx_id']
            op = req['op_type']
            hctx_in_flight[h] -= 1
            if op == 'WRITE':
                hctx_write_in_flight[h] -= 1
            req['complete_time'] = c_time
            req['total_lat_us'] = c_time - req['submit_time']
            completed_requests[req['req_id']] = req
            
            if op == 'READ':
                window_reads[h].append(req['total_lat_us'])
            else:
                window_writes[h].append(req['total_lat_us'])
            try_dispatch(h, c_time)
        current_time = max(current_time, target_time)

    def try_dispatch(h, cur_time):
        nonlocal dispatched_count, seq
        while hctx_in_flight[h] < queue_depth:
            dispatched_any = False
            if scheduler == 'none':
                if staging_fifo[h]:
                    req = staging_fifo[h].pop(0)
                    dispatch_req(req, cur_time)
                    dispatched_any = True
            elif scheduler == 'kyber':
                if staging_reads[h]:
                    req = staging_reads[h].pop(0)
                    dispatch_req(req, cur_time)
                    dispatched_any = True
                elif staging_writes[h]:
                    if hctx_write_in_flight[h] < write_tokens[h]:
                        req = staging_writes[h].pop(0)
                        dispatch_req(req, cur_time)
                        dispatched_any = True
                    else:
                        break
            if not dispatched_any:
                break

    def dispatch_req(req, cur_time):
        nonlocal dispatched_count, seq
        h = req['hctx_id']
        hctx_in_flight[h] += 1
        if req['op_type'] == 'WRITE':
            hctx_write_in_flight[h] += 1
        req['dispatch_time'] = cur_time
        req['queue_lat_us'] = cur_time - req['submit_time']
        dispatched_count += 1
        c_time = cur_time + req['device_latency_us']
        seq += 1
        heapq.heappush(comp_pq, (c_time, seq, req))

    op_results = []
    for idx, op in enumerate(data['operations']):
        op_type = op['type']
        ts = op['timestamp_us']
        advance_time(ts)
        
        if op_type == 'SUBMIT':
            h = op.get('hctx_id', 0)
            req = {
                'req_id': op['req_id'],
                'cpu_id': op.get('cpu_id', 0),
                'hctx_id': h,
                'op_type': op['op_type'],
                'device_latency_us': op['device_latency_us'],
                'submit_time': ts,
                'dispatch_time': None,
                'complete_time': None,
                'queue_lat_us': None,
                'total_lat_us': None
            }
            all_requests[req['req_id']] = req
            
            if scheduler == 'none':
                staging_fifo[h].append(req)
            else:
                if req['op_type'] == 'READ':
                    staging_reads[h].append(req)
                else:
                    staging_writes[h].append(req)
            
            try_dispatch(h, ts)
            
            is_disp = req['dispatch_time'] is not None
            op_results.append({
                'op_index': idx,
                'type': 'SUBMIT',
                'req_id': req['req_id'],
                'status': 'DISPATCHED' if is_disp else 'QUEUED',
                'hctx_id': h,
                'in_flight': hctx_in_flight[h]
            })
            
        elif op_type == 'SAMPLE_INTERVAL_EXPIRED':
            adjustments = {}
            for h in range(nr_hw):
                r_lats = sorted(window_reads[h])
                w_lats = sorted(window_writes[h])
                
                def calc_p99(arr):
                    if not arr: return 0
                    i = max(0, math.ceil(0.99 * len(arr)) - 1)
                    return arr[i]
                
                p99_r = calc_p99(r_lats)
                p99_w = calc_p99(w_lats)
                
                old_tok = write_tokens[h]
                if p99_r > read_target_us:
                    new_tok = max(min_tokens, old_tok // 2)
                    act = 'THROTTLE_READ_CONGESTION'
                elif p99_w > write_target_us:
                    new_tok = max(min_tokens, old_tok - 1)
                    act = 'THROTTLE_WRITE_LATENCY'
                else:
                    new_tok = min(max_tokens, old_tok + 1)
                    act = 'EXPAND_TOKENS'
                
                write_tokens[h] = new_tok
                adjustments[str(h)] = {
                    'p99_read_us': p99_r,
                    'p99_write_us': p99_w,
                    'old_tokens': old_tok,
                    'new_tokens': new_tok,
                    'action': act
                }
                window_reads[h] = []
                window_writes[h] = []
                try_dispatch(h, ts)
                
            op_results.append({
                'op_index': idx,
                'type': 'SAMPLE_INTERVAL_EXPIRED',
                'timestamp_us': ts,
                'adjustments': adjustments
            })
            
        elif op_type == 'QUERY_STATS':
            hctx_list = []
            for h in range(nr_hw):
                q_r = len(staging_reads[h]) if scheduler == 'kyber' else len([r for r in staging_fifo[h] if r['op_type'] == 'READ'])
                q_w = len(staging_writes[h]) if scheduler == 'kyber' else len([r for r in staging_fifo[h] if r['op_type'] == 'WRITE'])
                hctx_list.append({
                    'hctx_id': h,
                    'in_flight': hctx_in_flight[h],
                    'write_in_flight': hctx_write_in_flight[h],
                    'write_tokens': write_tokens[h],
                    'queued_reads': q_r,
                    'queued_writes': q_w
                })
            op_results.append({
                'op_index': idx,
                'type': 'QUERY_STATS',
                'timestamp_us': ts,
                'dispatched_count': dispatched_count,
                'completed_count': len(completed_requests),
                'hctx_stats': hctx_list
            })
            
        elif op_type == 'DRAIN_ALL':
            while comp_pq:
                next_time = comp_pq[0][0]
                advance_time(next_time)
            advance_time(ts)
            op_results.append({
                'op_index': idx,
                'type': 'DRAIN_ALL',
                'timestamp_us': current_time,
                'total_completed': len(completed_requests)
            })

    reads = [r for r in all_requests.values() if r['op_type'] == 'READ' and r['complete_time'] is not None]
    writes = [r for r in all_requests.values() if r['op_type'] == 'WRITE' and r['complete_time'] is not None]
    
    def calc_stats(arr):
        if not arr:
            return {'count': 0, 'avg_queue_lat_us': 0.0, 'avg_total_lat_us': 0.0, 'max_total_lat_us': 0}
        avg_q = round(sum(r['queue_lat_us'] for r in arr) / len(arr), 2)
        avg_tot = round(sum(r['total_lat_us'] for r in arr) / len(arr), 2)
        max_tot = max(r['total_lat_us'] for r in arr)
        return {
            'count': len(arr),
            'avg_queue_lat_us': avg_q,
            'avg_total_lat_us': avg_tot,
            'max_total_lat_us': max_tot
        }
        
    req_list = []
    for k in sorted(all_requests.keys()):
        r = all_requests[k]
        req_list.append({
            'req_id': r['req_id'],
            'op_type': r['op_type'],
            'hctx_id': r['hctx_id'],
            'submit_time': r['submit_time'],
            'dispatch_time': r['dispatch_time'],
            'complete_time': r['complete_time'],
            'queue_lat_us': r['queue_lat_us'],
            'device_lat_us': r['device_latency_us'],
            'total_lat_us': r['total_lat_us']
        })
        
    return {
        'operation_results': op_results,
        'summary': {
            'total_submitted': len(all_requests),
            'total_dispatched': dispatched_count,
            'total_completed': len(completed_requests),
            'read_stats': calc_stats(reads),
            'write_stats': calc_stats(writes),
            'requests': req_list
        }
    }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    res = run_simulation(data)
    print(json.dumps(res, separators=(',', ':'), ensure_ascii=False))

if __name__ == '__main__':
    main()
