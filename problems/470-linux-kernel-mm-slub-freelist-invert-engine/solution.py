import sys
import json
import copy

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

class SlubEngine:
    def __init__(self, config):
        self.obj_size = config.get('obj_size', 64)
        self.objs_per_slab = config.get('objs_per_slab', 4)
        self.min_partial = config.get('min_partial', 1)
        self.nr_cpus = config.get('nr_cpus', 2)
        
        self.cpu_slabs = {c: {'slab_id': None, 'freelist': []} for c in range(self.nr_cpus)}
        self.slabs = {}
        self.next_slab_id = 0
        self.node_partial = []
        self.allocations = {}
        
        self.stats = {
            'fast_path_allocs': 0,
            'slow_path_inverts': 0,
            'partial_harvests': 0,
            'buddy_new_slabs': 0,
            'local_frees': 0,
            'remote_frees': 0,
            'slabs_freed_to_buddy': 0
        }

    def alloc(self, cpu, alloc_id):
        if self.cpu_slabs[cpu]['freelist']:
            obj = self.cpu_slabs[cpu]['freelist'].pop(0)
            sid = self.cpu_slabs[cpu]['slab_id']
            self.slabs[sid]['inuse'] += 1
            self.allocations[alloc_id] = {'slab_id': sid, 'obj': obj}
            self.stats['fast_path_allocs'] += 1
            return {'status': 'SUCCESS', 'path': 'FAST_PATH', 'slab_id': sid, 'obj': obj}
            
        cur_sid = self.cpu_slabs[cpu]['slab_id']
        if cur_sid is not None:
            cur_slab = self.slabs[cur_sid]
            if cur_slab['remote_freelist']:
                self.cpu_slabs[cpu]['freelist'] = list(cur_slab['remote_freelist'])
                cur_slab['remote_freelist'] = []
                obj = self.cpu_slabs[cpu]['freelist'].pop(0)
                cur_slab['inuse'] += 1
                self.allocations[alloc_id] = {'slab_id': cur_sid, 'obj': obj}
                self.stats['slow_path_inverts'] += 1
                return {'status': 'SUCCESS', 'path': 'SLOW_PATH_INVERT', 'slab_id': cur_sid, 'obj': obj}
            else:
                cur_slab['frozen_by_cpu'] = None
                self.cpu_slabs[cpu]['slab_id'] = None
                
        if self.node_partial:
            new_sid = self.node_partial.pop(0)
            new_slab = self.slabs[new_sid]
            new_slab['frozen_by_cpu'] = cpu
            self.cpu_slabs[cpu]['slab_id'] = new_sid
            self.cpu_slabs[cpu]['freelist'] = list(new_slab['remote_freelist'])
            new_slab['remote_freelist'] = []
            obj = self.cpu_slabs[cpu]['freelist'].pop(0)
            new_slab['inuse'] += 1
            self.allocations[alloc_id] = {'slab_id': new_sid, 'obj': obj}
            self.stats['partial_harvests'] += 1
            return {'status': 'SUCCESS', 'path': 'PARTIAL_HARVEST', 'slab_id': new_sid, 'obj': obj}
            
        new_sid = self.next_slab_id
        self.next_slab_id += 1
        objs = [f's{new_sid}_o{i}' for i in range(self.objs_per_slab)]
        self.slabs[new_sid] = {
            'slab_id': new_sid,
            'frozen_by_cpu': cpu,
            'inuse': 1,
            'remote_freelist': [],
            'objects': objs
        }
        self.cpu_slabs[cpu]['slab_id'] = new_sid
        obj = objs[0]
        self.cpu_slabs[cpu]['freelist'] = objs[1:]
        self.allocations[alloc_id] = {'slab_id': new_sid, 'obj': obj}
        self.stats['buddy_new_slabs'] += 1
        return {'status': 'SUCCESS', 'path': 'BUDDY_NEW_SLAB', 'slab_id': new_sid, 'obj': obj}

    def free(self, cpu, alloc_id):
        if alloc_id not in self.allocations:
            return {'status': 'FAIL', 'error': 'ENOENT_ALLOC_NOT_FOUND'}
        info = self.allocations.pop(alloc_id)
        sid = info['slab_id']
        obj = info['obj']
        slab = self.slabs[sid]
        prev_inuse = slab['inuse']
        slab['inuse'] -= 1
        
        fz = slab['frozen_by_cpu']
        if fz is not None:
            if fz == cpu:
                self.cpu_slabs[cpu]['freelist'].insert(0, obj)
                self.stats['local_frees'] += 1
                return {'status': 'SUCCESS', 'type': 'LOCAL_FREE', 'slab_id': sid, 'obj': obj}
            else:
                slab['remote_freelist'].insert(0, obj)
                self.stats['remote_frees'] += 1
                return {'status': 'SUCCESS', 'type': 'REMOTE_FREE_FROZEN', 'slab_id': sid, 'frozen_by': fz, 'obj': obj}
        else:
            slab['remote_freelist'].insert(0, obj)
            if prev_inuse == self.objs_per_slab:
                if sid not in self.node_partial:
                    self.node_partial.append(sid)
                return {'status': 'SUCCESS', 'type': 'UNFROZEN_TO_PARTIAL', 'slab_id': sid, 'obj': obj}
            elif slab['inuse'] == 0:
                if len(self.node_partial) > self.min_partial:
                    if sid in self.node_partial:
                        self.node_partial.remove(sid)
                    del self.slabs[sid]
                    self.stats['slabs_freed_to_buddy'] += 1
                    return {'status': 'SUCCESS', 'type': 'EMPTY_SLAB_FREED_TO_BUDDY', 'slab_id': sid, 'obj': obj}
                else:
                    return {'status': 'SUCCESS', 'type': 'EMPTY_SLAB_KEPT_IN_PARTIAL', 'slab_id': sid, 'obj': obj}
            else:
                return {'status': 'SUCCESS', 'type': 'UNFROZEN_PARTIAL_FREE', 'slab_id': sid, 'obj': obj}

    def run(self, ops):
        results = []
        for idx, op in enumerate(ops):
            t = op['type']
            if t == 'ALLOC_OBJECT':
                cpu = op['cpu']
                aid = op['alloc_id']
                res = self.alloc(cpu, aid)
                results.append({'op_index': idx, 'type': t, 'cpu': cpu, 'alloc_id': aid, **res})
            elif t == 'FREE_OBJECT':
                cpu = op['cpu']
                aid = op['alloc_id']
                res = self.free(cpu, aid)
                results.append({'op_index': idx, 'type': t, 'cpu': cpu, 'alloc_id': aid, **res})
            elif t == 'QUERY_SLUB_STATE':
                results.append({
                    'op_index': idx,
                    'type': t,
                    'cpu_slabs': {
                        str(c): {
                            'slab_id': self.cpu_slabs[c]['slab_id'],
                            'local_freelist_len': len(self.cpu_slabs[c]['freelist'])
                        } for c in range(self.nr_cpus)
                    },
                    'node_partial_slabs': list(self.node_partial),
                    'active_slabs_count': len(self.slabs),
                    'stats': dict(self.stats)
                })

        summary = {
            'total_operations': len(ops),
            'active_allocations_count': len(self.allocations),
            'active_slabs_count': len(self.slabs),
            'node_partial_count': len(self.node_partial),
            'stats': dict(self.stats)
        }
        return {'operation_results': results, 'summary': summary}

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    engine = SlubEngine(data.get('config', {}))
    res = engine.run(data['operations'])
    print(json.dumps(res, separators=(',', ':'), ensure_ascii=False))

if __name__ == '__main__':
    main()
