# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #431 Solution:
Linux Kernel File Systems & Storage: fs/iomap Modern Direct I/O (O_DIRECT), Extent State Machine & Bio Splitting Engine
(fs/iomap/direct-io.c, fs/iomap/iter.c, include/linux/iomap.h)
"""

import sys
import json

# Ensure UTF-8 streams on Windows
if sys.platform == "win32":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")


class IomapExtent:
    def __init__(self, offset, length, paddr, extent_type, flags=0):
        self.offset = offset
        self.length = length
        self.paddr = paddr
        self.extent_type = extent_type
        self.flags = flags

    def end(self):
        return self.offset + self.length


class IomapEngine:
    def __init__(self, config):
        self.sector_size = config.get("sector_size", 512)
        self.max_bio_size = config.get("max_bio_size", 65536)
        self.allow_unaligned = config.get("allow_unaligned", False)
        
        self.extents = []
        for ext_data in config.get("initial_extents", []):
            self.extents.append(IomapExtent(
                ext_data["offset"],
                ext_data["length"],
                ext_data.get("paddr", -1),
                ext_data["type"],
                ext_data.get("flags", 0)
            ))
        self._sort_extents()

        self.total_bytes_read = 0
        self.total_bytes_written = 0
        self.zero_filled_bytes = 0
        self.bio_count = 0
        self.unwritten_conversions = 0
        self.aligned_io_count = 0
        self.unaligned_rejects = 0

    def _sort_extents(self):
        self.extents.sort(key=lambda x: x.offset)

    def _find_extent(self, pos):
        for ext in self.extents:
            if ext.offset <= pos < ext.end():
                return ext
        return None

    def execute_command(self, cmd):
        op = cmd.get("op")
        if op == "IOMAP_READ":
            return self._iomap_read(cmd)
        elif op == "IOMAP_WRITE":
            return self._iomap_write(cmd)
        elif op == "ALLOC_EXTENT":
            return self._alloc_extent(cmd)
        elif op == "DUMP_EXTENTS":
            return self._dump_extents(cmd)
        else:
            return {"op": op, "status": "UNKNOWN_OP"}

    def _check_alignment(self, offset, length):
        if self.allow_unaligned:
            return True
        return (offset % self.sector_size == 0) and (length % self.sector_size == 0)

    def _iomap_read(self, cmd):
        offset = cmd["offset"]
        length = cmd["length"]

        if not self._check_alignment(offset, length):
            self.unaligned_rejects += 1
            return {
                "op": "IOMAP_READ",
                "offset": offset,
                "length": length,
                "status": "EINVAL_UNALIGNED_DIRECT_IO",
                "bios": []
            }

        self.aligned_io_count += 1
        pos = offset
        remaining = length
        bios = []
        zero_fill = 0
        disk_read = 0

        while remaining > 0:
            ext = self._find_extent(pos)
            if not ext:
                next_ext_offset = None
                for e in self.extents:
                    if e.offset > pos:
                        if next_ext_offset is None or e.offset < next_ext_offset:
                            next_ext_offset = e.offset
                
                chunk_len = remaining if next_ext_offset is None else min(remaining, next_ext_offset - pos)
                zero_fill += chunk_len
                bios.append({
                    "type": "ZERO_FILL",
                    "offset": pos,
                    "length": chunk_len,
                    "paddr": -1,
                    "origin_type": "HOLE"
                })
                pos += chunk_len
                remaining -= chunk_len
                continue

            ext_remaining = ext.end() - pos
            chunk_len = min(remaining, ext_remaining)

            if ext.extent_type in ("HOLE", "UNWRITTEN"):
                zero_fill += chunk_len
                bios.append({
                    "type": "ZERO_FILL",
                    "offset": pos,
                    "length": chunk_len,
                    "paddr": -1,
                    "origin_type": ext.extent_type
                })
            elif ext.extent_type == "MAPPED":
                curr_p = ext.paddr + (pos - ext.offset)
                cur_rem = chunk_len
                cur_pos = pos
                while cur_rem > 0:
                    bio_len = min(cur_rem, self.max_bio_size)
                    self.bio_count += 1
                    bios.append({
                        "type": "BIO_READ",
                        "offset": cur_pos,
                        "length": bio_len,
                        "paddr": curr_p
                    })
                    curr_p += bio_len
                    cur_pos += bio_len
                    cur_rem -= bio_len
                    disk_read += bio_len
            elif ext.extent_type == "INLINE":
                bios.append({
                    "type": "INLINE_COPY",
                    "offset": pos,
                    "length": chunk_len,
                    "paddr": ext.paddr
                })
                disk_read += chunk_len

            pos += chunk_len
            remaining -= chunk_len

        self.total_bytes_read += length
        self.zero_filled_bytes += zero_fill

        return {
            "op": "IOMAP_READ",
            "offset": offset,
            "length": length,
            "status": "SUCCESS",
            "bytes_read": length,
            "zero_filled_bytes": zero_fill,
            "disk_bytes_read": disk_read,
            "bios": bios
        }

    def _iomap_write(self, cmd):
        offset = cmd["offset"]
        length = cmd["length"]

        if not self._check_alignment(offset, length):
            self.unaligned_rejects += 1
            return {
                "op": "IOMAP_WRITE",
                "offset": offset,
                "length": length,
                "status": "EINVAL_UNALIGNED_DIRECT_IO",
                "bios": []
            }

        self.aligned_io_count += 1
        pos = offset
        remaining = length
        bios = []
        converted_ranges = []

        while remaining > 0:
            ext = self._find_extent(pos)
            if not ext or ext.extent_type == "HOLE":
                alloc_p = cmd.get("alloc_paddr", 1000000 + pos)
                ext_len = max(remaining, 65536)
                new_ext = IomapExtent(pos, ext_len, alloc_p, "MAPPED")
                self._insert_or_replace_extent(new_ext)
                ext = new_ext

            ext_remaining = ext.end() - pos
            chunk_len = min(remaining, ext_remaining)

            if ext.extent_type == "UNWRITTEN":
                self._convert_unwritten(ext, pos, chunk_len)
                self.unwritten_conversions += 1
                converted_ranges.append({"offset": pos, "length": chunk_len})
                ext = self._find_extent(pos)

            curr_p = ext.paddr + (pos - ext.offset)
            cur_rem = chunk_len
            cur_pos = pos
            while cur_rem > 0:
                bio_len = min(cur_rem, self.max_bio_size)
                self.bio_count += 1
                bios.append({
                    "type": "BIO_WRITE",
                    "offset": cur_pos,
                    "length": bio_len,
                    "paddr": curr_p
                })
                curr_p += bio_len
                cur_pos += bio_len
                cur_rem -= bio_len

            pos += chunk_len
            remaining -= chunk_len

        self.total_bytes_written += length

        return {
            "op": "IOMAP_WRITE",
            "offset": offset,
            "length": length,
            "status": "SUCCESS",
            "bytes_written": length,
            "bios": bios,
            "converted_ranges": converted_ranges
        }

    def _convert_unwritten(self, ext, pos, length):
        orig_offset = ext.offset
        orig_len = ext.length
        orig_paddr = ext.paddr
        self.extents.remove(ext)

        before_len = pos - orig_offset
        if before_len > 0:
            self.extents.append(IomapExtent(orig_offset, before_len, orig_paddr, "UNWRITTEN"))

        mid_paddr = orig_paddr + before_len
        self.extents.append(IomapExtent(pos, length, mid_paddr, "MAPPED"))

        after_len = orig_len - (before_len + length)
        if after_len > 0:
            after_offset = pos + length
            after_paddr = mid_paddr + length
            self.extents.append(IomapExtent(after_offset, after_len, after_paddr, "UNWRITTEN"))

        self._sort_extents()

    def _insert_or_replace_extent(self, new_ext):
        to_remove = []
        for e in self.extents:
            if not (e.end() <= new_ext.offset or e.offset >= new_ext.end()):
                to_remove.append(e)
        for e in to_remove:
            self.extents.remove(e)
        self.extents.append(new_ext)
        self._sort_extents()

    def _alloc_extent(self, cmd):
        ext = IomapExtent(cmd["offset"], cmd["length"], cmd["paddr"], cmd["type"])
        self._insert_or_replace_extent(ext)
        return {
            "op": "ALLOC_EXTENT",
            "status": "EXTENT_ALLOCATED",
            "offset": ext.offset,
            "length": ext.length,
            "paddr": ext.paddr,
            "type": ext.extent_type
        }

    def _dump_extents(self, cmd):
        dump = []
        for e in self.extents:
            dump.append({
                "offset": e.offset,
                "length": e.length,
                "paddr": e.paddr,
                "type": e.extent_type
            })
        return {
            "op": "DUMP_EXTENTS",
            "status": "SUCCESS",
            "extent_count": len(dump),
            "extents": dump
        }

    def run_trace(self, trace):
        results = []
        for cmd in trace:
            res = self.execute_command(cmd)
            results.append(res)
            
        summary = {
            "total_bytes_read": self.total_bytes_read,
            "total_bytes_written": self.total_bytes_written,
            "zero_filled_bytes": self.zero_filled_bytes,
            "bio_count": self.bio_count,
            "unwritten_conversions": self.unwritten_conversions,
            "aligned_io_count": self.aligned_io_count,
            "unaligned_rejects": self.unaligned_rejects,
            "final_extent_count": len(self.extents)
        }
        return {"events": results, "summary": summary}


def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    trace = data.get("trace", [])
    
    engine = IomapEngine(config)
    output = engine.run_trace(trace)
    print(json.dumps(output, separators=(',', ':'), ensure_ascii=False))


if __name__ == "__main__":
    solve()
