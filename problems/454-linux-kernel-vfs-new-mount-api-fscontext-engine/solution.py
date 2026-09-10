import sys
import json

SUPPORTED_FS = {
    "ext4": {
        "is_pseudo": False,
        "valid_keys": {
            "source": str,
            "ro": bool,
            "errors": ["continue", "remount-ro", "panic"],
            "data": ["journal", "ordered", "writeback"],
            "commit": int
        }
    },
    "xfs": {
        "is_pseudo": False,
        "valid_keys": {
            "source": str,
            "ro": bool,
            "logbufs": int,
            "allocsize": int
        }
    },
    "tmpfs": {
        "is_pseudo": True,
        "valid_keys": {
            "size": str,
            "nr_blocks": int,
            "nr_inodes": int,
            "mode": int
        }
    }
}

class VfsMountEngine:
    def __init__(self):
        self.contexts = {}
        self.detached_mounts = {}
        self.mount_table = {}
        self.next_sb_id = 1
        self.stats = {
            "contexts_created": 0,
            "superblocks_created": 0,
            "mounts_attached": 0,
            "param_errors": 0
        }

    def fsopen(self, fs_name, fs_fd):
        if fs_name not in SUPPORTED_FS:
            return {"status": "ENODEV_UNKNOWN_FS", "fs_name": fs_name}
        if fs_fd in self.contexts:
            return {"status": "EBADF_DUPLICATE_FD", "fs_fd": fs_fd}
        
        self.contexts[fs_fd] = {
            "fs_name": fs_name,
            "state": "FS_CONTEXT_CREATED",
            "params": {},
            "sb_id": None
        }
        self.stats["contexts_created"] += 1
        return {"status": "FS_CONTEXT_CREATED", "fs_fd": fs_fd, "fs_name": fs_name}

    def fsconfig_set(self, fs_fd, key, val):
        if fs_fd not in self.contexts:
            return {"status": "EBADF_UNKNOWN_FD", "fs_fd": fs_fd}
        
        ctx = self.contexts[fs_fd]
        if ctx["state"] not in ["FS_CONTEXT_CREATED", "FS_CONTEXT_FOR_RECONFIGURE"]:
            return {"status": "EBUSY_INVALID_STATE", "state": ctx["state"]}
        
        fs_spec = SUPPORTED_FS[ctx["fs_name"]]
        if key not in fs_spec["valid_keys"]:
            self.stats["param_errors"] += 1
            return {"status": "EINVAL_PARAM_KEY", "fs_name": ctx["fs_name"], "key": key}
        
        spec_type = fs_spec["valid_keys"][key]
        if isinstance(spec_type, list):
            if val not in spec_type:
                self.stats["param_errors"] += 1
                return {"status": "EINVAL_PARAM_VALUE", "key": key, "val": val, "allowed": spec_type}
        
        ctx["params"][key] = val
        return {"status": "PARAM_SET", "fs_fd": fs_fd, "key": key, "val": val}

    def fsconfig_create_tree(self, fs_fd):
        if fs_fd not in self.contexts:
            return {"status": "EBADF_UNKNOWN_FD", "fs_fd": fs_fd}
        
        ctx = self.contexts[fs_fd]
        if ctx["state"] != "FS_CONTEXT_CREATED":
            return {"status": "EBUSY_INVALID_STATE", "state": ctx["state"]}
        
        fs_spec = SUPPORTED_FS[ctx["fs_name"]]
        if not fs_spec["is_pseudo"] and "source" not in ctx["params"]:
            return {"status": "EINVAL_MISSING_SOURCE", "fs_name": ctx["fs_name"]}
        
        sb_id = self.next_sb_id
        self.next_sb_id += 1
        ctx["sb_id"] = sb_id
        ctx["state"] = "FS_CONTEXT_AWAITING_MOUNT"
        self.stats["superblocks_created"] += 1

        return {
            "status": "SUPERBLOCK_CREATED",
            "fs_fd": fs_fd,
            "sb_id": sb_id,
            "fs_name": ctx["fs_name"]
        }

    def fsmount(self, fs_fd, mnt_fd, mount_attrs=None):
        if fs_fd not in self.contexts:
            return {"status": "EBADF_UNKNOWN_FD", "fs_fd": fs_fd}
        if mnt_fd in self.detached_mounts:
            return {"status": "EBADF_DUPLICATE_MNT_FD", "mnt_fd": mnt_fd}
        
        ctx = self.contexts[fs_fd]
        if ctx["state"] != "FS_CONTEXT_AWAITING_MOUNT":
            return {"status": "EINVAL_NOT_AWAITING_MOUNT", "state": ctx["state"]}
        
        if mount_attrs is None:
            mount_attrs = {"ro": False, "nodev": False, "nosuid": False}

        self.detached_mounts[mnt_fd] = {
            "mnt_fd": mnt_fd,
            "fs_name": ctx["fs_name"],
            "sb_id": ctx["sb_id"],
            "params": dict(ctx["params"]),
            "attrs": mount_attrs
        }
        
        del self.contexts[fs_fd]
        return {"status": "MOUNT_DETACHED_CREATED", "mnt_fd": mnt_fd, "sb_id": self.detached_mounts[mnt_fd]["sb_id"]}

    def move_mount(self, mnt_fd, target_path):
        if mnt_fd not in self.detached_mounts:
            return {"status": "EBADF_UNKNOWN_MNT_FD", "mnt_fd": mnt_fd}
        
        mnt = self.detached_mounts.pop(mnt_fd)
        is_over = target_path in self.mount_table
        self.mount_table[target_path] = mnt
        self.stats["mounts_attached"] += 1

        return {
            "status": "MOUNT_ATTACHED",
            "target_path": target_path,
            "sb_id": mnt["sb_id"],
            "fs_name": mnt["fs_name"],
            "is_over_existing": is_over
        }

    def fspick_reconfigure(self, target_path, reconfig_fs_fd):
        if target_path not in self.mount_table:
            return {"status": "ENOENT_TARGET_NOT_MOUNTED", "target_path": target_path}
        if reconfig_fs_fd in self.contexts:
            return {"status": "EBADF_DUPLICATE_FD", "fs_fd": reconfig_fs_fd}
        
        mnt = self.mount_table[target_path]
        self.contexts[reconfig_fs_fd] = {
            "fs_name": mnt["fs_name"],
            "state": "FS_CONTEXT_FOR_RECONFIGURE",
            "params": dict(mnt["params"]),
            "sb_id": mnt["sb_id"],
            "target_path": target_path
        }
        return {
            "status": "RECONFIG_CONTEXT_CREATED",
            "fs_fd": reconfig_fs_fd,
            "target_path": target_path,
            "sb_id": mnt["sb_id"]
        }

    def fsconfig_apply_reconfigure(self, reconfig_fs_fd):
        if reconfig_fs_fd not in self.contexts:
            return {"status": "EBADF_UNKNOWN_FD", "fs_fd": reconfig_fs_fd}
        ctx = self.contexts[reconfig_fs_fd]
        if ctx["state"] != "FS_CONTEXT_FOR_RECONFIGURE":
            return {"status": "EINVAL_NOT_RECONFIG", "state": ctx["state"]}
        
        target_path = ctx["target_path"]
        if target_path in self.mount_table:
            self.mount_table[target_path]["params"].update(ctx["params"])
        
        del self.contexts[reconfig_fs_fd]
        return {"status": "RECONFIG_APPLIED", "target_path": target_path}

    def query_vfs_state(self):
        mounts_summary = {}
        for p in sorted(self.mount_table.keys()):
            m = self.mount_table[p]
            mounts_summary[p] = {
                "fs_name": m["fs_name"],
                "sb_id": m["sb_id"],
                "params": m["params"],
                "attrs": m["attrs"]
            }
        return {
            "active_contexts": len(self.contexts),
            "detached_mounts_count": len(self.detached_mounts),
            "attached_mounts": mounts_summary,
            "stats": self.stats
        }

