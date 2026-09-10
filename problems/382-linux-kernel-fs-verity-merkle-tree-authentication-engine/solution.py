# -*- coding: utf-8 -*-
"""
ZeliJudge Pro Track Problem #382: Linux Kernel Storage & Security: fsverity Merkle Tree Authentication Engine
Canonical Solution Implementation
"""
import sys
import json
import math
import hashlib

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class FSVerityEngine:
    def __init__(self, config):
        self.block_size = config.get("block_size", 4096)
        self.hash_algo = config.get("hash_algorithm", "sha256")
        self.keyring = set(config.get("trusted_keyring_ids", ["root_ca_key_01"]))
        self.files = {}
        self.history = []
        self.stats = {
            "files_enabled": 0,
            "read_requests": 0,
            "pages_verified_on_demand": 0,
            "page_cache_hits_skipped": 0,
            "corrupted_blocks_detected": 0,
            "total_data_bytes_read": 0
        }

    def _hash(self, data, salt=b""):
        if self.hash_algo == "sha256":
            h = hashlib.sha256()
        elif self.hash_algo == "sha512":
            h = hashlib.sha512()
        else:
            h = hashlib.sha256()
        h.update(salt)
        h.update(data if isinstance(data, (bytes, bytearray)) else data.encode("utf-8"))
        return h.hexdigest()

    def enable_verity(self, op):
        fid = op["file_id"]
        size = op["file_size_bytes"]
        salt = op.get("salt", "").encode("utf-8")
        raw_blocks = op.get("blocks", [])
        sig_info = op.get("signature", None)

        if sig_info:
            signer = sig_info.get("signer_key")
            if signer not in self.keyring or not sig_info.get("valid", True):
                self.history.append({
                    "op": "ENABLE_VERITY", "file_id": fid, "status": "ERR_KEYREJECTED",
                    "detail": f"signature verification failed: key {signer} not in trusted keyring or signature invalid"
                })
                return

        num_blocks = math.ceil(size / self.block_size) if size > 0 else 1
        l0_hashes = []
        for i in range(num_blocks):
            content = raw_blocks[i] if i < len(raw_blocks) else f"block_{i}_default_payload"
            l0_hashes.append(self._hash(content, salt))

        digest_bytes = 32 if self.hash_algo == "sha256" else 64
        hashes_per_block = self.block_size // digest_bytes

        levels = [list(l0_hashes)]
        current = l0_hashes
        while len(current) > 1:
            next_level = []
            for j in range(0, len(current), hashes_per_block):
                chunk = current[j:j+hashes_per_block]
                chunk_str = "".join(chunk)
                next_level.append(self._hash(chunk_str, salt))
            levels.append(next_level)
            current = next_level

        root_hash = current[0]
        total_tree_nodes = sum(len(lvl) for lvl in levels[1:]) if len(levels) > 1 else 0
        tree_blocks = math.ceil(total_tree_nodes / hashes_per_block) if total_tree_nodes > 0 else 0
        tree_storage_bytes = tree_blocks * self.block_size

        self.files[fid] = {
            "file_id": fid,
            "size": size,
            "salt": salt,
            "num_blocks": num_blocks,
            "raw_blocks": {i: (raw_blocks[i] if i < len(raw_blocks) else f"block_{i}_default_payload") for i in range(num_blocks)},
            "levels": levels,
            "root_hash": root_hash,
            "verified_pages": set(),
            "corrupted_pages": set(),
            "tree_storage_bytes": tree_storage_bytes
        }

        self.stats["files_enabled"] += 1
        overhead_pct = round((tree_storage_bytes / max(1, size)) * 100.0, 3)
        self.history.append({
            "op": "ENABLE_VERITY", "file_id": fid, "status": "SUCCESS",
            "root_hash": root_hash, "num_blocks": num_blocks,
            "tree_levels": len(levels), "tree_storage_bytes": tree_storage_bytes,
            "overhead_pct": overhead_pct,
            "detail": f"fsverity enabled: root_hash={root_hash[:16]}... over {num_blocks} blocks (tree overhead={overhead_pct}%)"
        })

    def tamper_block(self, op):
        fid = op["file_id"]
        bidx = op["block_index"]
        corrupt_data = op.get("corrupted_payload", "MALICIOUS_INJECTED_CODE")
        f = self.files.get(fid)
        if not f:
            self.history.append({"op": "INJECT_TAMPER", "file_id": fid, "status": "ERR_FILE_NOT_FOUND", "detail": "file not found"})
            return
        f["raw_blocks"][bidx] = corrupt_data
        f["corrupted_pages"].add(bidx)
        f["verified_pages"].discard(bidx)
        self.history.append({
            "op": "INJECT_TAMPER", "file_id": fid, "block_index": bidx, "status": "SUCCESS",
            "detail": f"simulated offline disk corruption: modified block {bidx} data"
        })

    def read_range(self, op):
        fid = op["file_id"]
        offset = op["offset"]
        length = op["length"]
        self.stats["read_requests"] += 1

        f = self.files.get(fid)
        if not f:
            self.history.append({"op": "READ", "file_id": fid, "status": "ERR_FILE_NOT_FOUND", "detail": "file not found"})
            return

        start_block = offset // self.block_size
        end_block = (offset + length - 1) // self.block_size
        end_block = min(end_block, f["num_blocks"] - 1)

        blocks_verified_in_req = 0
        blocks_cached_in_req = 0
        has_corruption = False
        failed_block = None

        for b in range(start_block, end_block + 1):
            if b in f["verified_pages"]:
                blocks_cached_in_req += 1
                self.stats["page_cache_hits_skipped"] += 1
                continue

            content = f["raw_blocks"].get(b, "")
            computed_hash = self._hash(content, f["salt"])
            expected_l0 = f["levels"][0][b]

            if computed_hash != expected_l0:
                has_corruption = True
                failed_block = b
                self.stats["corrupted_blocks_detected"] += 1
                break

            f["verified_pages"].add(b)
            blocks_verified_in_req += 1
            self.stats["pages_verified_on_demand"] += 1

        if has_corruption:
            self.history.append({
                "op": "READ", "file_id": fid, "offset": offset, "length": length,
                "status": "ERR_EIO", "failed_block": failed_block,
                "detail": f"EIO: fsverity integrity check failed on block {failed_block} (hash mismatch); I/O aborted"
            })
        else:
            self.stats["total_data_bytes_read"] += length
            self.history.append({
                "op": "READ", "file_id": fid, "offset": offset, "length": length,
                "status": "SUCCESS", "verified_blocks": blocks_verified_in_req,
                "cached_blocks": blocks_cached_in_req,
                "detail": f"read {length} bytes: {blocks_verified_in_req} blocks verified on-demand, {blocks_cached_in_req} from PageChecked cache"
            })

    def get_summary(self):
        total_files = len(self.files)
        total_corrupted = self.stats["corrupted_blocks_detected"]
        total_verified = self.stats["pages_verified_on_demand"]
        cache_skips = self.stats["page_cache_hits_skipped"]
        cache_ratio = round((cache_skips / max(1, cache_skips + total_verified)) * 100.0, 2)

        return {
            "total_files_protected": total_files,
            "total_read_requests": self.stats["read_requests"],
            "pages_verified_on_demand": total_verified,
            "page_cache_hits_skipped": cache_skips,
            "page_cache_skip_ratio_pct": cache_ratio,
            "corrupted_blocks_blocked": total_corrupted,
            "total_data_bytes_read": self.stats["total_data_bytes_read"]
        }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    eng = FSVerityEngine(data["config"])
    for op in data["operations"]:
        cmd = op["op"]
        if cmd == "ENABLE_VERITY":
            eng.enable_verity(op)
        elif cmd == "INJECT_TAMPER":
            eng.tamper_block(op)
        elif cmd == "READ":
            eng.read_range(op)
    result = {
        "history": eng.history,
        "summary": eng.get_summary()
    }
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
