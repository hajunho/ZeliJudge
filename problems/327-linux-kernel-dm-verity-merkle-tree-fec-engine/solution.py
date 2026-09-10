import sys
import json
import hashlib
import copy

# Ensure UTF-8 I/O for Windows environments
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")

def sha256_hash(data: bytes, salt: bytes = b"") -> str:
    h = hashlib.sha256()
    h.update(salt)
    h.update(data)
    return h.hexdigest()

class DMVerityDevice:
    def __init__(self, raw_config: dict):
        config = copy.deepcopy(raw_config)
        self.dev_name = config.get("name", "dm-vroot")
        self.block_size = int(config.get("block_size", 64))
        self.salt = config.get("salt", "verity_salt").encode("utf-8")
        self.corruption_mode = config.get("corruption_mode", "EIO")  # EIO, PANIC, RESTART, LOG_ONLY
        self.fec_enabled = bool(config.get("fec_enabled", False))
        self.fec_roots = int(config.get("fec_roots", 2))

        self.data_blocks = {}
        raw_data = config.get("data_blocks", [])
        for i, blk_data in enumerate(raw_data):
            b = blk_data.encode("utf-8")
            if len(b) < self.block_size:
                b = b.ljust(self.block_size, b"\x00")
            elif len(b) > self.block_size:
                b = b[:self.block_size]
            self.data_blocks[i] = b

        self.num_data_blocks = len(self.data_blocks)
        self.hashes_per_block = max(2, int(config.get("hashes_per_block", 4)))
        
        self.merkle_tree = []
        self.root_hash = ""
        self.fec_parity = {}
        self.stats = {
            "reads_total": 0,
            "reads_verified": 0,
            "corruptions_detected": 0,
            "fec_repairs": 0,
            "io_errors": 0
        }
        self.read_logs = []
        self.build_tree()

    def build_tree(self):
        if self.num_data_blocks == 0:
            self.root_hash = sha256_hash(b"", self.salt)
            return

        cur_level_hashes = []
        for i in range(self.num_data_blocks):
            blk = self.data_blocks[i]
            h = sha256_hash(blk, self.salt)
            cur_level_hashes.append(h)
            if self.fec_enabled:
                self.fec_parity[i] = bytes(blk)

        self.merkle_tree = []

        while len(cur_level_hashes) > 1:
            level_blocks = []
            next_level_hashes = []
            for i in range(0, len(cur_level_hashes), self.hashes_per_block):
                chunk = cur_level_hashes[i:i + self.hashes_per_block]
                level_blocks.append(chunk)
                chunk_bytes = "".join(chunk).encode("utf-8")
                next_level_hashes.append(sha256_hash(chunk_bytes, self.salt))
            self.merkle_tree.append(level_blocks)
            cur_level_hashes = next_level_hashes

        self.merkle_tree.append([[cur_level_hashes[0]]])
        self.root_hash = cur_level_hashes[0]

    def read_block(self, block_idx: int) -> dict:
        self.stats["reads_total"] += 1
        if block_idx not in self.data_blocks:
            return {"block_idx": block_idx, "status": "ERROR_OUT_OF_BOUNDS"}

        cur_data = self.data_blocks[block_idx]
        calc_hash = sha256_hash(cur_data, self.salt)

        expected_hash = None
        tree_idx = block_idx
        path_verified = True
        fec_applied = False

        chunk_idx = tree_idx // self.hashes_per_block
        offset_in_chunk = tree_idx % self.hashes_per_block
        
        if len(self.merkle_tree) > 0 and chunk_idx < len(self.merkle_tree[0]):
            expected_hash = self.merkle_tree[0][chunk_idx][offset_in_chunk]

        if calc_hash != expected_hash:
            self.stats["corruptions_detected"] += 1
            if self.fec_enabled and block_idx in self.fec_parity:
                orig_data = self.fec_parity[block_idx]
                recovered_hash = sha256_hash(orig_data, self.salt)
                if recovered_hash == expected_hash:
                    self.data_blocks[block_idx] = bytes(orig_data)
                    self.stats["fec_repairs"] += 1
                    fec_applied = True
                else:
                    path_verified = False
            else:
                path_verified = False

        if path_verified:
            self.stats["reads_verified"] += 1
            res = {
                "block_idx": block_idx,
                "status": "VERIFIED",
                "fec_repaired": fec_applied,
                "root_hash": self.root_hash
            }
        else:
            self.stats["io_errors"] += 1
            res = {
                "block_idx": block_idx,
                "status": f"CORRUPTED_{self.corruption_mode}",
                "fec_repaired": False,
                "root_hash": self.root_hash
            }

        self.read_logs.append(res)
        return res

    def corrupt_block(self, block_idx: int, byte_offset: int, corrupted_char: str):
        if block_idx in self.data_blocks:
            b = bytearray(self.data_blocks[block_idx])
            b[byte_offset % self.block_size] = ord(corrupted_char[0])
            self.data_blocks[block_idx] = bytes(b)

    def run_commands(self, commands: list):
        for cmd in commands:
            ctype = cmd["type"]
            if ctype == "READ_BLOCK":
                self.read_block(cmd["block_idx"])
            elif ctype == "CORRUPT_BLOCK":
                self.corrupt_block(cmd["block_idx"], cmd.get("byte_offset", 0), cmd.get("char", "X"))
            elif ctype == "VERIFY_ALL":
                for idx in sorted(self.data_blocks.keys()):
                    self.read_block(idx)

    def get_state(self) -> dict:
        return {
            "dev_name": self.dev_name,
            "root_hash": self.root_hash,
            "fec_enabled": self.fec_enabled,
            "corruption_mode": self.corruption_mode,
            "stats": self.stats,
            "read_logs": self.read_logs,
            "merkle_levels": len(self.merkle_tree)
        }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    dev = DMVerityDevice(data.get("config", {}))
    dev.run_commands(data.get("commands", []))
    print(json.dumps(dev.get_state(), separators=(",", ":"), ensure_ascii=False))

if __name__ == "__main__":
    main()
