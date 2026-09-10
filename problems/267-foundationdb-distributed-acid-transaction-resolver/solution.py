import sys
import json

if sys.platform == 'win32':
    try:
        sys.stdin.reconfigure(encoding='utf-8')
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

class ShardedResolver:
    def __init__(self, resolver_id, start_key, end_key, max_history=100):
        self.resolver_id = resolver_id
        self.start_key = start_key
        self.end_key = end_key
        self.max_history = max_history
        self.key_history = {}

    def owns_key(self, key):
        if self.start_key is not None and key < self.start_key:
            return False
        if self.end_key is not None and key >= self.end_key:
            return False
        return True

    def check_conflicts(self, read_version, read_keys):
        conflicts = []
        for rk in read_keys:
            if self.owns_key(rk):
                history = self.key_history.get(rk, [])
                for cv in history:
                    if cv > read_version:
                        conflicts.append({
                            'key': rk,
                            'conflict_version': cv,
                            'resolver_id': self.resolver_id
                        })
                        break
        return conflicts

    def record_writes(self, commit_version, written_keys):
        for wk in written_keys:
            if self.owns_key(wk):
                if wk not in self.key_history:
                    self.key_history[wk] = []
                self.key_history[wk].append(commit_version)

    def prune(self, min_version):
        for k in list(self.key_history.keys()):
            self.key_history[k] = [v for v in self.key_history[k] if v >= min_version]

class FoundationDBEngine:
    def __init__(self, config):
        self.current_version = int(config.get('initial_version', 1000))
        self.max_history_versions = int(config.get('max_history_versions', 100))
        resolver_configs = config.get('resolvers', [
            {'id': 'resolver_0', 'start_key': None, 'end_key': 'm'},
            {'id': 'resolver_1', 'start_key': 'm', 'end_key': None}
        ])
        self.resolvers = [
            ShardedResolver(r['id'], r.get('start_key'), r.get('end_key'), self.max_history_versions)
            for r in resolver_configs
        ]
        init_kv_raw = config.get('initial_kv', {})
        self.kv_store = {}
        for k, v in init_kv_raw.items():
            if isinstance(v, dict) and 'val' in v:
                self.kv_store[k] = v
            else:
                self.kv_store[k] = {'val': v, 'version': self.current_version}

    def process_transaction(self, tx):
        tx_id = tx['tx_id']
        tx_type = tx.get('type', 'READ_WRITE')
        read_version = tx.get('read_version', self.current_version)
        read_keys = tx.get('read_keys', [])
        write_ops = tx.get('write_ops', {})

        min_allowed = self.current_version - self.max_history_versions
        if read_version < min_allowed:
            return {
                'tx_id': tx_id,
                'status': 'ABORTED',
                'error': 'transaction_too_old',
                'error_code': 1007,
                'read_version': read_version,
                'min_allowed_version': min_allowed,
                'current_version': self.current_version
            }

        if tx_type == 'READ_ONLY':
            read_values = {}
            for k in read_keys:
                if k in self.kv_store and self.kv_store[k]['version'] <= read_version:
                    read_values[k] = self.kv_store[k]['val']
                else:
                    read_values[k] = None
            return {
                'tx_id': tx_id,
                'status': 'COMMITTED',
                'type': 'READ_ONLY',
                'read_version': read_version,
                'read_values': read_values
            }

        all_conflicts = []
        for res in self.resolvers:
            c = res.check_conflicts(read_version, read_keys)
            all_conflicts.extend(c)

        if all_conflicts:
            return {
                'tx_id': tx_id,
                'status': 'ABORTED',
                'error': 'not_committed',
                'error_code': 1020,
                'conflict_reason': 'write_conflict',
                'conflicts': all_conflicts,
                'read_version': read_version
            }

        self.current_version += 1
        commit_version = self.current_version
        written_keys = list(write_ops.keys())

        for res in self.resolvers:
            res.record_writes(commit_version, written_keys)
            res.prune(self.current_version - self.max_history_versions)

        for k, v in write_ops.items():
            self.kv_store[k] = {'val': v, 'version': commit_version}

        return {
            'tx_id': tx_id,
            'status': 'COMMITTED',
            'type': 'READ_WRITE',
            'read_version': read_version,
            'commit_version': commit_version,
            'written_keys': written_keys
        }

def run_simulation(data):
    config = data.get('config', {})
    transactions = data.get('transactions', [])
    engine = FoundationDBEngine(config)

    results = []
    committed_count = 0
    aborted_count = 0

    for tx in transactions:
        res = engine.process_transaction(tx)
        if res['status'] == 'COMMITTED':
            committed_count += 1
        else:
            aborted_count += 1
        results.append(res)

    final_kv = {k: v['val'] for k, v in sorted(engine.kv_store.items())}

    return {
        'summary': {
            'initial_version': int(config.get('initial_version', 1000)),
            'final_version': engine.current_version,
            'total_transactions': len(transactions),
            'committed_count': committed_count,
            'aborted_count': aborted_count
        },
        'transactions': results,
        'final_kv_store': final_kv
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    res = run_simulation(data)
    print(json.dumps(res, ensure_ascii=False))

if __name__ == '__main__':
    main()
