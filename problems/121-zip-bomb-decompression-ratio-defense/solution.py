import sys
import json
import os

class SafeDecompressor:
    def __init__(self):
        self.reset()

    def reset(self):
        self.max_uncompressed_mb = 100
        self.max_ratio = 100
        self.max_file_count = 1000
        self.max_depth = 2

        self.processed = 0
        self.extracted = 0
        self.rejected_zip_bomb = 0
        self.rejected_zip_slip = 0

    def config(self, max_uncompressed_mb=None, max_ratio=None, max_file_count=None, max_depth=None):
        if max_uncompressed_mb is not None:
            self.max_uncompressed_mb = int(max_uncompressed_mb)
        if max_ratio is not None:
            self.max_ratio = int(max_ratio)
        if max_file_count is not None:
            self.max_file_count = int(max_file_count)
        if max_depth is not None:
            self.max_depth = int(max_depth)
        return f"OK max_uncompressed_mb={self.max_uncompressed_mb} max_ratio={self.max_ratio} max_file_count={self.max_file_count} max_depth={self.max_depth}"

    def is_zip_slip(self, path):
        # Check absolute path or directory traversal
        norm = os.path.normpath(path)
        if norm.startswith('..') or norm.startswith('/') or norm.startswith('\\') or '..' in norm.split(os.sep):
            return True
        # also check raw separators
        parts = path.replace('\\', '/').split('/')
        if '..' in parts or path.startswith('/'):
            return True
        return False

    def decompress(self, archive_name, compressed_bytes, entries_json, depth=1):
        self.processed += 1
        compressed_bytes = int(compressed_bytes)
        depth = int(depth)

        # 1. Depth check
        if depth > self.max_depth:
            self.rejected_zip_bomb += 1
            return f"ERROR archive={archive_name} status=REJECTED error=ZIP_BOMB_DETECTED reason=MAX_DEPTH_EXCEEDED depth={depth}"

        try:
            entries = json.loads(entries_json)
        except Exception:
            entries = []

        total_files = len(entries)

        # 2. File count check
        if total_files > self.max_file_count:
            self.rejected_zip_bomb += 1
            return f"ERROR archive={archive_name} status=REJECTED error=ZIP_BOMB_DETECTED reason=MAX_FILE_COUNT_EXCEEDED count={total_files}"

        total_uncompressed_bytes = 0
        max_bytes_limit = self.max_uncompressed_mb * 1024 * 1024

        for entry in entries:
            name = entry.get("name", "")
            size = entry.get("size", 0)
            csize = entry.get("csize", 0)
            is_zip = entry.get("is_zip", False)

            # 3. Zip Slip check
            if self.is_zip_slip(name):
                self.rejected_zip_slip += 1
                return f"ERROR archive={archive_name} status=REJECTED error=ZIP_SLIP_DETECTED filename={name}"

            # 4. Excessive Ratio check
            if csize > 0:
                ratio = size / csize
                if ratio > self.max_ratio:
                    self.rejected_zip_bomb += 1
                    return f"ERROR archive={archive_name} status=REJECTED error=ZIP_BOMB_DETECTED reason=EXCESSIVE_RATIO ratio={ratio:.1f} limit={self.max_ratio}"

            # 5. Total Size limit check
            total_uncompressed_bytes += size
            if total_uncompressed_bytes > max_bytes_limit:
                self.rejected_zip_bomb += 1
                total_mb = total_uncompressed_bytes / (1024 * 1024)
                return f"ERROR archive={archive_name} status=REJECTED error=ZIP_BOMB_DETECTED reason=MAX_SIZE_EXCEEDED total_mb={total_mb:.1f} limit_mb={self.max_uncompressed_mb}"

            # 6. Nested Zip recursion
            if is_zip:
                sub_entries_json = json.dumps(entry.get("sub_entries", []))
                sub_csize = entry.get("csize", 0)
                sub_res = self.decompress(name, sub_csize, sub_entries_json, depth=depth + 1)
                if sub_res.startswith("ERROR"):
                    # Propagate inner error directly (processed count already updated)
                    self.processed -= 1 # adjust outer double-counting
                    return sub_res

        self.extracted += 1
        overall_ratio = total_uncompressed_bytes / max(1, compressed_bytes)
        return f"SUCCESS archive={archive_name} status=EXTRACTED files={total_files} total_bytes={total_uncompressed_bytes} compression_ratio={overall_ratio:.1f}"

    def stats(self):
        return f"STATS processed={self.processed} extracted={self.extracted} rejected_zip_bomb={self.rejected_zip_bomb} rejected_zip_slip={self.rejected_zip_slip}"

def main():
    sim = SafeDecompressor()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        parts = line.split(maxsplit=1)
        cmd = parts[0]
        rest = parts[1] if len(parts) > 1 else ""

        if cmd == "CONFIG":
            params = {}
            for p in rest.split():
                if '=' in p:
                    k, v = p.split('=', 1)
                    params[k] = v
            print(sim.config(
                max_uncompressed_mb=params.get('max_uncompressed_mb'),
                max_ratio=params.get('max_ratio'),
                max_file_count=params.get('max_file_count'),
                max_depth=params.get('max_depth')
            ))

        elif cmd == "DECOMPRESS":
            # parse archive=..., compressed_bytes=..., depth=..., entries=...
            # Note: entries might be json with spaces, e.g. entries=[{"name": ...}]
            archive = ""
            compressed_bytes = 0
            depth = 1
            entries_json = "[]"

            if "entries=" in rest:
                idx = rest.index("entries=")
                entries_json = rest[idx + len("entries="):]
                prefix = rest[:idx].strip()
            else:
                prefix = rest

            for p in prefix.split():
                if p.startswith("archive="):
                    archive = p[len("archive="):]
                elif p.startswith("compressed_bytes="):
                    compressed_bytes = int(p[len("compressed_bytes="):])
                elif p.startswith("depth="):
                    depth = int(p[len("depth="):])

            print(sim.decompress(
                archive_name=archive,
                compressed_bytes=compressed_bytes,
                entries_json=entries_json,
                depth=depth
            ))

        elif cmd == "STATS":
            print(sim.stats())

        elif cmd == "RESET":
            sim.reset()
            print("OK max_uncompressed_mb=100 max_ratio=100 max_file_count=1000 max_depth=2")

if __name__ == '__main__':
    main()
