import sys
import json
import copy

# Ensure UTF-8 I/O for Windows environments
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")

class NFTSetElement:
    def __init__(self, key, data=None, timeout_ms=None, created_ts=0):
        self.key = key
        self.data = data
        self.timeout_ms = timeout_ms
        self.expiration_ts = (created_ts + timeout_ms) if timeout_ms is not None else None
        self.packets = 0
        self.bytes = 0

    def is_expired(self, current_ts: int) -> bool:
        if self.expiration_ts is not None and current_ts >= self.expiration_ts:
            return True
        return False

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "data": self.data,
            "timeout_ms": self.timeout_ms,
            "expiration_ts": self.expiration_ts,
            "packets": self.packets,
            "bytes": self.bytes
        }

class NFTSet:
    def __init__(self, name: str, key_type: str, data_type: str = None, dynamic: bool = False, default_timeout_ms: int = None):
        self.name = name
        self.key_type = key_type
        self.data_type = data_type
        self.dynamic = dynamic
        self.default_timeout_ms = default_timeout_ms
        self.elements = {}

    def gc(self, current_ts: int):
        expired_keys = [k for k, elem in self.elements.items() if elem.is_expired(current_ts)]
        for k in expired_keys:
            del self.elements[k]

    def add(self, key, data=None, timeout_ms=None, current_ts=0):
        self.gc(current_ts)
        t_ms = timeout_ms if timeout_ms is not None else self.default_timeout_ms
        self.elements[key] = NFTSetElement(key, data, t_ms, current_ts)

    def delete(self, key):
        if key in self.elements:
            del self.elements[key]

    def lookup(self, key, current_ts=0):
        self.gc(current_ts)
        elem = self.elements.get(key)
        if elem and elem.is_expired(current_ts):
            del self.elements[key]
            return None
        return elem

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "key_type": self.key_type,
            "data_type": self.data_type,
            "dynamic": self.dynamic,
            "elements": {str(k): elem.to_dict() for k, elem in sorted(self.elements.items(), key=lambda x: str(x[0]))}
        }

