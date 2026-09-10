import sys
import json
from typing import Dict, List, Any, Optional

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

class BpfLruNode:
    def __init__(self, key: str, value: Any, cpu: int):
        self.key = key
        self.value = value
        self.cpu = cpu
        self.ref: bool = False

class BpfLruListEngine:
    """
    Simulation of Linux kernel's kernel/bpf/bpf_lru_list.c:
    - Global active list
    - Global inactive list
    - Per-CPU pending lists
    - Lockless read/lookup setting node->ref = True
    - Eviction algorithm from inactive list with active list demotion/rotation
    """
    def __init__(self, max_entries: int, num_cpus: int = 4):
        self.max_entries = max_entries
        self.num_cpus = num_cpus
        self.table: Dict[str, BpfLruNode] = {}
        
        self.active_list: List[str] = []
        self.inactive_list: List[str] = []
        self.per_cpu_pending: Dict[int, List[str]] = {c: [] for c in range(num_cpus)}
        self.evictions: List[str] = []

    def flush_pending(self, cpu: int):
        if cpu not in self.per_cpu_pending:
            return
        pending = self.per_cpu_pending[cpu]
        while pending:
            key = pending.pop(0)
            if key in self.table:
                self.inactive_list.insert(0, key)

    def flush_all_pending(self):
        for c in range(self.num_cpus):
            self.flush_pending(c)

    def balance_active_inactive(self):
        while len(self.active_list) > max(1, len(self.inactive_list)):
            tail_key = self.active_list.pop()
            self.inactive_list.insert(0, tail_key)

    def lookup(self, cpu: int, key: str) -> Dict[str, Any]:
        if key in self.table:
            node = self.table[key]
            node.ref = True
            return {"found": True, "value": node.value}
        return {"found": False, "value": None}

    def evict_one(self) -> Optional[str]:
        self.flush_all_pending()
        victim = None
        
        # Traverse inactive list from tail (LRU)
        while self.inactive_list:
            tail_key = self.inactive_list.pop()
            if tail_key not in self.table:
                continue
            node = self.table[tail_key]
            if node.ref:
                node.ref = False
                self.active_list.insert(0, tail_key)
                self.balance_active_inactive()
            else:
                victim = tail_key
                break
                
        if victim is None and self.active_list:
            self.balance_active_inactive()
            if self.inactive_list:
                victim = self.inactive_list.pop()
                if victim in self.table:
                    self.table[victim].ref = False

        if victim and victim in self.table:
            del self.table[victim]
            self.evictions.append(victim)
            return victim
        return None

    def update(self, cpu: int, key: str, value: Any) -> Dict[str, Any]:
        if key in self.table:
            node = self.table[key]
            node.value = value
            node.ref = True
            return {"status": "UPDATED", "key": key, "evicted": None}

        evicted = None
        if len(self.table) >= self.max_entries:
            evicted = self.evict_one()

        node = BpfLruNode(key, value, cpu)
        self.table[key] = node
        if cpu not in self.per_cpu_pending:
            self.per_cpu_pending[cpu] = []
        self.per_cpu_pending[cpu].append(key)
        self.flush_pending(cpu)
        
        return {"status": "INSERTED", "key": key, "evicted": evicted}

    def delete(self, cpu: int, key: str) -> Dict[str, Any]:
        if key in self.table:
            del self.table[key]
            if key in self.active_list:
                self.active_list.remove(key)
            if key in self.inactive_list:
                self.inactive_list.remove(key)
            for c in range(self.num_cpus):
                if key in self.per_cpu_pending[c]:
                    self.per_cpu_pending[c].remove(key)
            return {"deleted": True}
        return {"deleted": False}

    def get_summary(self) -> Dict[str, Any]:
        self.flush_all_pending()
        return {
            "total_entries": len(self.table),
            "active_list": list(self.active_list),
            "inactive_list": list(self.inactive_list),
            "evicted_keys": list(self.evictions),
            "table_keys": sorted(list(self.table.keys()))
        }

def process_trace(data: Dict[str, Any]) -> Dict[str, Any]:
    max_entries = data.get("max_entries", 4)
    num_cpus = data.get("num_cpus", 2)
    commands = data.get("commands", [])
    
    engine = BpfLruListEngine(max_entries=max_entries, num_cpus=num_cpus)
    command_results = []
    
    for cmd in commands:
        op = cmd.get("op")
        cpu = cmd.get("cpu", 0)
        key = cmd.get("key")
        val = cmd.get("value")
        
        if op == "LOOKUP":
            res = engine.lookup(cpu, key)
            command_results.append({"op": "LOOKUP", "key": key, "result": res})
        elif op == "UPDATE":
            res = engine.update(cpu, key, val)
            command_results.append({"op": "UPDATE", "key": key, "result": res})
        elif op == "DELETE":
            res = engine.delete(cpu, key)
            command_results.append({"op": "DELETE", "key": key, "result": res})
            
    summary = engine.get_summary()
    return {
        "command_results": command_results,
        "final_state": summary
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    result = process_trace(data)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
