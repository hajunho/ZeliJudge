# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #339: Distributed CephFS MDS Inode Caps & Subtree Partitioning Engine.
"""
import sys
import json

sys.stdout.reconfigure(encoding="utf-8")

class CephFsMdsEngine:
    def __init__(self, config):
        self.max_ranks = config.get("mds_ranks", 2)
        self.subtrees = {"/": {"rank": 0, "state": "ACTIVE"}}
        self.inodes = {
            "/": {"type": "DIR", "size": 4096, "version": 1, "dirty_clients": set()}
        }
        self.inode_caps = {"/": {}}
        self.clients = set()
        
        self.stats = {
            "cap_grants": 0,
            "cap_revocations": 0,
            "cap_flushes": 0,
            "subtree_migrations": 0,
            "dirty_cap_updates": 0
        }

    def _resolve_rank(self, path):
        best_prefix = "/"
        for p in self.subtrees:
            if path == p or path.startswith(p.rstrip("/") + "/"):
                if len(p) > len(best_prefix):
                    best_prefix = p
        return self.subtrees[best_prefix]["rank"], best_prefix

    def create_inode(self, path, itype="FILE", size=0):
        if path in self.inodes:
            return {"status": "ALREADY_EXISTS", "path": path}
        self.inodes[path] = {
            "type": itype,
            "size": size,
            "version": 1,
            "dirty_clients": set()
        }
        self.inode_caps[path] = {}
        rank, sub_root = self._resolve_rank(path)
        return {"status": "CREATED", "path": path, "mds_rank": rank, "subtree_root": sub_root}

    def split_subtree(self, path, dst_rank):
        if path not in self.inodes or self.inodes[path]["type"] != "DIR":
            return {"error": "INVALID_DIR_PATH"}
        if dst_rank >= self.max_ranks:
            return {"error": "INVALID_MDS_RANK"}
        
        self.subtrees[path] = {"rank": dst_rank, "state": "ACTIVE"}
        self.stats["subtree_migrations"] += 1
        return {"status": "SUBTREE_EXPORTED", "path": path, "assigned_rank": dst_rank}

    def request_cap(self, client_id, path, req_mode="READ"):
        if path not in self.inodes:
            return {"error": "INODE_NOT_FOUND"}
        self.clients.add(client_id)
        current_caps = self.inode_caps[path]
        revocations = []
        
        if req_mode == "READ":
            for cid, cinfo in list(current_caps.items()):
                if cid != client_id and ("Fx" in cinfo["caps"] or "Fw" in cinfo["caps"]):
                    if cinfo["dirty"]:
                        self.stats["cap_flushes"] += 1
                        self.inodes[path]["size"] = max(self.inodes[path]["size"], cinfo["size"])
                        self.inodes[path]["version"] += 1
                        cinfo["dirty"] = False
                    cinfo["caps"] = {"Fs", "Fc"}
                    self.stats["cap_revocations"] += 1
                    revocations.append({"revoked_client": cid, "revoked_caps": ["Fx", "Fw"], "downgraded_to": ["Fs", "Fc"]})
            
            if client_id not in current_caps:
                current_caps[client_id] = {"caps": set(), "dirty": False, "size": self.inodes[path]["size"]}
            current_caps[client_id]["caps"].update(["Fs", "Fc"])
            self.stats["cap_grants"] += 1
            rank, _ = self._resolve_rank(path)
            return {
                "status": "CAP_GRANTED",
                "client_id": client_id,
                "path": path,
                "granted_caps": sorted(list(current_caps[client_id]["caps"])),
                "mds_rank": rank,
                "revocations": revocations
            }

        elif req_mode == "WRITE":
            for cid, cinfo in list(current_caps.items()):
                if cid != client_id:
                    if cinfo["dirty"]:
                        self.stats["cap_flushes"] += 1
                        self.inodes[path]["size"] = max(self.inodes[path]["size"], cinfo["size"])
                        self.inodes[path]["version"] += 1
                        cinfo["dirty"] = False
                    rev_caps = sorted(list(cinfo["caps"]))
                    cinfo["caps"] = set()
                    self.stats["cap_revocations"] += 1
                    revocations.append({"revoked_client": cid, "revoked_caps": rev_caps})
            
            if client_id not in current_caps:
                current_caps[client_id] = {"caps": set(), "dirty": False, "size": self.inodes[path]["size"]}
            current_caps[client_id]["caps"] = {"Fs", "Fc", "Fw", "Fx"}
            self.stats["cap_grants"] += 1
            rank, _ = self._resolve_rank(path)
            return {
                "status": "CAP_GRANTED",
                "client_id": client_id,
                "path": path,
                "granted_caps": sorted(list(current_caps[client_id]["caps"])),
                "mds_rank": rank,
                "revocations": revocations
            }

    def write_data(self, client_id, path, new_size):
        if path not in self.inodes:
            return {"error": "INODE_NOT_FOUND"}
        cinfo = self.inode_caps[path].get(client_id)
        if not cinfo or "Fw" not in cinfo["caps"]:
            return {"error": "NO_WRITE_CAP"}
        
        cinfo["dirty"] = True
        cinfo["size"] = new_size
        self.inodes[path]["dirty_clients"].add(client_id)
        self.stats["dirty_cap_updates"] += 1
        return {
            "status": "WRITE_BUFFERED",
            "client_id": client_id,
            "path": path,
            "buffered_size": new_size,
            "is_dirty": True
        }

    def flush_caps(self, client_id, path):
        if path not in self.inodes:
            return {"error": "INODE_NOT_FOUND"}
        cinfo = self.inode_caps[path].get(client_id)
        if not cinfo:
            return {"error": "NO_CAP_RECORD"}
        
        if cinfo["dirty"]:
            self.inodes[path]["size"] = max(self.inodes[path]["size"], cinfo["size"])
            self.inodes[path]["version"] += 1
            cinfo["dirty"] = False
            self.inodes[path]["dirty_clients"].discard(client_id)
            self.stats["cap_flushes"] += 1
            return {
                "status": "CAPS_FLUSHED",
                "client_id": client_id,
                "path": path,
                "committed_size": self.inodes[path]["size"],
                "inode_version": self.inodes[path]["version"]
            }
        return {
            "status": "NO_DIRTY_CAPS",
            "client_id": client_id,
            "path": path
        }

    def get_cluster_state(self):
        return {
            "stats": self.stats,
            "subtrees": self.subtrees,
            "total_inodes": len(self.inodes),
            "active_clients": sorted(list(self.clients))
        }

def solve():
    raw_data = sys.stdin.read().strip()
    if not raw_data:
        return
    data = json.loads(raw_data)
    engine = CephFsMdsEngine(data["config"])
    results = []
    for op in data["operations"]:
        opcode = op["op"]
        if opcode == "CREATE_INODE":
            res = engine.create_inode(op["path"], op.get("type", "FILE"), op.get("size", 0))
            results.append(res)
        elif opcode == "SPLIT_SUBTREE":
            res = engine.split_subtree(op["path"], op["dst_rank"])
            results.append(res)
        elif opcode == "REQUEST_CAP":
            res = engine.request_cap(op["client_id"], op["path"], op.get("cap_type", "READ"))
            results.append(res)
        elif opcode == "WRITE_DATA":
            res = engine.write_data(op["client_id"], op["path"], op["new_size"])
            results.append(res)
        elif opcode == "FLUSH_CAPS":
            res = engine.flush_caps(op["client_id"], op["path"])
            results.append(res)
    
    cluster_state = engine.get_cluster_state()
    output = {
        "results": results,
        "cluster_state": cluster_state
    }
    print(json.dumps(output, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    solve()