def main():
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    
    raw = sys.stdin.read()
    if not raw.strip():
        return
    input_data = json.loads(raw)

    engine = VfsMountEngine()
    results = []

    for op in input_data.get("operations", []):
        cmd = op.get("op")
        if cmd == "FSOPEN":
            res = engine.fsopen(op["fs_name"], op["fs_fd"])
            results.append(res)
        elif cmd == "FSCONFIG_SET":
            res = engine.fsconfig_set(op["fs_fd"], op["key"], op["val"])
            results.append(res)
        elif cmd == "FSCONFIG_CREATE_TREE":
            res = engine.fsconfig_create_tree(op["fs_fd"])
            results.append(res)
        elif cmd == "FSMOUNT":
            res = engine.fsmount(op["fs_fd"], op["mnt_fd"], op.get("attrs"))
            results.append(res)
        elif cmd == "MOVE_MOUNT":
            res = engine.move_mount(op["mnt_fd"], op["target_path"])
            results.append(res)
        elif cmd == "FSPICK_RECONFIGURE":
            res = engine.fspick_reconfigure(op["target_path"], op["reconfig_fs_fd"])
            results.append(res)
        elif cmd == "FSCONFIG_APPLY_RECONFIGURE":
            res = engine.fsconfig_apply_reconfigure(op["reconfig_fs_fd"])
            results.append(res)
        elif cmd == "QUERY_VFS_STATE":
            res = engine.query_vfs_state()
            results.append(res)

    out = {"results": results}
    print(json.dumps(out, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
