import sys
import json

# Redis Cluster CRC16 Table (Polynomial 0x1021, XMODEM)
POLY = 0x1021
CRC16_TABLE = []
for i in range(256):
    curr = i << 8
    for _ in range(8):
        if curr & 0x8000:
            curr = ((curr << 1) ^ POLY) & 0xFFFF
        else:
            curr = (curr << 1) & 0xFFFF
    CRC16_TABLE.append(curr)

def get_slot(key_str: str) -> int:
    s = key_str.find('{')
    if s != -1:
        e = key_str.find('}', s + 1)
        if e != -1 and e > s + 1:
            key_str = key_str[s + 1:e]
    
    crc = 0
    for b in key_str.encode('utf-8'):
        crc = ((crc << 8) & 0xFFFF) ^ CRC16_TABLE[((crc >> 8) ^ b) & 0xFF]
    return crc % 16384

class RedisClusterEngine:
    def __init__(self, data):
        c_conf = data.get("cluster_config", {})
        self.nodes = c_conf.get("nodes", {})
        self.node_ids = list(self.nodes.keys())
        self.endpoints = {nid: info["endpoint"] for nid, info in self.nodes.items()}
        self.endpoint_to_node = {info["endpoint"]: nid for nid, info in self.nodes.items()}

        self.slot_owners = {}
        for nid, info in self.nodes.items():
            for r in info.get("slots", []):
                for s in range(r[0], r[1] + 1):
                    self.slot_owners[s] = nid

        self.migrations = {}
        for m in c_conf.get("migrations", []):
            s = int(m["slot"])
            self.migrations[s] = {
                "source": m["source"],
                "target": m["target"]
            }

        self.storage = {nid: {} for nid in self.node_ids}
        for nid, kvs in c_conf.get("initial_storage", {}).items():
            if nid in self.storage:
                self.storage[nid].update(kvs)

        cl_conf = data.get("client_config", {})
        self.client_type = cl_conf.get("client_type", "SMART")
        self.max_redirects = int(cl_conf.get("max_redirects", 5))
        
        self.client_cache = {}
        if "initial_cache" in cl_conf:
            for s_str, nid in cl_conf["initial_cache"].items():
                self.client_cache[int(s_str)] = nid
        else:
            self.client_cache = dict(self.slot_owners)

        self.commands_input = data.get("commands", [])

    def run(self):
        results = []
        total_hops = 0
        total_moved = 0
        total_ask = 0
        success_count = 0
        fail_count = 0

        for item in self.commands_input:
            item_type = item.get("type", "CLIENT")
            if item_type == "ADMIN":
                action = item.get("action")
                if action == "MIGRATE_KEY":
                    k = item.get("key")
                    slot = get_slot(k)
                    if slot in self.migrations:
                        src = self.migrations[slot]["source"]
                        dst = self.migrations[slot]["target"]
                        if k in self.storage[src]:
                            val = self.storage[src].pop(k)
                            self.storage[dst][k] = val
                            results.append({"type": "ADMIN", "action": action, "key": k, "slot": slot, "status": "MIGRATED", "from": src, "to": dst})
                        else:
                            results.append({"type": "ADMIN", "action": action, "key": k, "slot": slot, "status": "KEY_NOT_FOUND_ON_SOURCE"})
                    else:
                        results.append({"type": "ADMIN", "action": action, "key": k, "slot": slot, "status": "SLOT_NOT_MIGRATING"})

                elif action == "FINALIZE_SLOT":
                    slot = int(item.get("slot"))
                    if slot in self.migrations:
                        target = self.migrations[slot]["target"]
                        self.slot_owners[slot] = target
                        del self.migrations[slot]
                        results.append({"type": "ADMIN", "action": action, "slot": slot, "status": "FINALIZED", "new_owner": target})
                    else:
                        results.append({"type": "ADMIN", "action": action, "slot": slot, "status": "SLOT_NOT_MIGRATING"})

                elif action == "START_MIGRATION":
                    slot = int(item.get("slot"))
                    src = item.get("source")
                    dst = item.get("target")
                    self.migrations[slot] = {"source": src, "target": dst}
                    results.append({"type": "ADMIN", "action": action, "slot": slot, "source": src, "target": dst, "status": "STARTED"})

            elif item_type == "CLIENT":
                cmd = item.get("cmd")
                key = item.get("key")
                val = item.get("val")
                slot = get_slot(key)

                hops = 0
                redirects = []
                asking_flag = False
                status = "UNKNOWN"
                res_val = None
                routed_node = None

                curr_node = self.client_cache.get(slot, self.node_ids[0])

                while hops < self.max_redirects:
                    hops += 1
                    total_hops += 1
                    has_asking = asking_flag
                    asking_flag = False

                    owner = self.slot_owners.get(slot)
                    is_migrating = (slot in self.migrations)

                    if curr_node == owner:
                        if is_migrating:
                            mig = self.migrations[slot]
                            dst = mig["target"]
                            key_exists = (key in self.storage[curr_node])
                            if not key_exists:
                                total_ask += 1
                                red_str = f"ASK {slot} {self.endpoints[dst]}"
                                redirects.append(red_str)
                                
                                if self.client_type == "SMART":
                                    asking_flag = True
                                    curr_node = dst
                                elif self.client_type == "NAIVE_NO_ASKING":
                                    self.client_cache[slot] = dst
                                    asking_flag = False
                                    curr_node = dst
                                elif self.client_type == "NAIVE_CACHE_MUTATE":
                                    self.client_cache[slot] = dst
                                    asking_flag = True
                                    curr_node = dst
                                continue
                            else:
                                res_val = self._execute_db(curr_node, cmd, key, val)
                                status = "SUCCESS"
                                routed_node = curr_node
                                break
                        else:
                            res_val = self._execute_db(curr_node, cmd, key, val)
                            status = "SUCCESS"
                            routed_node = curr_node
                            break

                    elif is_migrating and curr_node == self.migrations[slot]["target"]:
                        if has_asking:
                            res_val = self._execute_db(curr_node, cmd, key, val)
                            status = "SUCCESS"
                            routed_node = curr_node
                            break
                        else:
                            total_moved += 1
                            red_str = f"MOVED {slot} {self.endpoints[owner]}"
                            redirects.append(red_str)
                            self.client_cache[slot] = owner
                            curr_node = owner
                            asking_flag = False
                            continue

                    else:
                        total_moved += 1
                        red_str = f"MOVED {slot} {self.endpoints[owner]}"
                        redirects.append(red_str)
                        self.client_cache[slot] = owner
                        curr_node = owner
                        asking_flag = False
                        continue

                if hops >= self.max_redirects and status != "SUCCESS":
                    status = "TOO_MANY_REDIRECTS"
                    fail_count += 1
                else:
                    success_count += 1

                cmd_res = {
                    "type": "CLIENT",
                    "cmd": cmd,
                    "key": key,
                    "slot": slot,
                    "status": status,
                    "hops": hops,
                    "redirects": redirects
                }
                if status == "SUCCESS":
                    cmd_res["result"] = res_val
                    cmd_res["routed_node"] = routed_node
                else:
                    cmd_res["error"] = f"Exceeded max redirects ({self.max_redirects})"
                results.append(cmd_res)

        slots_touched = sorted(list(set(get_slot(item["key"]) for item in self.commands_input if item.get("type") == "CLIENT")))
        cache_snapshot = {str(s): self.client_cache.get(s) for s in slots_touched}

        return {
            "summary": {
                "total_client_commands": success_count + fail_count,
                "successful_commands": success_count,
                "failed_commands": fail_count,
                "total_hops": total_hops,
                "total_moved_redirects": total_moved,
                "total_ask_redirects": total_ask
            },
            "final_client_cache": cache_snapshot,
            "results": results
        }

    def _execute_db(self, node, cmd, key, val):
        if cmd == "GET":
            return self.storage[node].get(key)
        elif cmd == "SET":
            self.storage[node][key] = val
            return "OK"
        elif cmd == "DEL":
            ex = key in self.storage[node]
            if ex:
                del self.storage[node][key]
            return 1 if ex else 0
        elif cmd == "EXISTS":
            return 1 if key in self.storage[node] else 0
        return None

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    engine = RedisClusterEngine(data)
    result = engine.run()
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
