import sys
import json
import math

SECTOR_SIZE = 4096

def shannon_entropy(data_bytes):
    if not data_bytes:
        return 0.0
    freq = {}
    for b in data_bytes:
        freq[b] = freq.get(b, 0) + 1
    entropy = 0.0
    total = len(data_bytes)
    for count in freq.values():
        p = count / total
        entropy -= p * math.log2(p)
    return entropy

class BtrfsCompressionEngine:
    def __init__(self, entropy_threshold=6.5, compression_ratio_factor=0.3):
        self.entropy_threshold = entropy_threshold
        self.compression_ratio_factor = compression_ratio_factor
        self.files = {}
        self.next_disk_bytenr = 0x10000000
        self.stats = {
            "chunks_processed": 0,
            "heuristic_incompressible_skips": 0,
            "compression_savings_rejected": 0,
            "compressed_extents_written": 0,
            "raw_extents_written": 0,
            "decompression_reads": 0
        }

    def set_config(self, entropy_threshold=None, compression_ratio_factor=None):
        if entropy_threshold is not None:
            self.entropy_threshold = entropy_threshold
        if compression_ratio_factor is not None:
            self.compression_ratio_factor = compression_ratio_factor
        return {
            "status": "CONFIG_UPDATED",
            "entropy_threshold": self.entropy_threshold,
            "compression_ratio_factor": self.compression_ratio_factor
        }

    def write_extent_chunk(self, inode_id, file_offset, data_str):
        data_bytes = data_str.encode("utf-8")
        data_len = len(data_bytes)
        uncompressed_sectors = (data_len + SECTOR_SIZE - 1) // SECTOR_SIZE
        uncompressed_disk_size = uncompressed_sectors * SECTOR_SIZE

        self.stats["chunks_processed"] += 1

        entropy = shannon_entropy(data_bytes)
        if entropy >= self.entropy_threshold:
            self.stats["heuristic_incompressible_skips"] += 1
            bytenr = self.next_disk_bytenr
            self.next_disk_bytenr += uncompressed_disk_size
            extent = {
                "file_offset": file_offset,
                "num_bytes": data_len,
                "disk_bytenr": bytenr,
                "disk_num_bytes": uncompressed_disk_size,
                "is_compressed": False,
                "entropy": round(entropy, 2),
                "data": data_str
            }
            if inode_id not in self.files:
                self.files[inode_id] = []
            self.files[inode_id].append(extent)
            self.stats["raw_extents_written"] += 1
            return {
                "status": "RAW_EXTENT_WRITTEN",
                "reason": "HEURISTIC_INCOMPRESSIBLE",
                "entropy": round(entropy, 2),
                "disk_num_bytes": uncompressed_disk_size
            }

        unique_bytes = len(set(data_bytes))
        estimated_compressed_len = int(data_len * (unique_bytes / 256.0) * self.compression_ratio_factor) + 128
        compressed_sectors = (estimated_compressed_len + SECTOR_SIZE - 1) // SECTOR_SIZE
        compressed_disk_size = compressed_sectors * SECTOR_SIZE

        if compressed_disk_size >= uncompressed_disk_size:
            self.stats["compression_savings_rejected"] += 1
            bytenr = self.next_disk_bytenr
            self.next_disk_bytenr += uncompressed_disk_size
            extent = {
                "file_offset": file_offset,
                "num_bytes": data_len,
                "disk_bytenr": bytenr,
                "disk_num_bytes": uncompressed_disk_size,
                "is_compressed": False,
                "entropy": round(entropy, 2),
                "data": data_str
            }
            if inode_id not in self.files:
                self.files[inode_id] = []
            self.files[inode_id].append(extent)
            self.stats["raw_extents_written"] += 1
            return {
                "status": "RAW_EXTENT_WRITTEN",
                "reason": "INSUFFICIENT_SPACE_SAVINGS",
                "compressed_sectors": compressed_sectors,
                "uncompressed_sectors": uncompressed_sectors,
                "disk_num_bytes": uncompressed_disk_size
            }

        bytenr = self.next_disk_bytenr
        self.next_disk_bytenr += compressed_disk_size
        extent = {
            "file_offset": file_offset,
            "num_bytes": data_len,
            "disk_bytenr": bytenr,
            "disk_num_bytes": compressed_disk_size,
            "is_compressed": True,
            "entropy": round(entropy, 2),
            "data": data_str
        }
        if inode_id not in self.files:
            self.files[inode_id] = []
        self.files[inode_id].append(extent)
        self.stats["compressed_extents_written"] += 1

        return {
            "status": "COMPRESSED_EXTENT_WRITTEN",
            "algorithm": "ZSTD",
            "entropy": round(entropy, 2),
            "orig_size": data_len,
            "disk_num_bytes": compressed_disk_size,
            "saved_bytes": uncompressed_disk_size - compressed_disk_size
        }

    def read_extent(self, inode_id, file_offset, length):
        if inode_id not in self.files:
            return {"status": "ENOENT_INODE_NOT_FOUND", "inode_id": inode_id}

        ext = None
        for e in self.files[inode_id]:
            if e["file_offset"] <= file_offset < e["file_offset"] + e["num_bytes"]:
                ext = e
                break

        if not ext:
            return {"status": "ENXIO_OFFSET_NOT_MAPPED", "file_offset": file_offset}

        slice_start = file_offset - ext["file_offset"]
        sub_str = ext["data"][slice_start : slice_start + length]

        if ext["is_compressed"]:
            self.stats["decompression_reads"] += 1

        return {
            "status": "EXTENT_READ_SUCCESS",
            "is_compressed": ext["is_compressed"],
            "disk_num_bytes_read": ext["disk_num_bytes"],
            "data_len": len(sub_str),
            "data_preview": sub_str[:32]
        }

    def query_btrfs_state(self):
        file_summary = {}
        for ino in sorted(self.files.keys()):
            exts = self.files[ino]
            file_summary[ino] = {
                "extent_count": len(exts),
                "total_file_bytes": sum(e["num_bytes"] for e in exts),
                "total_disk_bytes": sum(e["disk_num_bytes"] for e in exts)
            }
        return {
            "files": file_summary,
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
    ent = cfg.get("entropy_threshold", 6.5)
    ratio = cfg.get("compression_ratio_factor", 0.3)

    engine = BtrfsCompressionEngine(entropy_threshold=ent, compression_ratio_factor=ratio)
    results = []

    for op in input_data.get("operations", []):
        cmd = op.get("op")
        if cmd == "SET_CONFIG":
            res = engine.set_config(op.get("entropy_threshold"), op.get("compression_ratio_factor"))
            results.append(res)
        elif cmd == "WRITE_EXTENT_CHUNK":
            res = engine.write_extent_chunk(op["inode_id"], op["file_offset"], op["data_str"])
            results.append(res)
        elif cmd == "READ_EXTENT":
            res = engine.read_extent(op["inode_id"], op["file_offset"], op["length"])
            results.append(res)
        elif cmd == "QUERY_BTRFS_STATE":
            res = engine.query_btrfs_state()
            results.append(res)

    out = {"results": results}
    print(json.dumps(out, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
