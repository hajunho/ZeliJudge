import sys
import json

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

class Srv6Engine:
    def __init__(self, config):
        self.local_sids = dict(config.get('local_sids', {}))
        self.fib = dict(config.get('fib', {}))
        self.vrf_tables = dict(config.get('vrf_tables', {}))
        self.stats = {
            'transit_end': 0,
            'decap_dx4': 0,
            'decap_dt6': 0,
            'ip_forward': 0,
            'dropped': 0
        }

    def run(self, ops):
        results = []
        for idx, op in enumerate(ops):
            t = op['type']
            if t == 'ADD_LOCAL_SID':
                sid = op['sid']
                entry = op['entry']
                self.local_sids[sid] = entry
                results.append({'op_index': idx, 'type': t, 'status': 'SUCCESS', 'sid': sid})
            elif t == 'ROUTE_PACKET':
                pkt = op['packet']
                outer = pkt.get('outer_ipv6', {})
                srh = pkt.get('srh')
                inner = pkt.get('inner_payload')
                
                hl = outer.get('hop_limit', 64)
                if hl <= 1:
                    self.stats['dropped'] += 1
                    results.append({'op_index': idx, 'type': t, 'status': 'DROP', 'error': 'TIME_EXCEEDED_HOP_LIMIT'})
                    continue
                    
                dst = outer.get('dst')
                if dst in self.local_sids:
                    sid_entry = self.local_sids[dst]
                    action = sid_entry['action']
                    
                    if action == 'End':
                        if not srh or srh.get('segments_left', 0) <= 0:
                            self.stats['dropped'] += 1
                            results.append({'op_index': idx, 'type': t, 'status': 'DROP', 'error': 'INVALID_SRH_SEGMENTS_LEFT'})
                            continue
                        srh['segments_left'] -= 1
                        new_dst = srh['segments'][srh['segments_left']]
                        outer['dst'] = new_dst
                        outer['hop_limit'] = hl - 1
                        nh = self.fib.get(new_dst, {'next_hop': 'default_gw', 'out_if': 'eth0'})
                        self.stats['transit_end'] += 1
                        results.append({
                            'op_index': idx,
                            'type': t,
                            'status': 'TRANSIT_END',
                            'new_dst': new_dst,
                            'segments_left': srh['segments_left'],
                            'next_hop': nh.get('next_hop'),
                            'out_if': nh.get('out_if')
                        })
                    elif action == 'End.DX4':
                        if srh and srh.get('segments_left', 0) != 0:
                            self.stats['dropped'] += 1
                            results.append({'op_index': idx, 'type': t, 'status': 'DROP', 'error': 'DX4_SEGMENTS_LEFT_NOT_ZERO'})
                            continue
                        if not inner or inner.get('type') != 'IPV4':
                            self.stats['dropped'] += 1
                            results.append({'op_index': idx, 'type': t, 'status': 'DROP', 'error': 'DX4_PAYLOAD_NOT_IPV4'})
                            continue
                        self.stats['decap_dx4'] += 1
                        results.append({
                            'op_index': idx,
                            'type': t,
                            'status': 'DECAP_DX4',
                            'inner_dst': inner.get('dst'),
                            'nh4': sid_entry.get('nh4'),
                            'out_if': sid_entry.get('out_if')
                        })
                    elif action == 'End.DT6':
                        if srh and srh.get('segments_left', 0) != 0:
                            self.stats['dropped'] += 1
                            results.append({'op_index': idx, 'type': t, 'status': 'DROP', 'error': 'DT6_SEGMENTS_LEFT_NOT_ZERO'})
                            continue
                        if not inner or inner.get('type') != 'IPV6':
                            self.stats['dropped'] += 1
                            results.append({'op_index': idx, 'type': t, 'status': 'DROP', 'error': 'DT6_PAYLOAD_NOT_IPV6'})
                            continue
                        vrf_id = sid_entry.get('vrf_table')
                        vrf_routes = self.vrf_tables.get(str(vrf_id), {})
                        inner_dst = inner.get('dst')
                        nh = vrf_routes.get(inner_dst)
                        if not nh:
                            self.stats['dropped'] += 1
                            results.append({'op_index': idx, 'type': t, 'status': 'DROP', 'error': 'VRF_ROUTE_LOOKUP_FAILED', 'vrf_id': vrf_id})
                            continue
                        self.stats['decap_dt6'] += 1
                        results.append({
                            'op_index': idx,
                            'type': t,
                            'status': 'DECAP_DT6',
                            'vrf_id': vrf_id,
                            'inner_dst': inner_dst,
                            'next_hop': nh.get('next_hop'),
                            'out_if': nh.get('out_if')
                        })
                else:
                    outer['hop_limit'] = hl - 1
                    nh = self.fib.get(dst)
                    if not nh:
                        self.stats['dropped'] += 1
                        results.append({'op_index': idx, 'type': t, 'status': 'DROP', 'error': 'NO_ROUTE_TO_HOST'})
                        continue
                    self.stats['ip_forward'] += 1
                    results.append({
                        'op_index': idx,
                        'type': t,
                        'status': 'IP_FORWARD',
                        'dst': dst,
                        'next_hop': nh.get('next_hop'),
                        'out_if': nh.get('out_if')
                    })
            elif t == 'QUERY_STATS':
                results.append({
                    'op_index': idx,
                    'type': t,
                    'stats': dict(self.stats)
                })

        summary = {
            'total_operations': len(ops),
            'stats': dict(self.stats)
        }
        return {'operation_results': results, 'summary': summary}

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    engine = Srv6Engine(data.get('config', {}))
    res = engine.run(data['operations'])
    print(json.dumps(res, separators=(',', ':'), ensure_ascii=False))

if __name__ == '__main__':
    main()
