import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class Inode:
    def __init__(self, ino, mode, is_dir=False, symlink_target=None):
        self.ino = ino
        self.mode = mode
        self.is_dir = is_dir
        self.symlink_target = symlink_target
        self.i_seq = 0

class Dentry:
    def __init__(self, name, parent=None, inode=None):
        self.name = name
        self.parent = parent if parent else self
        self.inode = inode
        self.d_seq = 0
        self.children = {}
        self.mounted_root = None

class VFSEngine:
    def __init__(self, config):
        self.max_nested_links = config.get("max_nested_links", 40)
        self.next_ino = 1
        self.root_inode = Inode(self.next_ino, 0o755, is_dir=True)
        self.next_ino += 1
        self.root_dentry = Dentry("/", None, self.root_inode)

    def _alloc_ino(self, is_dir=False, symlink_target=None):
        ino = self.next_ino
        self.next_ino += 1
        return Inode(ino, 0o755 if is_dir else 0o644, is_dir=is_dir, symlink_target=symlink_target)

    def _traverse_to_parent(self, path):
        parts = [p for p in path.split("/") if p]
        if not parts:
            return None, ""
        curr = self.root_dentry
        for comp in parts[:-1]:
            if curr.mounted_root:
                curr = curr.mounted_root
            if comp not in curr.children:
                return None, comp
            curr = curr.children[comp]
            if not curr.inode or not curr.inode.is_dir:
                return None, comp
        if curr.mounted_root:
            curr = curr.mounted_root
        return curr, parts[-1]

    def create(self, op):
        path = op["path"]
        is_dir = op.get("is_dir", False)
        symlink_target = op.get("symlink_target", None)

        parent_dent, filename = self._traverse_to_parent(path)
        if not parent_dent:
            return {"status": "PARENT_NOT_FOUND", "path": path}

        if filename in parent_dent.children and parent_dent.children[filename].inode is not None:
            return {"status": "ALREADY_EXISTS", "path": path}

        inode = self._alloc_ino(is_dir=is_dir, symlink_target=symlink_target)
        dentry = Dentry(filename, parent=parent_dent, inode=inode)
        parent_dent.children[filename] = dentry
        parent_dent.d_seq += 1
        return {
            "status": "CREATED",
            "path": path,
            "ino": inode.ino,
            "is_dir": is_dir,
            "symlink_target": symlink_target
        }

    def rename(self, op):
        old_path = op["old_path"]
        new_path = op["new_path"]
        old_parent, old_name = self._traverse_to_parent(old_path)
        if not old_parent or old_name not in old_parent.children:
            return {"status": "SOURCE_NOT_FOUND", "path": old_path}

        old_res = old_parent.children[old_name]
        new_parent, new_name = self._traverse_to_parent(new_path)
        if not new_parent:
            return {"status": "DEST_DIR_NOT_FOUND", "path": new_path}

        del old_parent.children[old_name]
        old_parent.d_seq += 1
        old_res.d_seq += 1

        old_res.name = new_name
        old_res.parent = new_parent
        new_parent.children[new_name] = old_res
        new_parent.d_seq += 1

        return {"status": "RENAMED", "old_path": old_path, "new_path": new_path}

    def mount(self, op):
        mount_path = op["path"]
        parent, name = self._traverse_to_parent(mount_path)
        if not parent or name not in parent.children:
            return {"status": "MOUNT_TARGET_INVALID", "path": mount_path}
        dent = parent.children[name]
        if not dent.inode or not dent.inode.is_dir:
            return {"status": "MOUNT_TARGET_INVALID", "path": mount_path}

        mnt_ino = self._alloc_ino(is_dir=True)
        mnt_root = Dentry("/", parent=dent.parent, inode=mnt_ino)
        dent.mounted_root = mnt_root
        dent.d_seq += 1
        return {"status": "MOUNTED", "path": mount_path, "mounted_ino": mnt_ino.ino}

    def lookup_path(self, op):
        path = op["path"]
        simulate_rcu_fail_at = op.get("simulate_rcu_fail_at", None)
        follow_symlinks = op.get("follow_symlinks", True)

        stats = {
            "rcu_steps": 0,
            "ref_steps": 0,
            "mount_crossings": 0,
            "symlinks_followed": 0,
            "fell_back_to_ref": False
        }

        mode = "RCU"
        symlink_stack = 0

        def resolve(p_str, curr_dent):
            nonlocal mode, symlink_stack
            comps = [c for c in p_str.split("/") if c]
            i = 0
            while i < len(comps):
                comp = comps[i]
                if comp == ".":
                    i += 1
                    continue
                elif comp == "..":
                    if curr_dent == self.root_dentry:
                        pass
                    else:
                        curr_dent = curr_dent.parent
                    i += 1
                    continue

                if curr_dent.mounted_root:
                    stats["mount_crossings"] += 1
                    mode = "REF"
                    stats["fell_back_to_ref"] = True
                    curr_dent = curr_dent.mounted_root

                if mode == "RCU":
                    if simulate_rcu_fail_at == comp:
                        mode = "REF"
                        stats["fell_back_to_ref"] = True
                        stats["ref_steps"] += 1
                    else:
                        stats["rcu_steps"] += 1
                else:
                    stats["ref_steps"] += 1

                if comp not in curr_dent.children:
                    return {"status": "NOT_FOUND", "failed_at": comp, "curr_path": curr_dent.name}

                next_dent = curr_dent.children[comp]
                inode = next_dent.inode

                if inode and inode.symlink_target is not None:
                    is_last = (i == len(comps) - 1)
                    if follow_symlinks or not is_last:
                        symlink_stack += 1
                        stats["symlinks_followed"] += 1
                        mode = "REF"
                        stats["fell_back_to_ref"] = True
                        if symlink_stack > self.max_nested_links:
                            return {"status": "ELOOP_SYMLINK_LOOP", "failed_at": comp}
                        target = inode.symlink_target
                        remaining = "/".join(comps[i+1:])
                        if target.startswith("/"):
                            new_path = target if not remaining else target.rstrip("/") + "/" + remaining
                            return resolve(new_path, self.root_dentry)
                        else:
                            new_path = target if not remaining else target.rstrip("/") + "/" + remaining
                            return resolve(new_path, curr_dent)

                curr_dent = next_dent
                i += 1

            if curr_dent.mounted_root:
                stats["mount_crossings"] += 1
                curr_dent = curr_dent.mounted_root

            return {
                "status": "FOUND",
                "ino": curr_dent.inode.ino if curr_dent.inode else None,
                "is_dir": curr_dent.inode.is_dir if curr_dent.inode else False,
                "dentry_name": curr_dent.name
            }

        res = resolve(path, self.root_dentry)
        res["stats"] = stats
        return res

def solve():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    engine = VFSEngine(data.get("config", {}))
    results = []
    for op in data.get("operations", []):
        name = op["op"]
        if name == "CREATE":
            results.append(engine.create(op))
        elif name == "RENAME":
            results.append(engine.rename(op))
        elif name == "MOUNT":
            results.append(engine.mount(op))
        elif name == "LOOKUP_PATH":
            results.append(engine.lookup_path(op))
        else:
            raise ValueError(f"Unknown op: {name}")

    print(json.dumps(results, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    solve()
