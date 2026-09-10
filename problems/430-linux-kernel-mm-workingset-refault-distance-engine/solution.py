# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #430 Solution:
Linux Kernel Memory Management: Page Cache Shadow Entries, Refault Distance & Working Set Detection Engine
(mm/workingset.c, mm/filemap.c, include/linux/swap.h, CONFIG_MEMCG)
"""

import sys
import json

# Ensure UTF-8 streams on Windows
if sys.platform == "win32":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")


class WorkingSetEngine:
    def __init__(self, config):
        self.max_memory_pages = config.get("max_memory_pages", 100)
        self.thrashing_threshold = config.get("thrashing_threshold", 0.5)
        self.default_slack_margin = config.get("default_slack_margin", 10)
        
        # State
        self.active_file_pages = 0
        self.inactive_file_pages = 0
        self.eviction_counter = 0
        
        # Stats
        self.workingset_refaults = 0
        self.workingset_activations = 0
        self.total_allocs = 0
        self.total_evictions = 0
        self.shadow_pruned_count = 0
        self.thrashing_events = 0
        
        # Storage:
        # xarray: (inode_id, offset) -> entry
        self.xarray = {}
        # page_id -> (inode_id, offset)
        self.page_lookup = {}
        
        # LRU queues
        self.active_lru = []
        self.inactive_lru = []

    def execute_command(self, cmd):
        op = cmd.get("op")
        
        if op == "ALLOC_PAGE":
            return self._alloc_page(cmd)
        elif op == "ACCESS_PAGE":
            return self._access_page(cmd)
        elif op == "EVICT_PAGE":
            return self._evict_page(cmd)
        elif op == "BALANCE_LRU":
            return self._balance_lru(cmd)
        elif op == "SHADOW_PRUNE":
            return self._shadow_prune(cmd)
        elif op == "EVALUATE_THRASHING":
            return self._evaluate_thrashing(cmd)
        else:
            return {"op": op, "status": "UNKNOWN_OP"}

    def _alloc_page(self, cmd):
        self.total_allocs += 1
        page_id = cmd["page_id"]
        inode_id = cmd["inode_id"]
        offset = cmd["offset"]
        memcg_id = cmd.get("memcg_id", 0)
        
        key = (inode_id, offset)
        existing = self.xarray.get(key)
        
        refault_occurred = False
        refault_dist = None
        status = ""
        
        if existing and existing["type"] == "SHADOW":
            refault_occurred = True
            self.workingset_refaults += 1
            eviction_ts = existing["eviction_timestamp"]
            refault_dist = self.eviction_counter - eviction_ts
            
            # Linux workingset logic:
            # refault_distance <= active_file_pages -> Part of working set!
            if refault_dist <= self.active_file_pages:
                self.workingset_activations += 1
                status = "WORKINGSET_REFAULT_ACTIVATE"
                lru_target = "ACTIVE"
                self.active_file_pages += 1
                self.active_lru.append(page_id)
            else:
                status = "INACTIVE_REFAULT_INSERT"
                lru_target = "INACTIVE"
                self.inactive_file_pages += 1
                self.inactive_lru.append(page_id)
        else:
            # Fresh insertion
            status = "FRESH_PAGE_INSERT"
            lru_target = "INACTIVE"
            self.inactive_file_pages += 1
            self.inactive_lru.append(page_id)
            
        new_entry = {
            "type": "PRESENT",
            "page_id": page_id,
            "lru": lru_target,
            "referenced": False,
            "memcg_id": memcg_id,
            "inode_id": inode_id,
            "offset": offset
        }
        self.xarray[key] = new_entry
        self.page_lookup[page_id] = key
        
        return {
            "op": "ALLOC_PAGE",
            "page_id": page_id,
            "status": status,
            "lru": lru_target,
            "refault_occurred": refault_occurred,
            "refault_distance": refault_dist,
            "active_pages": self.active_file_pages,
            "inactive_pages": self.inactive_file_pages
        }

    def _access_page(self, cmd):
        page_id = cmd["page_id"]
        key = self.page_lookup.get(page_id)
        
        if not key or key not in self.xarray:
            return {"op": "ACCESS_PAGE", "page_id": page_id, "status": "PAGE_NOT_FOUND"}
            
        entry = self.xarray[key]
        if entry["type"] != "PRESENT":
            return {"op": "ACCESS_PAGE", "page_id": page_id, "status": "PAGE_NOT_PRESENT"}
            
        if entry["lru"] == "ACTIVE":
            entry["referenced"] = True
            if page_id in self.active_lru:
                self.active_lru.remove(page_id)
                self.active_lru.append(page_id)
            return {
                "op": "ACCESS_PAGE",
                "page_id": page_id,
                "status": "ACTIVE_REFERENCED_HIT",
                "lru": "ACTIVE"
            }
        else:
            if not entry["referenced"]:
                entry["referenced"] = True
                if page_id in self.inactive_lru:
                    self.inactive_lru.remove(page_id)
                    self.inactive_lru.append(page_id)
                return {
                    "op": "ACCESS_PAGE",
                    "page_id": page_id,
                    "status": "INACTIVE_REFERENCED_MARKED",
                    "lru": "INACTIVE"
                }
            else:
                entry["referenced"] = False
                entry["lru"] = "ACTIVE"
                if page_id in self.inactive_lru:
                    self.inactive_lru.remove(page_id)
                self.active_lru.append(page_id)
                self.inactive_file_pages -= 1
                self.active_file_pages += 1
                return {
                    "op": "ACCESS_PAGE",
                    "page_id": page_id,
                    "status": "SECOND_CHANCE_PROMOTED_ACTIVE",
                    "lru": "ACTIVE",
                    "active_pages": self.active_file_pages,
                    "inactive_pages": self.inactive_file_pages
                }

    def _evict_page(self, cmd):
        page_id = cmd.get("page_id")
        if not page_id:
            if self.inactive_lru:
                page_id = self.inactive_lru[0]
            elif self.active_lru:
                page_id = self.active_lru[0]
            else:
                return {"op": "EVICT_PAGE", "status": "NO_PAGES_TO_EVICT"}
                
        key = self.page_lookup.get(page_id)
        if not key or key not in self.xarray:
            return {"op": "EVICT_PAGE", "page_id": page_id, "status": "PAGE_NOT_FOUND"}
            
        entry = self.xarray[key]
        if entry["type"] != "PRESENT":
            return {"op": "EVICT_PAGE", "page_id": page_id, "status": "PAGE_ALREADY_EVICTED"}
            
        self.eviction_counter += 1
        self.total_evictions += 1
        eviction_ts = self.eviction_counter
        
        lru_origin = entry["lru"]
        if lru_origin == "ACTIVE":
            self.active_file_pages -= 1
            if page_id in self.active_lru:
                self.active_lru.remove(page_id)
        else:
            self.inactive_file_pages -= 1
            if page_id in self.inactive_lru:
                self.inactive_lru.remove(page_id)
                
        shadow_entry = {
            "type": "SHADOW",
            "eviction_timestamp": eviction_ts,
            "memcg_id": entry["memcg_id"],
            "inode_id": entry["inode_id"],
            "offset": entry["offset"]
        }
        self.xarray[key] = shadow_entry
        del self.page_lookup[page_id]
        
        return {
            "op": "EVICT_PAGE",
            "page_id": page_id,
            "status": "PAGE_EVICTED_SHADOW_STORED",
            "eviction_timestamp": eviction_ts,
            "origin_lru": lru_origin,
            "active_pages": self.active_file_pages,
            "inactive_pages": self.inactive_file_pages
        }

    def _balance_lru(self, cmd):
        target_inactive_ratio = cmd.get("target_inactive_ratio", 0.5)
        target_min_inactive = int(self.active_file_pages * target_inactive_ratio)
        demoted = []
        
        while self.inactive_file_pages < target_min_inactive and self.active_lru:
            demote_pid = self.active_lru.pop(0)
            key = self.page_lookup[demote_pid]
            entry = self.xarray[key]
            entry["lru"] = "INACTIVE"
            entry["referenced"] = False
            self.inactive_lru.insert(0, demote_pid)
            self.active_file_pages -= 1
            self.inactive_file_pages += 1
            demoted.append(demote_pid)
            
        if demoted:
            status = "LRU_BALANCED_DEMOTION"
        else:
            status = "LRU_ALREADY_BALANCED"
            
        return {
            "op": "BALANCE_LRU",
            "status": status,
            "demoted_count": len(demoted),
            "demoted_pages": demoted,
            "active_pages": self.active_file_pages,
            "inactive_pages": self.inactive_file_pages
        }

    def _shadow_prune(self, cmd):
        max_age_margin = cmd.get("max_age_margin", self.default_slack_margin)
        threshold_dist = self.inactive_file_pages + self.active_file_pages + max_age_margin
        
        pruned_keys = []
        for key, entry in list(self.xarray.items()):
            if entry["type"] == "SHADOW":
                dist = self.eviction_counter - entry["eviction_timestamp"]
                if dist > threshold_dist:
                    pruned_keys.append(key)
                    del self.xarray[key]
                    
        self.shadow_pruned_count += len(pruned_keys)
        return {
            "op": "SHADOW_PRUNE",
            "status": "SHADOW_ENTRIES_PRUNED",
            "pruned_count": len(pruned_keys),
            "remaining_shadows": sum(1 for e in self.xarray.values() if e["type"] == "SHADOW")
        }

    def _evaluate_thrashing(self, cmd):
        ratio = round(self.workingset_activations / max(1, self.total_evictions), 4)
        is_thrashing = ratio >= self.thrashing_threshold
        
        if is_thrashing:
            self.thrashing_events += 1
            recommendation = "EXPAND_CGROUP_MEMORY"
        else:
            recommendation = "STEADY_STATE_NO_ACTION"
            
        return {
            "op": "EVALUATE_THRASHING",
            "status": "THRASHING_EVALUATED",
            "thrashing_detected": is_thrashing,
            "refault_activation_ratio": ratio,
            "threshold": self.thrashing_threshold,
            "recommendation": recommendation
        }

    def run_trace(self, trace):
        results = []
        for cmd in trace:
            res = self.execute_command(cmd)
            results.append(res)
            
        summary = {
            "total_allocs": self.total_allocs,
            "total_evictions": self.total_evictions,
            "workingset_refaults": self.workingset_refaults,
            "workingset_activations": self.workingset_activations,
            "shadow_pruned_count": self.shadow_pruned_count,
            "active_pages": self.active_file_pages,
            "inactive_pages": self.inactive_file_pages,
            "eviction_counter": self.eviction_counter,
            "thrashing_events": self.thrashing_events
        }
        return {"events": results, "summary": summary}


def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    trace = data.get("trace", [])
    
    engine = WorkingSetEngine(config)
    output = engine.run_trace(trace)
    print(json.dumps(output, separators=(',', ':'), ensure_ascii=False))


if __name__ == "__main__":
    solve()
