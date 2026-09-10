import sys
import json

BLOCK_SIZE = 4096
DELAYSTARTBLOCK = 0xFFFFFFFFFFFFFFFE

class XfsDelallocEngine:
    def __init__(self, total_disk_blocks=100000, prealloc_multiplier=1):
        self.total_disk_blocks = total_disk_blocks
        self.free_disk_blocks = total_disk_blocks
        self.reserved_blocks = 0
        self.prealloc_multiplier = prealloc_multiplier
        self.inodes = {}
        self.next_physical_block = 1000
        self.stats = {
            "buffered_writes": 0,
            "delalloc_reservations": 0,
            "speculative_prealloc_blocks": 0,
            "prealloc_hits": 0,
            "converted_to_real": 0,
            "extents_merged": 0,
            "eof_trimmed_blocks": 0
        }

    def _get_inode(self, inode_id):
        if inode_id not in self.inodes:
            self.inodes[inode_id] = {"size": 0, "extents": []}
        return self.inodes[inode_id]

    def buffered_write(self, inode_id, file_offset_bytes, length_bytes):
        self.stats["buffered_writes"] += 1
        inode = self._get_inode(inode_id)
        start_block = file_offset_bytes // BLOCK_SIZE
        end_block = (file_offset_bytes + length_bytes + BLOCK_SIZE - 1) // BLOCK_SIZE
        needed_blocks = end_block - start_block

        is_extending = (file_offset_bytes + length_bytes > inode["size"])
        inode["size"] = max(inode["size"], file_offset_bytes + length_bytes)

        hit_extent = None
        for ext in inode["extents"]:
            ext_start = ext["offset"]
            ext_end = ext["offset"] + ext["blockcount"]
            if ext["state"] == "DELALLOC" and ext_start <= start_block <= ext_end:
                hit_extent = ext
                break

        if hit_extent:
            self.stats["prealloc_hits"] += 1
            hit_end = hit_extent["offset"] + hit_extent["blockcount"]

            if end_block <= hit_end:
                return {
                    "status": "DELALLOC_HIT_PREALLOC",
                    "inode_id": inode_id,
                    "offset_block": start_block,
                    "covered_by_extent": hit_extent["offset"],
                    "new_blocks_reserved": 0
                }
            else:
                extra_needed = end_block - hit_end
                spec_extra = extra_needed * self.prealloc_multiplier if (is_extending and self.prealloc_multiplier > 0) else 0
                total_extra = extra_needed + spec_extra

                if self.free_disk_blocks - self.reserved_blocks < total_extra:
                    if self.free_disk_blocks - self.reserved_blocks < extra_needed:
                        return {"status": "ENOSPC_DISK_FULL", "needed": extra_needed}
                    total_extra = extra_needed
                    spec_extra = 0

                self.reserved_blocks += total_extra
                hit_extent["blockcount"] += total_extra
                self.stats["speculative_prealloc_blocks"] += spec_extra
                return {
                    "status": "DELALLOC_EXTENDED",
                    "inode_id": inode_id,
                    "offset_block": start_block,
                    "extra_blocks_reserved": total_extra,
                    "total_blockcount": hit_extent["blockcount"]
                }

        spec_blocks = needed_blocks * self.prealloc_multiplier if (is_extending and self.prealloc_multiplier > 0) else 0
        total_reserve = needed_blocks + spec_blocks

        if self.free_disk_blocks - self.reserved_blocks < total_reserve:
            if self.free_disk_blocks - self.reserved_blocks < needed_blocks:
                return {"status": "ENOSPC_DISK_FULL", "needed": needed_blocks}
            total_reserve = needed_blocks
            spec_blocks = 0

        self.reserved_blocks += total_reserve
        self.stats["delalloc_reservations"] += 1
        self.stats["speculative_prealloc_blocks"] += spec_blocks

        new_ext = {
            "offset": start_block,
            "startblock": DELAYSTARTBLOCK,
            "blockcount": total_reserve,
            "state": "DELALLOC"
        }
        inode["extents"].append(new_ext)
        inode["extents"].sort(key=lambda x: x["offset"])

        return {
            "status": "DELALLOC_ALLOCATED",
            "inode_id": inode_id,
            "offset_block": start_block,
            "written_blocks": needed_blocks,
            "speculative_blocks": spec_blocks,
            "total_delalloc_blocks": total_reserve,
            "reserved_blocks_total": self.reserved_blocks
        }

    def flush_writeback(self, inode_id):
        if inode_id not in self.inodes:
            return {"status": "ENOENT_INODE_NOT_FOUND", "inode_id": inode_id}

        inode = self.inodes[inode_id]
        converted_count = 0
        blocks_converted = 0

        new_extents = []
        for ext in inode["extents"]:
            if ext["state"] == "DELALLOC":
                pblock = self.next_physical_block
                bcount = ext["blockcount"]
                self.next_physical_block += bcount
                self.free_disk_blocks -= bcount
                self.reserved_blocks -= bcount

                real_ext = {
                    "offset": ext["offset"],
                    "startblock": pblock,
                    "blockcount": bcount,
                    "state": "REAL"
                }
                new_extents.append(real_ext)
                converted_count += 1
                blocks_converted += bcount
                self.stats["converted_to_real"] += 1
            else:
                new_extents.append(ext)

        merged_extents = []
        for ext in sorted(new_extents, key=lambda x: x["offset"]):
            if not merged_extents:
                merged_extents.append(ext)
            else:
                prev = merged_extents[-1]
                if (prev["state"] == "REAL" and ext["state"] == "REAL" and
                    prev["offset"] + prev["blockcount"] == ext["offset"] and
                    prev["startblock"] + prev["blockcount"] == ext["startblock"]):
                    prev["blockcount"] += ext["blockcount"]
                    self.stats["extents_merged"] += 1
                else:
                    merged_extents.append(ext)

        inode["extents"] = merged_extents

        return {
            "status": "WRITEBACK_COMPLETED",
            "inode_id": inode_id,
            "extents_converted": converted_count,
            "blocks_converted": blocks_converted,
            "final_extents_count": len(inode["extents"]),
            "free_disk_blocks": self.free_disk_blocks
        }

    def trim_eof_blocks(self, inode_id):
        if inode_id not in self.inodes:
            return {"status": "ENOENT_INODE_NOT_FOUND", "inode_id": inode_id}

        inode = self.inodes[inode_id]
        eof_block = (inode["size"] + BLOCK_SIZE - 1) // BLOCK_SIZE

        trimmed_blocks = 0
        new_extents = []

        for ext in inode["extents"]:
            ext_start = ext["offset"]
            ext_end = ext["offset"] + ext["blockcount"]

            if ext_start >= eof_block:
                trimmed = ext["blockcount"]
                trimmed_blocks += trimmed
                if ext["state"] == "DELALLOC":
                    self.reserved_blocks -= trimmed
                else:
                    self.free_disk_blocks += trimmed
            elif ext_end > eof_block:
                valid_count = eof_block - ext_start
                trimmed = ext["blockcount"] - valid_count
                trimmed_blocks += trimmed
                ext["blockcount"] = valid_count
                if ext["state"] == "DELALLOC":
                    self.reserved_blocks -= trimmed
                else:
                    self.free_disk_blocks += trimmed
                new_extents.append(ext)
            else:
                new_extents.append(ext)

        inode["extents"] = new_extents
        self.stats["eof_trimmed_blocks"] += trimmed_blocks

        return {
            "status": "EOF_BLOCKS_TRIMMED",
            "inode_id": inode_id,
            "trimmed_blocks": trimmed_blocks,
            "eof_block": eof_block,
            "remaining_extents": len(inode["extents"])
        }

    def query_xfs_state(self):
        inode_summary = {}
        for ino in sorted(self.inodes.keys()):
            in_obj = self.inodes[ino]
            inode_summary[ino] = {
                "size_bytes": in_obj["size"],
                "extents": list(in_obj["extents"])
            }
        return {
            "free_disk_blocks": self.free_disk_blocks,
            "reserved_blocks": self.reserved_blocks,
            "inodes": inode_summary,
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
    total_blocks = cfg.get("total_disk_blocks", 100000)
    multiplier = cfg.get("prealloc_multiplier", 1)

    engine = XfsDelallocEngine(total_disk_blocks=total_blocks, prealloc_multiplier=multiplier)
    results = []

    for op in input_data.get("operations", []):
        cmd = op.get("op")
        if cmd == "BUFFERED_WRITE":
            res = engine.buffered_write(op["inode_id"], op["file_offset"], op["length"])
            results.append(res)
        elif cmd == "FLUSH_WRITEBACK":
            res = engine.flush_writeback(op["inode_id"])
            results.append(res)
        elif cmd == "TRIM_EOF_BLOCKS":
            res = engine.trim_eof_blocks(op["inode_id"])
            results.append(res)
        elif cmd == "QUERY_XFS_STATE":
            res = engine.query_xfs_state()
            results.append(res)

    out = {"results": results}
    print(json.dumps(out, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
