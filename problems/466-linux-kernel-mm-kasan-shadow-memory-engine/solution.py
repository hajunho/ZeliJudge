import sys
import json

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

class KasanEngine:
    KASAN_SLAB_REDZONE = 0xFB
    KASAN_SLAB_FREE = 0xFC
    KASAN_PAGE_REDZONE = 0xFA
    KASAN_SHADOW_GAP = 0xFE
    
    def __init__(self, config):
        self.shadow_offset = config.get('shadow_offset', 0xdffffc0000000000)
        self.default_redzone = config.get('default_redzone_size', 16)
        self.shadow = {}
        self.objects = {}
        self.bug_reports = []
        self.clean_accesses = 0

    def mem_to_shadow(self, addr):
        return (addr >> 3) + self.shadow_offset

    def run(self, ops):
        results = []
        for idx, op in enumerate(ops):
            t = op['type']
            if t == 'KMALLOC':
                obj_id = op['obj_id']
                addr = op['addr']
                size = op['size']
                rz_size = op.get('redzone_size', self.default_redzone)
                
                full_chunks = size // 8
                rem = size % 8
                base_g = addr >> 3
                for i in range(full_chunks):
                    self.shadow[base_g + i] = 0x00
                if rem > 0:
                    self.shadow[base_g + full_chunks] = rem
                    rz_start_g = base_g + full_chunks + 1
                else:
                    rz_start_g = base_g + full_chunks
                    
                rz_chunks = (rz_size + 7) // 8
                for i in range(rz_chunks):
                    self.shadow[rz_start_g + i] = self.KASAN_SLAB_REDZONE
                    
                total_size = (rz_start_g + rz_chunks - base_g) * 8
                self.objects[obj_id] = {
                    'obj_id': obj_id,
                    'addr': addr,
                    'size': size,
                    'redzone_size': rz_size,
                    'total_size': total_size,
                    'freed': False
                }
                results.append({
                    'op_index': idx,
                    'type': t,
                    'status': 'SUCCESS',
                    'obj_id': obj_id,
                    'addr': hex(addr),
                    'size': size,
                    'redzone_size': rz_size
                })
            elif t == 'KFREE':
                obj_id = op['obj_id']
                if obj_id not in self.objects:
                    results.append({'op_index': idx, 'type': t, 'status': 'FAIL', 'error': 'ENOENT_OBJECT_NOT_FOUND'})
                    continue
                obj = self.objects[obj_id]
                if obj['freed']:
                    report = {
                        'op_index': idx,
                        'type': t,
                        'status': 'BUG_REPORT',
                        'bug_type': 'DOUBLE_FREE',
                        'obj_id': obj_id,
                        'addr': hex(obj['addr']),
                        'size': obj['size']
                    }
                    self.bug_reports.append(report)
                    results.append(report)
                    continue
                obj['freed'] = True
                base_g = obj['addr'] >> 3
                total_chunks = obj['total_size'] // 8
                for i in range(total_chunks):
                    self.shadow[base_g + i] = self.KASAN_SLAB_FREE
                results.append({
                    'op_index': idx,
                    'type': t,
                    'status': 'SUCCESS',
                    'action': 'POISONED_SLAB_FREE',
                    'obj_id': obj_id,
                    'addr': hex(obj['addr'])
                })
            elif t in ('READ_ACCESS', 'WRITE_ACCESS'):
                addr = op['addr']
                size = op['size']
                acc_type = 'READ' if t == 'READ_ACCESS' else 'WRITE'
                
                violation = False
                fault_p = None
                fault_val = 0
                for p in range(addr, addr + size):
                    g = p >> 3
                    o = p & 7
                    val = self.shadow.get(g, self.KASAN_SHADOW_GAP)
                    if val == 0:
                        continue
                    elif 1 <= val <= 7:
                        if o >= val:
                            violation = True
                            fault_p = p
                            fault_val = val
                            break
                    else:
                        violation = True
                        fault_p = p
                        fault_val = val
                        break
                        
                if violation:
                    matched_obj = None
                    for obj in self.objects.values():
                        if obj['addr'] <= fault_p < obj['addr'] + obj['total_size']:
                            matched_obj = obj
                            break
                    if fault_val == self.KASAN_SLAB_FREE:
                        btype = 'USE_AFTER_FREE'
                    elif fault_val == self.KASAN_SLAB_REDZONE or (1 <= fault_val <= 7):
                        btype = 'SLAB_OUT_OF_BOUNDS'
                    elif fault_val == self.KASAN_PAGE_REDZONE:
                        btype = 'PAGE_ALLOC_OUT_OF_BOUNDS'
                    else:
                        btype = 'WILD_MEMORY_ACCESS'
                        
                    report = {
                        'op_index': idx,
                        'type': t,
                        'status': 'BUG_REPORT',
                        'bug_type': btype,
                        'fault_addr': hex(fault_p),
                        'access_type': acc_type,
                        'access_size': size,
                        'shadow_val': f'0x{fault_val:02x}',
                        'obj_id': matched_obj['obj_id'] if matched_obj else None,
                        'offset_from_obj': (fault_p - matched_obj['addr']) if matched_obj else None
                    }
                    self.bug_reports.append(report)
                    results.append(report)
                else:
                    self.clean_accesses += 1
                    results.append({
                        'op_index': idx,
                        'type': t,
                        'status': 'ACCESS_OK',
                        'access_type': acc_type,
                        'addr': hex(addr),
                        'size': size
                    })
            elif t == 'QUERY_SHADOW':
                addr = op['addr']
                count = op.get('count', 4)
                res = []
                base_g = addr >> 3
                for i in range(count):
                    g = base_g + i
                    k_addr = g << 3
                    s_addr = self.mem_to_shadow(k_addr)
                    v = self.shadow.get(g, self.KASAN_SHADOW_GAP)
                    res.append({
                        'kernel_addr': hex(k_addr),
                        'shadow_addr': hex(s_addr),
                        'shadow_val': f'0x{v:02x}'
                    })
                results.append({
                    'op_index': idx,
                    'type': t,
                    'status': 'SUCCESS',
                    'shadow_bytes': res
                })

        bug_types_summary = {}
        for r in self.bug_reports:
            bt = r['bug_type']
            bug_types_summary[bt] = bug_types_summary.get(bt, 0) + 1
            
        summary = {
            'total_operations': len(ops),
            'allocated_objects': len(self.objects),
            'freed_objects': len([o for o in self.objects.values() if o['freed']]),
            'clean_accesses': self.clean_accesses,
            'bug_reports_count': len(self.bug_reports),
            'bug_types_summary': bug_types_summary
        }
        return {'operation_results': results, 'summary': summary}

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    engine = KasanEngine(data.get('config', {}))
    res = engine.run(data['operations'])
    print(json.dumps(res, separators=(',', ':'), ensure_ascii=False))

if __name__ == '__main__':
    main()
