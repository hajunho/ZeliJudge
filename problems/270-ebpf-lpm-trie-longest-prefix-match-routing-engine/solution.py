import sys
import json
import zlib

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

def ip_to_int(ip_str):
    octets = [int(x) for x in ip_str.strip().split(".")]
    return (octets[0] << 24) | (octets[1] << 16) | (octets[2] << 8) | octets[3]

def parse_cidr(cidr_str):
    parts = cidr_str.strip().split("/")
    ip_int = ip_to_int(parts[0])
    prefixlen = int(parts[1]) if len(parts) > 1 else 32
    mask = ((0xffffffff << (32 - prefixlen)) & 0xffffffff) if prefixlen > 0 else 0
    network = ip_int & mask
    return network, prefixlen

class LPMTrieNode:
    def __init__(self):
        self.children = [None, None]
        self.is_leaf = False
        self.route_data = None
        self.cidr_str = None
        self.prefixlen = 0

class LPMTrie:
    def __init__(self, max_entries=1000):
        self.root = LPMTrieNode()
        self.max_entries = max_entries
        self.total_routes = 0

    def insert(self, cidr_str, route_info):
        network, prefixlen = parse_cidr(cidr_str)
        curr = self.root
        for i in range(prefixlen):
            bit = (network >> (31 - i)) & 1
            if not curr.children[bit]:
                curr.children[bit] = LPMTrieNode()
            curr = curr.children[bit]

        is_new = not curr.is_leaf
        if is_new and self.total_routes >= self.max_entries:
            return False, "MAP_FULL"

        if is_new:
            self.total_routes += 1

        curr.is_leaf = True
        curr.route_data = dict(route_info)
        curr.cidr_str = cidr_str
        curr.prefixlen = prefixlen
        return True, "SUCCESS"

    def delete(self, cidr_str):
        network, prefixlen = parse_cidr(cidr_str)
        stack = []
        curr = self.root
        for i in range(prefixlen):
            bit = (network >> (31 - i)) & 1
            if not curr.children[bit]:
                return False, "NOT_FOUND"
            stack.append((curr, bit))
            curr = curr.children[bit]

        if not curr.is_leaf:
            return False, "NOT_FOUND"

        curr.is_leaf = False
        curr.route_data = None
        curr.cidr_str = None
        self.total_routes -= 1

        while stack:
            parent, bit = stack.pop()
            child = parent.children[bit]
            if not child.is_leaf and not child.children[0] and not child.children[1]:
                parent.children[bit] = None
            else:
                break

        return True, "DELETED"

    def lookup(self, ip_str):
        ip_int = ip_to_int(ip_str)
        best_match = None
        curr = self.root

        if curr.is_leaf:
            best_match = curr

        for i in range(32):
            bit = (ip_int >> (31 - i)) & 1
            if not curr.children[bit]:
                break
            curr = curr.children[bit]
            if curr.is_leaf:
                best_match = curr

        if best_match:
            return best_match.cidr_str, best_match.route_data
        return None, None

    def get_stats(self):
        node_count = 0
        max_d = 0

        def dfs(node, depth):
            nonlocal node_count, max_d
            if not node:
                return
            node_count += 1
            if depth > max_d:
                max_d = depth
            dfs(node.children[0], depth + 1)
            dfs(node.children[1], depth + 1)

        dfs(self.root, 0)
        return {
            "total_routes": self.total_routes,
            "trie_node_count": node_count,
            "max_depth": max_d
        }

def solve(data):
    config = data.get("config", {})
    max_entries = config.get("max_entries", 1000)
    enable_ecmp = config.get("enable_ecmp", True)

    trie = LPMTrie(max_entries=max_entries)

    for r in data.get("routes", []):
        trie.insert(r["cidr"], r)

    command_results = []

    for cmd in data.get("commands", []):
        op = cmd.get("op")
        if op == "ROUTE_PACKET":
            pkt = cmd["packet"]
            p_id = pkt["id"]
            src_ip = pkt.get("src_ip", "0.0.0.0")
            dst_ip = pkt["dst_ip"]
            src_port = pkt.get("src_port", 0)
            dst_port = pkt.get("dst_port", 0)
            proto = pkt.get("protocol", "TCP")

            cidr, r_data = trie.lookup(dst_ip)
            if not r_data:
                command_results.append({
                    "op": "ROUTE_PACKET",
                    "packet_id": p_id,
                    "status": "NO_ROUTE_TO_HOST",
                    "matched_cidr": None,
                    "action": "DROP"
                })
            else:
                action = r_data.get("action", "FORWARD")
                if action == "DROP":
                    command_results.append({
                        "op": "ROUTE_PACKET",
                        "packet_id": p_id,
                        "status": "DROPPED_BY_POLICY",
                        "matched_cidr": cidr,
                        "action": "DROP"
                    })
                else:
                    next_hops = r_data.get("next_hops", [])
                    if not next_hops:
                        command_results.append({
                            "op": "ROUTE_PACKET",
                            "packet_id": p_id,
                            "status": "NO_NEXT_HOP",
                            "matched_cidr": cidr,
                            "action": "DROP"
                        })
                        continue

                    if enable_ecmp and len(next_hops) > 1:
                        hash_str = f"{src_ip}:{dst_ip}:{src_port}:{dst_port}:{proto}"
                        h_val = zlib.crc32(hash_str.encode("utf-8")) & 0xffffffff
                        hop_idx = h_val % len(next_hops)
                        chosen_hop = next_hops[hop_idx]
                    else:
                        chosen_hop = next_hops[0]

                    command_results.append({
                        "op": "ROUTE_PACKET",
                        "packet_id": p_id,
                        "status": "FORWARDED",
                        "matched_cidr": cidr,
                        "action": "FORWARD",
                        "egress_interface": chosen_hop.get("interface"),
                        "gateway": chosen_hop.get("gateway"),
                        "metric": r_data.get("metric", 0)
                    })

        elif op == "INSERT_ROUTE":
            r = cmd["route"]
            ok, status = trie.insert(r["cidr"], r)
            command_results.append({
                "op": "INSERT_ROUTE",
                "cidr": r["cidr"],
                "status": status
            })

        elif op == "DELETE_ROUTE":
            cidr = cmd["cidr"]
            ok, status = trie.delete(cidr)
            command_results.append({
                "op": "DELETE_ROUTE",
                "cidr": cidr,
                "status": status
            })

        elif op == "GET_TRIE_STATS":
            stats = trie.get_stats()
            command_results.append({
                "op": "GET_TRIE_STATS",
                "stats": stats
            })

    return {
        "summary": {
            "total_commands_executed": len(command_results),
            "final_trie_stats": trie.get_stats()
        },
        "command_results": command_results
    }

def main():
    try:
        raw_data = sys.stdin.read().strip()
        if not raw_data:
            return
        data = json.loads(raw_data)
        res = solve(data)
        print(json.dumps(res, ensure_ascii=False))
    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
