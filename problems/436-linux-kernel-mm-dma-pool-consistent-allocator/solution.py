# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #436 Solution:
Linux Kernel Device Drivers & Memory: mm/dmapool.c Consistent Small DMA Allocator Engine
(mm/dmapool.c, include/linux/dmapool.h, drivers/nvme/host/pci.c)
"""

import sys
import json

# Ensure UTF-8 streams on Windows
if sys.platform == "win32":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")


class DmaPoolPage:
    def __init__(self, page_id, page_size, dma_base, block_size, align):
        self.page_id = page_id
        self.page_size = page_size
        self.dma_base = dma_base
        self.block_size = block_size
        self.align = align
        
        self.free_offsets = []
        offset = 0
        while offset + block_size <= page_size:
            if offset % align == 0:
                self.free_offsets.append(offset)
                offset += block_size
            else:
                offset += (align - (offset % align))
                
        self.total_blocks = len(self.free_offsets)
        self.in_use = 0


class DmaPoolEngine:
    def __init__(self, config):
        self.pool_name = config.get("name", "nvme_desc_pool")
        self.block_size = config.get("block_size", 64)
        self.align = config.get("align", 64)
        self.page_size = config.get("page_size", 4096)
        self.base_dma_start = config.get("base_dma_start", 0x10000000)
        
        self.pages = []
        self.next_page_id = 0
        self.allocations = {}
        
        self.total_allocs = 0
        self.total_frees = 0
        self.pages_allocated_count = 0
        self.pages_freed_count = 0

    def execute_command(self, cmd):
        op = cmd.get("op")
        if op == "DMA_POOL_ALLOC":
            return self._alloc(cmd)
        elif op == "DMA_POOL_FREE":
            return self._free(cmd)
        elif op == "GET_POOL_INFO":
            return self._get_info(cmd)
        else:
            return {"op": op, "status": "UNKNOWN_OP"}

    def _alloc(self, cmd):
        handle_id = cmd["handle_id"]
        if handle_id in self.allocations:
            return {"op": "DMA_POOL_ALLOC", "handle_id": handle_id, "status": "EEXIST_HANDLE_ALREADY_ALLOCATED"}

        target_page = None
        for p in self.pages:
            if len(p.free_offsets) > 0:
                target_page = p
                break

        page_allocated_new = False
        if not target_page:
            page_dma = self.base_dma_start + (self.next_page_id * self.page_size)
            target_page = DmaPoolPage(self.next_page_id, self.page_size, page_dma, self.block_size, self.align)
            self.pages.append(target_page)
            self.next_page_id += 1
            self.pages_allocated_count += 1
            page_allocated_new = True

        offset = target_page.free_offsets.pop(0)
        target_page.in_use += 1
        dma_addr = target_page.dma_base + offset
        
        self.allocations[handle_id] = (target_page.page_id, offset, dma_addr)
        self.total_allocs += 1

        return {
            "op": "DMA_POOL_ALLOC",
            "handle_id": handle_id,
            "status": "SUCCESS",
            "page_id": target_page.page_id,
            "offset": offset,
            "dma_addr": hex(dma_addr),
            "new_page_allocated": page_allocated_new,
            "page_in_use": target_page.in_use,
            "page_remaining": len(target_page.free_offsets)
        }

    def _free(self, cmd):
        handle_id = cmd["handle_id"]
        if handle_id not in self.allocations:
            return {"op": "DMA_POOL_FREE", "handle_id": handle_id, "status": "EINVAL_HANDLE_NOT_FOUND"}

        page_id, offset, dma_addr = self.allocations.pop(handle_id)
        self.total_frees += 1

        target_page = None
        for p in self.pages:
            if p.page_id == page_id:
                target_page = p
                break

        target_page.free_offsets.append(offset)
        target_page.in_use -= 1

        page_freed = False
        if target_page.in_use == 0 and len(self.pages) > 1:
            self.pages.remove(target_page)
            self.pages_freed_count += 1
            page_freed = True

        return {
            "op": "DMA_POOL_FREE",
            "handle_id": handle_id,
            "status": "SUCCESS",
            "page_id": page_id,
            "offset": offset,
            "coherent_page_freed": page_freed,
            "active_pages": len(self.pages)
        }

    def _get_info(self, cmd):
        return {
            "op": "GET_POOL_INFO",
            "pool_name": self.pool_name,
            "block_size": self.block_size,
            "align": self.align,
            "active_pages": len(self.pages),
            "allocated_blocks": len(self.allocations),
            "total_allocs": self.total_allocs,
            "total_frees": self.total_frees
        }

    def run_trace(self, trace):
        results = []
        for cmd in trace:
            res = self.execute_command(cmd)
            results.append(res)
            
        summary = {
            "total_allocs": self.total_allocs,
            "total_frees": self.total_frees,
            "pages_allocated_count": self.pages_allocated_count,
            "pages_freed_count": self.pages_freed_count,
            "active_pages": len(self.pages),
            "active_allocations": len(self.allocations),
            "memory_saved_bytes": (self.total_allocs * self.page_size) - (self.pages_allocated_count * self.page_size)
        }
        return {"events": results, "summary": summary}


def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    trace = data.get("trace", [])
    
    engine = DmaPoolEngine(config)
    output = engine.run_trace(trace)
    print(json.dumps(output, separators=(',', ':'), ensure_ascii=False))


if __name__ == "__main__":
    solve()