class NFTVM:
    def __init__(self, raw_config: dict):
        table_config = copy.deepcopy(raw_config)
        self.name = table_config.get("name", "filter")
        self.sets = {}
        for s_cfg in table_config.get("sets", []):
            s = NFTSet(
                name=s_cfg["name"],
                key_type=s_cfg.get("key_type", "ipv4_addr"),
                data_type=s_cfg.get("data_type"),
                dynamic=s_cfg.get("dynamic", False),
                default_timeout_ms=s_cfg.get("default_timeout_ms")
            )
            for elem in s_cfg.get("elements", []):
                s.add(elem["key"], elem.get("data"), elem.get("timeout_ms"), current_ts=0)
            self.sets[s.name] = s

        self.chains = {}
        for c_cfg in table_config.get("chains", []):
            self.chains[c_cfg["name"]] = {
                "name": c_cfg["name"],
                "hook": c_cfg.get("hook"),
                "priority": c_cfg.get("priority", 0),
                "policy": c_cfg.get("policy", "ACCEPT"),
                "rules": c_cfg.get("rules", [])
            }

        self.stats = {
            "packets_processed": 0,
            "packets_accepted": 0,
            "packets_dropped": 0,
            "rules_evaluated": 0,
            "expressions_executed": 0
        }
        self.current_time_ms = 0
        self.packet_results = []
        self.snapshots = []

    def _extract_payload(self, pkt: dict, base: str, offset: int, length: int) -> int:
        if base == "NETWORK_HEADER":
            if offset == 12:
                return pkt.get("src_ip", 0)
            elif offset == 16:
                return pkt.get("dst_ip", 0)
            elif offset == 9:
                return pkt.get("proto", 0)
        elif base == "TRANSPORT_HEADER":
            if offset == 0:
                return pkt.get("src_port", 0)
            elif offset == 2:
                return pkt.get("dst_port", 0)
            elif offset == 13:
                return pkt.get("tcp_flags", 0)
        return 0

    def _eval_rule(self, rule: dict, pkt: dict, regs: dict, call_stack: list) -> str:
        self.stats["rules_evaluated"] += 1
        for expr in rule.get("expressions", []):
            self.stats["expressions_executed"] += 1
            op = expr["op"]
            
            if op == "PAYLOAD":
                dreg = expr["dest_reg"]
                val = self._extract_payload(pkt, expr["base"], expr["offset"], expr["length"])
                regs["data"][dreg] = val

            elif op == "IMMEDIATE":
                if "dest_reg" in expr:
                    regs["data"][expr["dest_reg"]] = expr["value"]
                elif "verdict" in expr:
                    regs["verdict"] = {"code": expr["verdict"].get("code", "NFT_CONTINUE"), "chain": expr["verdict"].get("chain")}

            elif op == "CMP":
                sreg = expr["sreg"]
                sval = regs["data"][sreg]
                target = expr["value"]
                cmp_op = expr["cmp_op"]
                matched = False
                if cmp_op == "EQ":
                    matched = (sval == target)
                elif cmp_op == "NEQ":
                    matched = (sval != target)
                elif cmp_op == "LT":
                    matched = (sval < target)
                elif cmp_op == "LTE":
                    matched = (sval <= target)
                elif cmp_op == "GT":
                    matched = (sval > target)
                elif cmp_op == "GTE":
                    matched = (sval >= target)
                
                if not matched:
                    regs["verdict"] = {"code": "NFT_BREAK", "chain": None}
                    return "NFT_BREAK"

            elif op == "RANGE":
                sreg = expr["sreg"]
                sval = regs["data"][sreg]
                if not (expr["min_val"] <= sval <= expr["max_val"]):
                    regs["verdict"] = {"code": "NFT_BREAK", "chain": None}
                    return "NFT_BREAK"

            elif op == "BITWISE":
                sreg = expr["sreg"]
                dreg = expr["dreg"]
                sval = regs["data"][sreg]
                mask = expr.get("mask", 0xFFFFFFFF)
                xor = expr.get("xor", 0)
                regs["data"][dreg] = (sval & mask) ^ xor

            elif op == "LOOKUP":
                set_obj = self.sets.get(expr["set_name"])
                if not set_obj:
                    regs["verdict"] = {"code": "NFT_BREAK", "chain": None}
                    return "NFT_BREAK"
                key = regs["data"][expr["sreg"]]
                elem = set_obj.lookup(key, self.current_time_ms)
                if not elem:
                    regs["verdict"] = {"code": "NFT_BREAK", "chain": None}
                    return "NFT_BREAK"
                
                if "dreg" in expr and elem.data is not None:
                    if isinstance(elem.data, dict) and "verdict" in elem.data:
                        regs["verdict"] = elem.data["verdict"]
                    else:
                        regs["data"][expr["dreg"]] = elem.data

            elif op == "DYNSET":
                set_obj = self.sets.get(expr["set_name"])
                if set_obj:
                    key = regs["data"][expr["sreg_key"]]
                    timeout_ms = expr.get("timeout_ms")
                    elem = set_obj.lookup(key, self.current_time_ms)
                    if not elem:
                        set_obj.add(key, None, timeout_ms, self.current_time_ms)
                        elem = set_obj.lookup(key, self.current_time_ms)
                    if elem:
                        elem.packets += 1
                        elem.bytes += pkt.get("length", 0)

            elif op == "COUNTER":
                if "stats" not in rule:
                    rule["stats"] = {"packets": 0, "bytes": 0}
                rule["stats"]["packets"] += 1
                rule["stats"]["bytes"] += pkt.get("length", 0)

            vcode = regs["verdict"]["code"]
            if vcode in ("NF_ACCEPT", "NF_DROP", "NFT_JUMP", "NFT_GOTO", "NFT_RETURN"):
                return vcode

        return "NFT_CONTINUE"

    def process_packet(self, pkt: dict, hook: str = "PREROUTING") -> str:
        self.stats["packets_processed"] += 1
        current_time_ms = pkt.get("timestamp_ms", self.current_time_ms)
        self.current_time_ms = current_time_ms

        for s in self.sets.values():
            s.gc(self.current_time_ms)

        matching_chains = [c for c in self.chains.values() if c.get("hook") == hook]
        matching_chains.sort(key=lambda c: c["priority"])

        if not matching_chains:
            self.stats["packets_accepted"] += 1
            verdict = "ACCEPT"
            self.packet_results.append({"packet_id": pkt.get("id"), "verdict": verdict, "timestamp_ms": current_time_ms})
            return verdict

        regs = {
            "verdict": {"code": "NFT_CONTINUE", "chain": None},
            "data": [0] * 16
        }

        call_stack = []
        cur_chain_name = matching_chains[0]["name"]
        rule_idx = 0

        while True:
            cur_chain = self.chains.get(cur_chain_name)
            if not cur_chain:
                break

            rules = cur_chain.get("rules", [])
            if rule_idx >= len(rules):
                if call_stack:
                    cur_chain_name, rule_idx = call_stack.pop()
                    continue
                else:
                    policy = cur_chain.get("policy", "ACCEPT")
                    if policy == "ACCEPT":
                        self.stats["packets_accepted"] += 1
                        verdict = "ACCEPT"
                    else:
                        self.stats["packets_dropped"] += 1
                        verdict = "DROP"
                    self.packet_results.append({"packet_id": pkt.get("id"), "verdict": verdict, "timestamp_ms": current_time_ms})
                    return verdict

            rule = rules[rule_idx]
            rule_idx += 1
            regs["verdict"] = {"code": "NFT_CONTINUE", "chain": None}
            vcode = self._eval_rule(rule, pkt, regs, call_stack)

            if vcode == "NFT_BREAK" or vcode == "NFT_CONTINUE":
                continue
            elif vcode == "NF_ACCEPT":
                self.stats["packets_accepted"] += 1
                verdict = "ACCEPT"
                self.packet_results.append({"packet_id": pkt.get("id"), "verdict": verdict, "timestamp_ms": current_time_ms})
                return verdict
            elif vcode == "NF_DROP":
                self.stats["packets_dropped"] += 1
                verdict = "DROP"
                self.packet_results.append({"packet_id": pkt.get("id"), "verdict": verdict, "timestamp_ms": current_time_ms})
                return verdict
            elif vcode == "NFT_JUMP":
                target_chain = regs["verdict"]["chain"]
                call_stack.append((cur_chain_name, rule_idx))
                cur_chain_name = target_chain
                rule_idx = 0
            elif vcode == "NFT_GOTO":
                target_chain = regs["verdict"]["chain"]
                cur_chain_name = target_chain
                rule_idx = 0
            elif vcode == "NFT_RETURN":
                if call_stack:
                    cur_chain_name, rule_idx = call_stack.pop()
                else:
                    policy = cur_chain.get("policy", "ACCEPT")
                    if policy == "ACCEPT":
                        self.stats["packets_accepted"] += 1
                        verdict = "ACCEPT"
                    else:
                        self.stats["packets_dropped"] += 1
                        verdict = "DROP"
                    self.packet_results.append({"packet_id": pkt.get("id"), "verdict": verdict, "timestamp_ms": current_time_ms})
                    return verdict

        self.stats["packets_accepted"] += 1
        verdict = "ACCEPT"
        self.packet_results.append({"packet_id": pkt.get("id"), "verdict": verdict, "timestamp_ms": current_time_ms})
        return verdict

    def run_commands(self, commands: list):
        for cmd in commands:
            ctype = cmd["type"]
            if ctype == "PACKET":
                self.process_packet(cmd["packet"], cmd.get("hook", "PREROUTING"))
            elif ctype == "SET_ADD":
                set_obj = self.sets.get(cmd["set_name"])
                if set_obj:
                    set_obj.add(cmd["key"], cmd.get("data"), cmd.get("timeout_ms"), self.current_time_ms)
            elif ctype == "SET_DEL":
                set_obj = self.sets.get(cmd["set_name"])
                if set_obj:
                    set_obj.delete(cmd["key"])
            elif ctype == "ADVANCE_TIME":
                self.current_time_ms += cmd["delta_ms"]
                for s in self.sets.values():
                    s.gc(self.current_time_ms)
            elif ctype == "QUERY_SNAPSHOT":
                self.snapshots.append({
                    "timestamp_ms": self.current_time_ms,
                    "stats": copy.deepcopy(self.stats),
                    "sets": {k: s.to_dict() for k, s in sorted(self.sets.items())}
                })

    def get_state(self) -> dict:
        return {
            "table": self.name,
            "stats": self.stats,
            "packet_results": self.packet_results,
            "sets": {k: s.to_dict() for k, s in sorted(self.sets.items())},
            "chains": {k: {
                "name": c["name"],
                "hook": c["hook"],
                "priority": c["priority"],
                "policy": c["policy"],
                "rules": c["rules"]
            } for k, c in sorted(self.chains.items())},
            "snapshots": self.snapshots
        }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    vm = NFTVM(data.get("config", {}))
    vm.run_commands(data.get("commands", []))
    print(json.dumps(vm.get_state(), separators=(",", ":"), ensure_ascii=False))

if __name__ == "__main__":
    main()
