# -*- coding: utf-8 -*-
"""
ZeliJudge Pro #389: Linux Kernel EROFS VLE In-Place Decompression & Extent Mapping Engine
Implementation in Python 3.
"""
import sys
import json

PAGE_SIZE = 4096

class ErofsEngine:
    def __init__(self, config):
        self.block_size = config.get("block_size", 4096)
        self.inodes = {}
        self.events = []
        self.total_ipd = 0
        self.total_bounce = 0

    def run_commands(self, commands):
        for cmd in commands:
            op = cmd.get("op")
            if op == "CREATE_INODE":
                self._handle_create_inode(cmd)
            elif op == "READ":
                self._handle_read(cmd)

    def _handle_create_inode(self, cmd):
        ino = cmd["ino"]
        file_size = cmd["size"]
        is_extended = cmd.get("is_extended", False)
        extents = cmd.get("extents", [])

        self.inodes[ino] = {
            "ino": ino,
            "size": file_size,
            "format": "EXTENDED" if is_extended else "COMPACT",
            "inode_bytes": 64 if is_extended else 32,
            "extents": extents
        }
        self.events.append({
            "op": "CREATE_INODE",
            "ino": ino,
            "size": file_size,
            "format": "EXTENDED" if is_extended else "COMPACT",
            "extents_count": len(extents),
            "status": "SUCCESS"
        })

    def _handle_read(self, cmd):
        ino = cmd["ino"]
        offset = cmd["offset"]
        length = cmd["length"]

        if ino not in self.inodes:
            self.events.append({"op": "READ", "ino": ino, "status": "FAIL_NO_INODE"})
            return

        inode = self.inodes[ino]
        if offset + length > inode["size"]:
            length = max(0, inode["size"] - offset)

        start_c = offset // self.block_size
        end_c = (offset + length - 1) // self.block_size if length > 0 else start_c

        ipd_count = 0
        bounce_count = 0
        clusters_read = 0
        assembled_data = bytearray()

        extent_map = {e["logical_cluster"]: e for e in inode["extents"]}

        for c_idx in range(start_c, end_c + 1):
            if c_idx not in extent_map:
                self.events.append({
                    "op": "READ",
                    "ino": ino,
                    "cluster": c_idx,
                    "status": "EIO_HOLE_OR_UNMAPPED"
                })
                return

            e = extent_map[c_idx]
            clusters_read += 1
            raw_hex = e.get("data", "")
            raw_bytes = bytes.fromhex(raw_hex) if raw_hex else bytes([0] * e["usize"])

            if e["type"] == "EROFS_MAP_MAPPED":
                cluster_decompressed = raw_bytes
            else:
                if e["csize"] <= self.block_size:
                    ipd_count += 1
                    self.total_ipd += 1
                else:
                    bounce_count += 1
                    self.total_bounce += 1

                if len(raw_bytes) < e["csize"]:
                    self.events.append({
                        "op": "READ",
                        "ino": ino,
                        "cluster": c_idx,
                        "status": "EIO_DECOMPRESSION_CORRUPT"
                    })
                    return

                cluster_decompressed = bytearray(raw_bytes[:e["csize"]])
                if len(cluster_decompressed) < e["usize"]:
                    cluster_decompressed.extend([0xaa] * (e["usize"] - len(cluster_decompressed)))
                else:
                    cluster_decompressed = cluster_decompressed[:e["usize"]]

            assembled_data.extend(cluster_decompressed)

        rel_start = offset - (start_c * self.block_size)
        rel_end = rel_start + length
        result_bytes = assembled_data[rel_start:rel_end]

        self.events.append({
            "op": "READ",
            "ino": ino,
            "offset": offset,
            "length": length,
            "clusters_read": clusters_read,
            "ipd_count": ipd_count,
            "bounce_count": bounce_count,
            "status": "SUCCESS"
        })

    def get_result(self):
        total_uncompressed = sum(ino["size"] for ino in self.inodes.values())
        total_compressed = 0
        total_metadata = sum(ino["inode_bytes"] for ino in self.inodes.values())
        for ino in self.inodes.values():
            for e in ino["extents"]:
                total_compressed += e.get("csize", e.get("usize", 0))

        ratio = (total_compressed / total_uncompressed) if total_uncompressed > 0 else 1.0
        return {
            "total_inodes": len(self.inodes),
            "total_uncompressed_bytes": total_uncompressed,
            "total_compressed_bytes": total_compressed,
            "total_metadata_bytes": total_metadata,
            "compression_ratio": round(ratio, 4),
            "total_ipd_decompressions": self.total_ipd,
            "total_bounce_decompressions": self.total_bounce,
            "events": self.events
        }

def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    commands = data.get("commands", [])

    engine = ErofsEngine(config)
    engine.run_commands(commands)
    result = engine.get_result()

    sys.stdout.write(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
