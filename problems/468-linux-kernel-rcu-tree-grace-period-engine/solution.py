import sys
import json

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

class TreeRcuEngine:
    def __init__(self, config):
        self.nr_cpus = config.get('nr_cpus', 8)
        self.fanout = config.get('fanout', 4)
        self.num_leaves = (self.nr_cpus + self.fanout - 1) // self.fanout
        
        self.cpu_nesting = {c: 0 for c in range(self.nr_cpus)}
        self.gp_number = 0
        self.gp_active = False
        
        self.leaf_qsmask = {l: 0 for l in range(self.num_leaves)}
        self.root_qsmask = 0
        
        self.pending_callbacks = []
        self.invoked_callbacks = []
        self.total_gp_started = 0
        self.total_gp_completed = 0
        self.total_cbs_registered = 0

    def run(self, ops):
        results = []
        for idx, op in enumerate(ops):
            t = op['type']
            if t == 'START_GRACE_PERIOD':
                if self.gp_active:
                    results.append({'op_index': idx, 'type': t, 'status': 'FAIL', 'error': 'EBUSY_GP_IN_PROGRESS', 'gp_number': self.gp_number})
                else:
                    self.gp_number += 1
                    self.gp_active = True
                    self.total_gp_started += 1
                    for l in range(self.num_leaves):
                        mask = 0
                        for b in range(self.fanout):
                            c = l * self.fanout + b
                            if c < self.nr_cpus:
                                mask |= (1 << b)
                        self.leaf_qsmask[l] = mask
                    if self.num_leaves > 1:
                        self.root_qsmask = (1 << self.num_leaves) - 1
                    else:
                        self.root_qsmask = self.leaf_qsmask[0]
                    results.append({
                        'op_index': idx,
                        'type': t,
                        'status': 'SUCCESS',
                        'gp_number': self.gp_number,
                        'leaf_masks': {str(l): self.leaf_qsmask[l] for l in range(self.num_leaves)},
                        'root_mask': self.root_qsmask
                    })
            elif t == 'RCU_READ_LOCK':
                c = op['cpu']
                self.cpu_nesting[c] += 1
                results.append({'op_index': idx, 'type': t, 'status': 'SUCCESS', 'cpu': c, 'nesting': self.cpu_nesting[c]})
            elif t == 'RCU_READ_UNLOCK':
                c = op['cpu']
                if self.cpu_nesting[c] <= 0:
                    results.append({'op_index': idx, 'type': t, 'status': 'FAIL', 'error': 'EINVAL_NESTING_UNDERFLOW', 'cpu': c})
                else:
                    self.cpu_nesting[c] -= 1
                    results.append({'op_index': idx, 'type': t, 'status': 'SUCCESS', 'cpu': c, 'nesting': self.cpu_nesting[c]})
            elif t == 'CPU_QUIESCENT_STATE':
                c = op['cpu']
                if self.cpu_nesting[c] > 0:
                    results.append({'op_index': idx, 'type': t, 'status': 'BLOCKED_IN_CRITICAL_SECTION', 'cpu': c, 'nesting': self.cpu_nesting[c]})
                elif not self.gp_active:
                    results.append({'op_index': idx, 'type': t, 'status': 'NO_ACTIVE_GP', 'cpu': c})
                else:
                    l = c // self.fanout
                    b = c % self.fanout
                    if not (self.leaf_qsmask[l] & (1 << b)):
                        results.append({'op_index': idx, 'type': t, 'status': 'ALREADY_REPORTED', 'cpu': c})
                    else:
                        self.leaf_qsmask[l] &= ~(1 << b)
                        leaf_cleared = (self.leaf_qsmask[l] == 0)
                        gp_completed = False
                        if leaf_cleared:
                            if self.num_leaves > 1:
                                self.root_qsmask &= ~(1 << l)
                                if self.root_qsmask == 0:
                                    gp_completed = True
                            else:
                                gp_completed = True
                        invoked_now = []
                        if gp_completed:
                            self.gp_active = False
                            self.total_gp_completed += 1
                            rem = []
                            for cb in self.pending_callbacks:
                                if cb['target_gp'] <= self.gp_number:
                                    cb_info = dict(cb)
                                    cb_info['invoked_at_gp'] = self.gp_number
                                    invoked_now.append(cb_info)
                                    self.invoked_callbacks.append(cb_info)
                                else:
                                    rem.append(cb)
                            self.pending_callbacks = rem
                        results.append({
                            'op_index': idx,
                            'type': t,
                            'status': 'QS_RECORDED',
                            'cpu': c,
                            'leaf_index': l,
                            'leaf_cleared': leaf_cleared,
                            'gp_completed': gp_completed,
                            'invoked_callbacks_count': len(invoked_now)
                        })
            elif t == 'CALL_RCU':
                cb_id = op['cb_id']
                payload = op.get('payload')
                target = self.gp_number if self.gp_active else self.gp_number + 1
                self.pending_callbacks.append({
                    'cb_id': cb_id,
                    'payload': payload,
                    'registered_at_gp': self.gp_number,
                    'target_gp': target
                })
                self.total_cbs_registered += 1
                results.append({'op_index': idx, 'type': t, 'status': 'SUCCESS', 'cb_id': cb_id, 'target_gp': target})
            elif t == 'RCU_STALL_CHECK':
                if not self.gp_active:
                    results.append({'op_index': idx, 'type': t, 'status': 'NO_ACTIVE_GP'})
                else:
                    stalled = []
                    for l in range(self.num_leaves):
                        for b in range(self.fanout):
                            c = l * self.fanout + b
                            if c < self.nr_cpus and (self.leaf_qsmask[l] & (1 << b)):
                                stalled.append({
                                    'cpu': c,
                                    'leaf_index': l,
                                    'in_critical_section': self.cpu_nesting[c] > 0,
                                    'nesting': self.cpu_nesting[c]
                                })
                    results.append({
                        'op_index': idx,
                        'type': t,
                        'status': 'STALL_DETECTED' if stalled else 'NO_STALL',
                        'gp_number': self.gp_number,
                        'stalled_count': len(stalled),
                        'stalled_cpus': stalled
                    })
            elif t == 'QUERY_RCU_STATE':
                results.append({
                    'op_index': idx,
                    'type': t,
                    'gp_number': self.gp_number,
                    'gp_active': self.gp_active,
                    'pending_callbacks_count': len(self.pending_callbacks),
                    'invoked_callbacks_count': len(self.invoked_callbacks),
                    'leaf_masks': {str(l): self.leaf_qsmask[l] for l in range(self.num_leaves)},
                    'root_mask': self.root_qsmask,
                    'active_readers': [c for c, n in self.cpu_nesting.items() if n > 0]
                })

        summary = {
            'total_operations': len(ops),
            'total_gp_started': self.total_gp_started,
            'total_gp_completed': self.total_gp_completed,
            'total_callbacks_registered': self.total_cbs_registered,
            'total_callbacks_invoked': len(self.invoked_callbacks),
            'final_gp_number': self.gp_number,
            'final_gp_active': self.gp_active,
            'active_readers_count': len([c for c, n in self.cpu_nesting.items() if n > 0])
        }
        return {'operation_results': results, 'summary': summary}

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    engine = TreeRcuEngine(data.get('config', {}))
    res = engine.run(data['operations'])
    print(json.dumps(res, separators=(',', ':'), ensure_ascii=False))

if __name__ == '__main__':
    main()
