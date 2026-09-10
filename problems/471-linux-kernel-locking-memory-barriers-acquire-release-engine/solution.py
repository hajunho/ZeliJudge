import sys
import json
import copy

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

class LkmmEngine:
    def __init__(self, config):
        self.arch = config.get('arch', 'WEAK')
        self.memory = dict(config.get('initial_memory', {}))
        self.nr_cpus = config.get('nr_cpus', 2)
        self.store_buffers = {c: [] for c in range(self.nr_cpus)}
        self.speculative_reads = {c: {} for c in range(self.nr_cpus)}
        self.read_results = {}
        self.stats = {
            'writes': 0,
            'reads': 0,
            'store_buffer_flushes': 0,
            'acquire_barriers': 0,
            'release_barriers': 0,
            'full_mb_barriers': 0
        }

    def run(self, ops):
        results = []
        for idx, op in enumerate(ops):
            t = op['type']
            if t == 'WRITE':
                c = op['cpu']
                var = op['var']
                val = op['val']
                barrier = op.get('barrier', 'NONE')
                self.stats['writes'] += 1
                
                if barrier in ('RELEASE', 'FULL_MB'):
                    if barrier == 'RELEASE':
                        self.stats['release_barriers'] += 1
                    else:
                        self.stats['full_mb_barriers'] += 1
                    flushed = len(self.store_buffers[c])
                    while self.store_buffers[c]:
                        st = self.store_buffers[c].pop(0)
                        self.memory[st['var']] = st['val']
                    self.memory[var] = val
                    results.append({
                        'op_index': idx,
                        'type': t,
                        'cpu': c,
                        'var': var,
                        'val': val,
                        'barrier': barrier,
                        'flushed_stores': flushed,
                        'committed_to_shared': True
                    })
                else:
                    self.store_buffers[c].append({'var': var, 'val': val})
                    results.append({
                        'op_index': idx,
                        'type': t,
                        'cpu': c,
                        'var': var,
                        'val': val,
                        'barrier': barrier,
                        'buffered': True,
                        'store_buffer_depth': len(self.store_buffers[c])
                    })
            elif t == 'SPECULATIVE_PREFETCH_READ':
                c = op['cpu']
                var = op['var']
                read_id = op['read_id']
                val = self.memory.get(var, 0)
                self.speculative_reads[c][var] = {'val': val, 'read_id': read_id}
                results.append({
                    'op_index': idx,
                    'type': t,
                    'cpu': c,
                    'var': var,
                    'read_id': read_id,
                    'staged_val': val,
                    'status': 'SPECULATIVE_LOAD_STAGED'
                })
            elif t == 'READ':
                c = op['cpu']
                var = op['var']
                read_id = op.get('read_id', f'r_{idx}')
                barrier = op.get('barrier', 'NONE')
                self.stats['reads'] += 1
                
                if barrier in ('ACQUIRE', 'FULL_MB'):
                    if barrier == 'ACQUIRE':
                        self.stats['acquire_barriers'] += 1
                    else:
                        self.stats['full_mb_barriers'] += 1
                    self.speculative_reads[c].clear()
                    
                val = None
                source = None
                if barrier == 'NONE' and var in self.speculative_reads[c]:
                    spec = self.speculative_reads[c].pop(var)
                    val = spec['val']
                    source = 'SPECULATIVE_PREFETCH_STALE'
                else:
                    for st in reversed(self.store_buffers[c]):
                        if st['var'] == var:
                            val = st['val']
                            source = 'STORE_FORWARDING'
                            break
                    if val is None:
                        val = self.memory.get(var, 0)
                        source = 'SHARED_COHERENT_MEMORY'
                        
                self.read_results[read_id] = val
                results.append({
                    'op_index': idx,
                    'type': t,
                    'cpu': c,
                    'var': var,
                    'read_id': read_id,
                    'val': val,
                    'source': source,
                    'barrier': barrier
                })
            elif t == 'FLUSH_STORE_BUFFER':
                c = op['cpu']
                count = op.get('count', len(self.store_buffers[c]))
                self.stats['store_buffer_flushes'] += 1
                flushed_entries = []
                while self.store_buffers[c] and len(flushed_entries) < count:
                    st = self.store_buffers[c].pop(0)
                    self.memory[st['var']] = st['val']
                    flushed_entries.append(st)
                results.append({
                    'op_index': idx,
                    'type': t,
                    'cpu': c,
                    'flushed_count': len(flushed_entries),
                    'flushed_entries': flushed_entries,
                    'remaining_depth': len(self.store_buffers[c])
                })
            elif t == 'QUERY_STATE':
                results.append({
                    'op_index': idx,
                    'type': t,
                    'shared_memory': dict(self.memory),
                    'store_buffers': {str(c): list(sb) for c, sb in self.store_buffers.items()},
                    'read_results': dict(self.read_results)
                })

        summary = {
            'total_operations': len(ops),
            'final_shared_memory': dict(self.memory),
            'store_buffers_count': {str(c): len(sb) for c, sb in self.store_buffers.items()},
            'read_results': dict(self.read_results),
            'stats': dict(self.stats)
        }
        return {'operation_results': results, 'summary': summary}

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    d = copy.deepcopy(data)
    engine = LkmmEngine(d.get('config', {}))
    res = engine.run(d['operations'])
    print(json.dumps(res, separators=(',', ':'), ensure_ascii=False))

if __name__ == '__main__':
    main()
