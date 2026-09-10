# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #403 Solution:
Linux Kernel Storage: Page Cache Folio Readahead Engine
"""
import sys
import json

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class ReadaheadEngine:
    def __init__(self, config):
        self.ra_max_pages = int(config.get("ra_max_pages", 32))
        self.ra_min_pages = int(config.get("ra_min_pages", 4))
        self.page_cache = set()
        self.ra_start = 0
        self.ra_size = 0
        self.async_size = 0
        self.prev_pos = -1

        self.current_tick = 0
        self.stats = {
            "sync_reads": 0,
            "async_readaheads": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "io_pages_submitted": 0,
            "random_seeks": 0
        }

    def submit_io(self, start_page, nr_pages, is_async=False):
        for p in range(start_page, start_page + nr_pages):
            self.page_cache.add(p)
        self.stats["io_pages_submitted"] += nr_pages
        if is_async:
            self.stats["async_readaheads"] += 1
        else:
            self.stats["sync_reads"] += 1

    def read_page(self, page_index):
        self.current_tick += 1
        is_hit = page_index in self.page_cache
        if is_hit:
            self.stats["cache_hits"] += 1
        else:
            self.stats["cache_misses"] += 1

        is_seq = (self.prev_pos != -1 and page_index == self.prev_pos + 1) or (self.prev_pos == -1 and page_index == 0)

        if not is_hit:
            if is_seq:
                if self.ra_size == 0:
                    new_size = self.ra_min_pages
                else:
                    new_size = min(self.ra_size * 2, self.ra_max_pages)
                self.ra_start = page_index
                self.ra_size = new_size
                self.async_size = self.ra_size // 2
                self.submit_io(self.ra_start, self.ra_size, is_async=False)
            else:
                self.stats["random_seeks"] += 1
                self.ra_start = page_index
                self.ra_size = 1
                self.async_size = 0
                self.submit_io(page_index, 1, is_async=False)
        else:
            async_mark = self.ra_start + self.ra_size - self.async_size
            if self.async_size > 0 and page_index == async_mark:
                next_start = self.ra_start + self.ra_size
                next_size = min(self.ra_size * 2, self.ra_max_pages)
                next_async = next_size // 2
                self.submit_io(next_start, next_size, is_async=True)
                self.ra_start = next_start
                self.ra_size = next_size
                self.async_size = next_async

        self.prev_pos = page_index
        return {
            "page_index": page_index,
            "cache_hit": is_hit,
            "ra_window": {"start": self.ra_start, "size": self.ra_size, "async_size": self.async_size}
        }

    def run_simulation(self, page_reads):
        results = []
        for p in page_reads:
            res = self.read_page(p)
            results.append(res)

        return self.get_summary(results)

    def get_summary(self, read_results=None):
        return {
            "stats": self.stats,
            "cached_pages_count": len(self.page_cache),
            "final_ra_window": {
                "start": self.ra_start,
                "size": self.ra_size,
                "async_size": self.async_size
            },
            "read_results": read_results or []
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    page_reads = data.get("page_reads", [])
    engine = ReadaheadEngine(config)
    res = engine.run_simulation(page_reads)
    print(json.dumps(res, separators=(",", ":"), ensure_ascii=False))

if __name__ == "__main__":
    main()
