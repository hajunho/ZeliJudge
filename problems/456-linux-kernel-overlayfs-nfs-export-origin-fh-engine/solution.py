import sys
import json

class OverlayNfsEngine:
    def __init__(self, index_enabled=True, nfs_export_enabled=True):
        self.index_enabled = index_enabled
        self.nfs_export_enabled = nfs_export_enabled
        self.lower_files = {}
        self.upper_files = {}
        self.index_dir = {}
        self.next_upper_ino = 50000
        self.stats = {
            "encoded_fh": 0,
            "decoded_fh": 0,
            "index_hits": 0,
            "copy_ups": 0,
            "stale_errors": 0
        }

    def init_overlay(self, lower_files, upper_files=None):
        self.lower_files = {f["path"]: {"ino": f["ino"], "gen": f.get("gen", 1), "size": f.get("size", 1024)} for f in lower_files}
        self.upper_files.clear()
        self.index_dir.clear()
        if upper_files:
            for f in upper_files:
                self.upper_files[f["path"]] = {
                    "ino": f["ino"],
                    "gen": f.get("gen", 1),
                    "size": f.get("size", 1024),
                    "origin_fh": f.get("origin_fh"),
                    "is_whiteout": f.get("is_whiteout", False)
                }
                if self.index_enabled and f.get("origin_fh"):
                    self.index_dir[f["origin_fh"]] = f["path"]
        return {
            "status": "OVERLAY_INITIALIZED",
            "lower_count": len(self.lower_files),
            "upper_count": len(self.upper_files),
            "index_enabled": self.index_enabled
        }

    def _encode_raw_fh(self, layer, ino, gen):
        return f"OVL:{layer}:{ino}:{gen}"

    def encode_fh(self, path):
        if not self.nfs_export_enabled:
            return {"status": "EOPNOTSUPP_NFS_EXPORT_DISABLED"}

        if path in self.upper_files:
            u_file = self.upper_files[path]
            if u_file["is_whiteout"]:
                return {"status": "ENOENT_FILE_NOT_FOUND", "path": path}
            fh = self._encode_raw_fh("UPPER", u_file["ino"], u_file["gen"])
            self.stats["encoded_fh"] += 1
            return {"status": "FH_ENCODED", "path": path, "fh": fh, "layer": "UPPER", "ino": u_file["ino"]}

        if path in self.lower_files:
            l_file = self.lower_files[path]
            fh = self._encode_raw_fh("LOWER", l_file["ino"], l_file["gen"])
            self.stats["encoded_fh"] += 1
            return {"status": "FH_ENCODED", "path": path, "fh": fh, "layer": "LOWER", "ino": l_file["ino"]}

        return {"status": "ENOENT_FILE_NOT_FOUND", "path": path}

    def copy_up(self, path, new_size=None):
        if path not in self.lower_files:
            return {"status": "ENOENT_NOT_IN_LOWER", "path": path}
        if path in self.upper_files and not self.upper_files[path]["is_whiteout"]:
            return {"status": "EEXIST_ALREADY_IN_UPPER", "path": path}

        l_file = self.lower_files[path]
        origin_fh = self._encode_raw_fh("LOWER", l_file["ino"], l_file["gen"])
        u_ino = self.next_upper_ino
        self.next_upper_ino += 1

        size = new_size if new_size is not None else l_file["size"]
        self.upper_files[path] = {
            "ino": u_ino,
            "gen": 1,
            "size": size,
            "origin_fh": origin_fh,
            "is_whiteout": False
        }

        if self.index_enabled:
            self.index_dir[origin_fh] = path

        self.stats["copy_ups"] += 1
        return {
            "status": "COPY_UP_SUCCESS",
            "path": path,
            "lower_ino": l_file["ino"],
            "upper_ino": u_ino,
            "origin_fh": origin_fh,
            "indexed": self.index_enabled
        }

    def create_upper(self, path, size=0):
        if (path in self.upper_files and not self.upper_files[path]["is_whiteout"]) or (path in self.lower_files and path not in self.upper_files):
            return {"status": "EEXIST_FILE_EXISTS", "path": path}

        u_ino = self.next_upper_ino
        self.next_upper_ino += 1
        self.upper_files[path] = {
            "ino": u_ino,
            "gen": 1,
            "size": size,
            "origin_fh": None,
            "is_whiteout": False
        }
        return {"status": "UPPER_FILE_CREATED", "path": path, "ino": u_ino}

    def delete_file(self, path):
        exists_in_upper = (path in self.upper_files and not self.upper_files[path]["is_whiteout"])
        exists_in_lower = (path in self.lower_files)

        if not exists_in_upper and not exists_in_lower:
            return {"status": "ENOENT_FILE_NOT_FOUND", "path": path}

        if exists_in_lower:
            u_ino = self.next_upper_ino
            self.next_upper_ino += 1
            self.upper_files[path] = {
                "ino": u_ino,
                "gen": 1,
                "size": 0,
                "origin_fh": None,
                "is_whiteout": True
            }
        else:
            del self.upper_files[path]

        return {"status": "FILE_DELETED", "path": path, "whiteout_created": exists_in_lower}

    def decode_fh(self, fh):
        if not self.nfs_export_enabled:
            return {"status": "EOPNOTSUPP_NFS_EXPORT_DISABLED"}

        parts = fh.split(":")
        if len(parts) != 4 or parts[0] != "OVL":
            return {"status": "EINVAL_CORRUPT_FH", "fh": fh}

        layer = parts[1]
        try:
            ino = int(parts[2])
            gen = int(parts[3])
        except ValueError:
            return {"status": "EINVAL_CORRUPT_FH", "fh": fh}

        self.stats["decoded_fh"] += 1

        if layer == "UPPER":
            for p, u_file in self.upper_files.items():
                if u_file["ino"] == ino and u_file["gen"] == gen:
                    if u_file["is_whiteout"]:
                        self.stats["stale_errors"] += 1
                        return {"status": "ESTALE_WHITEOUT_DELETED", "fh": fh}
                    return {
                        "status": "FH_DECODED",
                        "path": p,
                        "layer": "UPPER",
                        "ino": ino,
                        "gen": gen,
                        "is_copied_up": (u_file["origin_fh"] is not None)
                    }
            self.stats["stale_errors"] += 1
            return {"status": "ESTALE_FILE_REMOVED", "fh": fh}

        elif layer == "LOWER":
            if self.index_enabled and fh in self.index_dir:
                upper_path = self.index_dir[fh]
                if upper_path in self.upper_files:
                    u_file = self.upper_files[upper_path]
                    if not u_file["is_whiteout"]:
                        self.stats["index_hits"] += 1
                        return {
                            "status": "FH_DECODED_VIA_INDEX",
                            "path": upper_path,
                            "layer": "UPPER",
                            "ino": u_file["ino"],
                            "gen": u_file["gen"],
                            "origin_fh": fh,
                            "is_copied_up": True
                        }
                    else:
                        self.stats["stale_errors"] += 1
                        return {"status": "ESTALE_WHITEOUT_DELETED", "fh": fh}

            for p, l_file in self.lower_files.items():
                if l_file["ino"] == ino and l_file["gen"] == gen:
                    if p in self.upper_files and self.upper_files[p]["is_whiteout"]:
                        self.stats["stale_errors"] += 1
                        return {"status": "ESTALE_WHITEOUT_DELETED", "fh": fh}
                    if not self.index_enabled and p in self.upper_files and not self.upper_files[p]["is_whiteout"]:
                        self.stats["stale_errors"] += 1
                        return {"status": "ESTALE_UNINDEXED_COPYUP", "fh": fh}
                    return {
                        "status": "FH_DECODED",
                        "path": p,
                        "layer": "LOWER",
                        "ino": ino,
                        "gen": gen,
                        "is_copied_up": False
                    }

            self.stats["stale_errors"] += 1
            return {"status": "ESTALE_FILE_REMOVED", "fh": fh}

        return {"status": "EINVAL_UNKNOWN_LAYER", "layer": layer}

    def query_export_state(self):
        return {
            "index_enabled": self.index_enabled,
            "nfs_export_enabled": self.nfs_export_enabled,
            "index_entries_count": len(self.index_dir),
            "upper_files_count": len(self.upper_files),
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

    cfg = input_data.get("config", {})
    idx = cfg.get("index_enabled", True)
    nfs = cfg.get("nfs_export_enabled", True)

    engine = OverlayNfsEngine(index_enabled=idx, nfs_export_enabled=nfs)
    results = []

    for op in input_data.get("operations", []):
        cmd = op.get("op")
        if cmd == "INIT_OVERLAY":
            res = engine.init_overlay(op["lower_files"], op.get("upper_files"))
            results.append(res)
        elif cmd == "ENCODE_FH":
            res = engine.encode_fh(op["path"])
            results.append(res)
        elif cmd == "DECODE_FH":
            res = engine.decode_fh(op["fh"])
            results.append(res)
        elif cmd == "COPY_UP":
            res = engine.copy_up(op["path"], op.get("new_size"))
            results.append(res)
        elif cmd == "CREATE_UPPER":
            res = engine.create_upper(op["path"], op.get("size", 0))
            results.append(res)
        elif cmd == "DELETE_FILE":
            res = engine.delete_file(op["path"])
            results.append(res)
        elif cmd == "QUERY_EXPORT_STATE":
            res = engine.query_export_state()
            results.append(res)

    out = {"results": results}
    print(json.dumps(out, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
