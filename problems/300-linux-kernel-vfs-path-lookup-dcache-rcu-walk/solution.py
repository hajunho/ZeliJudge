# -*- coding: utf-8 -*-
import sys
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

class VFSNode:
    def __init__(self, name, inode_id, is_dir=False, is_symlink=False, symlink_target=None, parent=None):
        self.name = name
        self.inode_id = inode_id
        self.is_dir = is_dir
        self.is_symlink = is_symlink
        self.symlink_target = symlink_target
        self.parent = parent
        self.seq = 2
        self.children = {}

def normalize_path(path):
    parts = []
    for p in path.split("/"):
        if not p or p == ".":
            continue
        elif p == "..":
            if parts:
                parts.pop()
        else:
            parts.append(p)
    return "/" + "/".join(parts)

class VFSPathLookupEngine:
    def __init__(self, config=None):
        config = config or {}
        self.max_symlinks = config.get("max_symlinks", 40)
        self.dcache = {}
        self.root = VFSNode("", inode_id=1, is_dir=True)
        self.root.parent = self.root
        self.next_inode = 2

        self.stats = {
            "total_lookups": 0,
            "rcu_walk_successes": 0,
            "unlazy_walk_fallbacks": 0,
            "dcache_hits": 0,
            "dcache_misses": 0,
            "negative_dentry_hits": 0,
            "symlinks_resolved": 0,
            "eloop_errors": 0
        }
        self.history = []

    def add_path(self, path, is_dir=True, is_symlink=False, symlink_target=None):
        clean = normalize_path(path)
        parts = [p for p in clean.split("/") if p]
        curr = self.root
        for idx, part in enumerate(parts):
            is_last = (idx == len(parts) - 1)
            if part not in curr.children:
                node = VFSNode(
                    part,
                    inode_id=self.next_inode,
                    is_dir=(is_dir if is_last else True),
                    is_symlink=(is_symlink if is_last else False),
                    symlink_target=(symlink_target if is_last else None),
                    parent=curr
                )
                self.next_inode += 1
                curr.children[part] = node
                self.dcache[(curr.inode_id, part)] = (node, node.seq)
            curr = curr.children[part]

    def modify_node(self, path):
        clean = normalize_path(path)
        parts = [p for p in clean.split("/") if p]
        curr = self.root
        for part in parts:
            if part in curr.children:
                curr = curr.children[part]
        curr.seq += 2

    def lookup(self, path):
        self.stats["total_lookups"] += 1
        symlink_count = 0
        current_path = path

        while True:
            raw_parts = [p for p in current_path.split("/") if p]
            curr_node = self.root
            mode = "RCU_WALK"
            path_resolved = True

            for idx, comp in enumerate(raw_parts):
                if comp == ".":
                    continue
                if comp == "..":
                    curr_node = curr_node.parent
                    continue

                parent_inode = curr_node.inode_id
                cached = self.dcache.get((parent_inode, comp))

                if mode == "RCU_WALK":
                    if cached is None:
                        self.stats["unlazy_walk_fallbacks"] += 1
                        self.stats["dcache_misses"] += 1
                        mode = "REF_WALK"
                        if comp in curr_node.children:
                            child = curr_node.children[comp]
                            self.dcache[(parent_inode, comp)] = (child, child.seq)
                            curr_node = child
                        else:
                            self.dcache[(parent_inode, comp)] = (None, 0)
                            res = {"path": path, "status": "ENOENT", "mode_completed": mode}
                            self.history.append(res)
                            return res
                    else:
                        child, cached_seq = cached
                        if child is None:
                            self.stats["negative_dentry_hits"] += 1
                            res = {"path": path, "status": "ENOENT", "mode_completed": mode}
                            self.history.append(res)
                            return res

                        if child.seq != cached_seq or (child.seq % 2 != 0):
                            self.stats["unlazy_walk_fallbacks"] += 1
                            mode = "REF_WALK"
                            self.dcache[(parent_inode, comp)] = (child, child.seq)
                            curr_node = child
                        else:
                            self.stats["dcache_hits"] += 1
                            curr_node = child

                else:
                    if comp in curr_node.children:
                        child = curr_node.children[comp]
                        curr_node = child
                    else:
                        res = {"path": path, "status": "ENOENT", "mode_completed": mode}
                        self.history.append(res)
                        return res

                if curr_node.is_symlink:
                    symlink_count += 1
                    self.stats["symlinks_resolved"] += 1
                    if symlink_count > self.max_symlinks:
                        self.stats["eloop_errors"] += 1
                        res = {"path": path, "status": "ELOOP", "mode_completed": mode}
                        self.history.append(res)
                        return res

                    if mode == "RCU_WALK":
                        self.stats["unlazy_walk_fallbacks"] += 1
                        mode = "REF_WALK"

                    target = curr_node.symlink_target
                    remaining = raw_parts[idx + 1:]
                    if target.startswith("/"):
                        current_path = target + ("/" + "/".join(remaining) if remaining else "")
                    else:
                        prefix_parts = raw_parts[:idx]
                        parent_dir = "/" + "/".join(prefix_parts)
                        current_path = parent_dir + "/" + target + ("/" + "/".join(remaining) if remaining else "")
                    path_resolved = False
                    break

            if path_resolved:
                if mode == "RCU_WALK":
                    self.stats["rcu_walk_successes"] += 1
                res = {
                    "path": path,
                    "inode_id": curr_node.inode_id,
                    "is_dir": curr_node.is_dir,
                    "mode_completed": mode,
                    "status": "SUCCESS"
                }
                self.history.append(res)
                return res

    def execute_operations(self, operations):
        for op in operations:
            otype = op.get("type")
            if otype == "ADD_PATH":
                self.add_path(
                    op.get("path"),
                    is_dir=op.get("is_dir", True),
                    is_symlink=op.get("is_symlink", False),
                    symlink_target=op.get("symlink_target")
                )
            elif otype == "MODIFY_NODE":
                self.modify_node(op.get("path"))
            elif otype == "LOOKUP":
                self.lookup(op.get("path"))

        return {
            "history": self.history,
            "stats": self.stats
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    operations = data.get("operations", [])
    engine = VFSPathLookupEngine(config)
    result = engine.execute_operations(operations)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
