import sys
import json

def ip_to_int(ip_str):
    parts = [int(p) for p in ip_str.split(".")]
    return (parts[0] << 24) | (parts[1] << 16) | (parts[2] << 8) | parts[3]

def int_to_ip(val):
    return f"{(val >> 24) & 0xFF}.{(val >> 16) & 0xFF}.{(val >> 8) & 0xFF}.{val & 0xFF}"

def get_bit(val, bit_idx, total_bits=32):
    shift = total_bits - 1 - bit_idx
    return (val >> shift) & 1

def mask_ip(ip_val, prefixlen, total_bits=32):
    if prefixlen == 0:
        return 0
    mask = ((1 << prefixlen) - 1) << (total_bits - prefixlen)
    return ip_val & mask

class LpmTrieNode:
    def __init__(self, prefixlen, ip_val, value=None, is_value_node=True):
        self.prefixlen = prefixlen
        self.ip_val = mask_ip(ip_val, prefixlen)
        self.value = value
        self.is_value_node = is_value_node
        self.child = [None, None]

class BpfLpmTrie:
    def __init__(self, config):
        self.max_entries = config.get("max_entries", 1024)
        self.root = None
        self.lookup_hits = 0
        self.lookup_misses = 0

    def insert(self, ip_str, prefixlen, value):
        ip_val = mask_ip(ip_to_int(ip_str), prefixlen)
        norm_ip = int_to_ip(ip_val)

        if self.root is None:
            self.root = LpmTrieNode(prefixlen, ip_val, value, is_value_node=True)
            return {"status": "INSERTED", "prefixlen": prefixlen, "key": norm_ip}

        node = self.root
        parent = None
        parent_dir = 0

        while True:
            xor_diff = node.ip_val ^ ip_val
            common_bits = 0
            while common_bits < min(node.prefixlen, prefixlen):
                if get_bit(xor_diff, common_bits) != 0:
                    break
                common_bits += 1

            if common_bits < node.prefixlen:
                branch = LpmTrieNode(common_bits, ip_val, None, is_value_node=False)
                old_dir = get_bit(node.ip_val, common_bits)
                branch.child[old_dir] = node
                
                if parent is None:
                    self.root = branch
                else:
                    parent.child[parent_dir] = branch
                
                if common_bits == prefixlen:
                    branch.is_value_node = True
                    branch.value = value
                    return {"status": "INSERTED", "prefixlen": prefixlen, "key": norm_ip}
                else:
                    new_node = LpmTrieNode(prefixlen, ip_val, value, is_value_node=True)
                    new_dir = get_bit(ip_val, common_bits)
                    branch.child[new_dir] = new_node
                    return {"status": "INSERTED", "prefixlen": prefixlen, "key": norm_ip}

            if node.prefixlen == prefixlen:
                node.is_value_node = True
                node.value = value
                return {"status": "INSERTED", "prefixlen": prefixlen, "key": norm_ip}

            branch_dir = get_bit(ip_val, node.prefixlen)
            if node.child[branch_dir] is None:
                new_node = LpmTrieNode(prefixlen, ip_val, value, is_value_node=True)
                node.child[branch_dir] = new_node
                return {"status": "INSERTED", "prefixlen": prefixlen, "key": norm_ip}

            parent = node
            parent_dir = branch_dir
            node = node.child[branch_dir]

    def lookup(self, ip_str):
        ip_val = ip_to_int(ip_str)
        node = self.root
        best_match = None

        while node is not None:
            node_masked = mask_ip(ip_val, node.prefixlen)
            if node_masked != node.ip_val:
                break

            if node.is_value_node:
                best_match = node

            if node.prefixlen >= 32:
                break

            next_dir = get_bit(ip_val, node.prefixlen)
            node = node.child[next_dir]

        if best_match is not None:
            self.lookup_hits += 1
            return {
                "status": "MATCH",
                "matched_prefixlen": best_match.prefixlen,
                "matched_key": int_to_ip(best_match.ip_val),
                "value": best_match.value
            }
        else:
            self.lookup_misses += 1
            return {"status": "NO_MATCH", "query_ip": ip_str}

    def delete(self, ip_str, prefixlen):
        ip_val = mask_ip(ip_to_int(ip_str), prefixlen)
        norm_ip = int_to_ip(ip_val)

        def _delete(node, parent, parent_dir):
            if node is None:
                return False

            node_masked = mask_ip(ip_val, node.prefixlen)
            if node_masked != node.ip_val:
                return False

            if node.prefixlen == prefixlen:
                if not node.is_value_node:
                    return False
                
                node.is_value_node = False
                node.value = None
                self._maybe_collapse(node, parent, parent_dir)
                return True

            next_dir = get_bit(ip_val, node.prefixlen)
            res = _delete(node.child[next_dir], node, next_dir)
            if res:
                self._maybe_collapse(node, parent, parent_dir)
            return res

        deleted = _delete(self.root, None, 0)
        if deleted:
            return {"status": "DELETED", "prefixlen": prefixlen, "key": norm_ip}
        return {"status": "NOT_FOUND", "prefixlen": prefixlen, "key": norm_ip}

    def _maybe_collapse(self, node, parent, parent_dir):
        if not node.is_value_node:
            if node.child[0] is None and node.child[1] is None:
                if parent is None:
                    self.root = None
                else:
                    parent.child[parent_dir] = None
            elif node.child[0] is None or node.child[1] is None:
                single_child = node.child[0] if node.child[0] is not None else node.child[1]
                if parent is None:
                    self.root = single_child
                else:
                    parent.child[parent_dir] = single_child

    def _count_nodes(self, node):
        if node is None:
            return 0, 0, 0
        v_cnt = 1 if node.is_value_node else 0
        i_cnt = 1 if not node.is_value_node else 0
        l_v, l_i, l_d = self._count_nodes(node.child[0])
        r_v, r_i, r_d = self._count_nodes(node.child[1])
        depth = 1 + max(l_d, r_d)
        return v_cnt + l_v + r_v, i_cnt + l_i + r_i, depth

    def query_stats(self):
        v_cnt, i_cnt, depth = self._count_nodes(self.root)
        return {
            "total_nodes": v_cnt,
            "intermediate_nodes": i_cnt,
            "tree_depth": depth,
            "lookup_hits": self.lookup_hits,
            "lookup_misses": self.lookup_misses
        }

def solve():
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    raw = sys.stdin.read().strip()
    if not raw:
        return

    input_data = json.loads(raw)
    config = input_data.get("config", {})
    trie = BpfLpmTrie(config)
    results = []

    for op in input_data.get("operations", []):
        cmd = op.get("op")
        if cmd == "INSERT":
            res = trie.insert(op["ip"], op["prefixlen"], op.get("value", {}))
            results.append(res)
        elif cmd == "LOOKUP":
            res = trie.lookup(op["ip"])
            results.append(res)
        elif cmd == "DELETE":
            res = trie.delete(op["ip"], op["prefixlen"])
            results.append(res)
        elif cmd == "QUERY_STATS":
            res = trie.query_stats()
            results.append(res)

    out_obj = {"results": results}
    print(json.dumps(out_obj, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    solve()
