import sys
import json

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

class HugeTlbEngine:
    def __init__(self, config):
        self.total_memory_gb = config['total_memory_gb']
        self.cma_size_gb = config['cma_size_gb']
        self.persistent_target = config.get('boot_gigantic_pages', 2)
        self.max_surplus = config.get('max_overcommit_surplus', 2)
        
        self.cma_slots = []
        for i in range(self.cma_size_gb):
            if i < self.persistent_target:
                self.cma_slots.append({
                    'slot_id': i,
                    'state': 'GIGANTIC_ALLOCATED',
                    'movable_pages': 0,
                    'unmovable_pinned': 0,
                    'page_id': f'boot-huge-{i}'
                })
            else:
                self.cma_slots.append({
                    'slot_id': i,
                    'state': 'CMA_FREE',
                    'movable_pages': 0,
                    'unmovable_pinned': 0,
                    'page_id': None
                })
                
        self.nr_huge_pages = self.persistent_target
        self.free_huge_pages = self.persistent_target
        self.surplus_huge_pages = 0
        
        self.cgroups = {}
        for cg, limit in config.get('cgroup_limits', {}).items():
            self.cgroups[cg] = {'max': limit, 'current': 0}
            
        self.active_allocations = {}
        self.free_pool = [f'boot-huge-{i}' for i in range(self.persistent_target)]
        self.page_to_slot = {f'boot-huge-{i}': i for i in range(self.persistent_target)}
        self.next_page_seq = 0
        
        self.total_migrated_pages = 0
        self.successful_allocations = 0
        self.failed_allocations = 0

    def run(self, ops):
        results = []
        for idx, op in enumerate(ops):
            t = op['type']
            if t == 'POPULATE_CMA_MOVABLE':
                sid = op['slot_id']
                if sid < 0 or sid >= len(self.cma_slots):
                    results.append({'op_index': idx, 'type': t, 'status': 'FAIL', 'slot_id': sid, 'error': 'EINVAL_INVALID_SLOT'})
                    continue
                slot = self.cma_slots[sid]
                if slot['state'] != 'CMA_FREE':
                    results.append({'op_index': idx, 'type': t, 'status': 'FAIL', 'slot_id': sid, 'error': 'EINVAL_SLOT_OCCUPIED'})
                else:
                    slot['state'] = 'CMA_MOVABLE_OCCUPIED'
                    slot['movable_pages'] = op.get('movable_pages', 0)
                    slot['unmovable_pinned'] = op.get('unmovable_pinned', 0)
                    results.append({'op_index': idx, 'type': t, 'status': 'SUCCESS', 'slot_id': sid, 'movable_pages': slot['movable_pages'], 'unmovable_pinned': slot['unmovable_pinned']})
            elif t == 'ALLOC_GIGANTIC_PAGE':
                req_id = op['req_id']
                cg = op.get('cgroup_id')
                if cg:
                    if cg not in self.cgroups:
                        self.cgroups[cg] = {'max': float('inf'), 'current': 0}
                    if self.cgroups[cg]['current'] + 1 > self.cgroups[cg]['max']:
                        self.failed_allocations += 1
                        results.append({'op_index': idx, 'type': t, 'status': 'FAIL', 'req_id': req_id, 'error': 'ENOSPC_CGROUP_LIMIT', 'cgroup': cg})
                        continue
                if self.free_huge_pages > 0:
                    page_id = self.free_pool.pop(0)
                    slot_id = self.page_to_slot[page_id]
                    self.free_huge_pages -= 1
                    if cg:
                        self.cgroups[cg]['current'] += 1
                    self.active_allocations[req_id] = {
                        'page_id': page_id,
                        'slot_id': slot_id,
                        'cgroup_id': cg,
                        'is_surplus': False
                    }
                    self.successful_allocations += 1
                    results.append({'op_index': idx, 'type': t, 'status': 'SUCCESS', 'req_id': req_id, 'source': 'PERSISTENT_POOL', 'page_id': page_id, 'slot_id': slot_id, 'migrated_pages': 0})
                else:
                    if self.surplus_huge_pages >= self.max_surplus:
                        self.failed_allocations += 1
                        results.append({'op_index': idx, 'type': t, 'status': 'FAIL', 'req_id': req_id, 'error': 'ENOMEM_SURPLUS_EXHAUSTED'})
                        continue
                    target_slot = None
                    migrated = 0
                    for s in self.cma_slots:
                        if s['state'] == 'CMA_FREE':
                            target_slot = s
                            break
                    if not target_slot:
                        for s in self.cma_slots:
                            if s['state'] == 'CMA_MOVABLE_OCCUPIED':
                                if s['unmovable_pinned'] > 0:
                                    self.failed_allocations += 1
                                    results.append({'op_index': idx, 'type': t, 'status': 'FAIL', 'req_id': req_id, 'error': 'EBUSY_PAGE_PINNED', 'slot_id': s['slot_id']})
                                    target_slot = 'PINNED_ERROR'
                                    break
                                else:
                                    target_slot = s
                                    migrated = s['movable_pages']
                                    break
                    if target_slot == 'PINNED_ERROR':
                        continue
                    if not target_slot:
                        self.failed_allocations += 1
                        results.append({'op_index': idx, 'type': t, 'status': 'FAIL', 'req_id': req_id, 'error': 'ENOMEM_FRAGMENTATION'})
                        continue
                    self.next_page_seq += 1
                    page_id = f'dyn-huge-{self.next_page_seq}'
                    slot_id = target_slot['slot_id']
                    target_slot['state'] = 'GIGANTIC_ALLOCATED'
                    target_slot['page_id'] = page_id
                    target_slot['movable_pages'] = 0
                    target_slot['unmovable_pinned'] = 0
                    self.page_to_slot[page_id] = slot_id
                    self.nr_huge_pages += 1
                    self.surplus_huge_pages += 1
                    self.total_migrated_pages += migrated
                    if cg:
                        self.cgroups[cg]['current'] += 1
                    self.active_allocations[req_id] = {
                        'page_id': page_id,
                        'slot_id': slot_id,
                        'cgroup_id': cg,
                        'is_surplus': True
                    }
                    self.successful_allocations += 1
                    results.append({'op_index': idx, 'type': t, 'status': 'SUCCESS', 'req_id': req_id, 'source': 'CMA_MIGRATION' if migrated > 0 else 'CMA_FREE', 'page_id': page_id, 'slot_id': slot_id, 'migrated_pages': migrated})
            elif t == 'FREE_GIGANTIC_PAGE':
                req_id = op['req_id']
                if req_id not in self.active_allocations:
                    results.append({'op_index': idx, 'type': t, 'status': 'FAIL', 'req_id': req_id, 'error': 'ENOENT_REQ_NOT_FOUND'})
                else:
                    alloc = self.active_allocations.pop(req_id)
                    cg = alloc['cgroup_id']
                    if cg and cg in self.cgroups:
                        self.cgroups[cg]['current'] -= 1
                    page_id = alloc['page_id']
                    slot_id = alloc['slot_id']
                    if alloc['is_surplus']:
                        self.surplus_huge_pages -= 1
                        self.nr_huge_pages -= 1
                        del self.page_to_slot[page_id]
                        slot = self.cma_slots[slot_id]
                        slot['state'] = 'CMA_FREE'
                        slot['page_id'] = None
                        act = 'DISSOLVED_TO_CMA'
                    else:
                        self.free_huge_pages += 1
                        self.free_pool.append(page_id)
                        act = 'RETURNED_TO_POOL'
                    results.append({'op_index': idx, 'type': t, 'status': 'SUCCESS', 'req_id': req_id, 'action': act, 'page_id': page_id, 'slot_id': slot_id})
            elif t == 'DISSOLVE_GIGANTIC_PAGE':
                sid = op['slot_id']
                if sid < 0 or sid >= len(self.cma_slots):
                    results.append({'op_index': idx, 'type': t, 'status': 'FAIL', 'slot_id': sid, 'error': 'EINVAL_INVALID_SLOT'})
                else:
                    slot = self.cma_slots[sid]
                    if slot['state'] != 'GIGANTIC_ALLOCATED':
                        results.append({'op_index': idx, 'type': t, 'status': 'FAIL', 'slot_id': sid, 'error': 'EINVAL_NOT_GIGANTIC'})
                    else:
                        pid = slot['page_id']
                        if pid not in self.free_pool:
                            results.append({'op_index': idx, 'type': t, 'status': 'FAIL', 'slot_id': sid, 'error': 'EBUSY_PAGE_IN_USE'})
                        else:
                            self.free_pool.remove(pid)
                            del self.page_to_slot[pid]
                            self.free_huge_pages -= 1
                            self.nr_huge_pages -= 1
                            self.persistent_target = max(0, self.persistent_target - 1)
                            slot['state'] = 'CMA_FREE'
                            slot['page_id'] = None
                            results.append({'op_index': idx, 'type': t, 'status': 'SUCCESS', 'slot_id': sid, 'page_id': pid, 'new_nr_huge_pages': self.nr_huge_pages})
            elif t == 'QUERY_HUGETLB_INFO':
                results.append({
                    'op_index': idx,
                    'type': t,
                    'nr_huge_pages': self.nr_huge_pages,
                    'free_huge_pages': self.free_huge_pages,
                    'surplus_huge_pages': self.surplus_huge_pages,
                    'active_allocations_count': len(self.active_allocations),
                    'cma_slots': [dict(s) for s in self.cma_slots],
                    'cgroups': {k: dict(v) for k, v in self.cgroups.items()}
                })
        
        summary = {
            'total_operations': len(ops),
            'successful_allocations': self.successful_allocations,
            'failed_allocations': self.failed_allocations,
            'total_migrated_pages': self.total_migrated_pages,
            'final_nr_huge_pages': self.nr_huge_pages,
            'final_free_huge_pages': self.free_huge_pages,
            'final_surplus_huge_pages': self.surplus_huge_pages,
            'cgroup_usage': {k: dict(v) for k, v in self.cgroups.items()}
        }
        return {'operation_results': results, 'summary': summary}

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    engine = HugeTlbEngine(data['config'])
    res = engine.run(data['operations'])
    print(json.dumps(res, separators=(',', ':'), ensure_ascii=False))

if __name__ == '__main__':
    main()
