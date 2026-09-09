"""
[Problem #161] JVM G1GC Humongous Allocation 파편화와 Old Gen 승격 실패(Promotion Failure)
Solution Implementation

이 모듈은 HotSpot JVM의 Garbage-First (G1) 가비지 컬렉터의 메모리 할당,
Humongous Region 판정, Concurrent Marking Cycle (IHOP), Young GC 및 To-space Exhausted,
Full GC Stop-The-World (STW) 압축 메커니즘을 정밀 시뮬레이션합니다.
"""

import math
from typing import Any, Dict, List, Optional


class G1GCSimulator:
    """HotSpot G1GC 메모리 관리 및 가비지 컬렉션 시뮬레이터."""

    def __init__(
        self,
        heap_size_mb: int,
        config: Dict[str, Any],
        initial_regions: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self.heap_size_mb = heap_size_mb
        self.region_size_mb = config.get("region_size_mb", 1)
        self.total_regions = self.heap_size_mb // self.region_size_mb
        self.region_size_bytes = self.region_size_mb * 1024 * 1024
        
        # Humongous 임계값: 리전 크기의 50%
        self.humongous_threshold = self.region_size_bytes // 2
        
        self.ihop_percent = config.get("ihop_percent", 45)
        self.max_young_percent = config.get("max_young_percent", 30)
        self.max_eden_regions = max(1, int(self.total_regions * (self.max_young_percent / 100.0)))
        self.max_tenuring_threshold = config.get("max_tenuring_threshold", 5)
        self.streaming_chunk_size_kb = config.get("streaming_chunk_size_kb", 0)
        
        # 리전 테이블: None은 FREE 리전
        self.regions: List[Optional[Dict[str, Any]]] = [None] * self.total_regions
        self.current_eden_idx: Optional[int] = None
        
        # 초기 리전 상태 주입 (단편화 및 올드젠 포화 시나리오 재현용)
        if initial_regions:
            for ir in initial_regions:
                idx = ir["region_index"]
                self.regions[idx] = {
                    "type": ir["type"],
                    "objects": [dict(o) for o in ir.get("objects", [])],
                    "used_bytes": ir.get("used_bytes", 0),
                }
        
        # 수집 통계 지표
        self.young_gc_count = 0
        self.full_gc_count = 0
        self.humongous_alloc_count = 0
        self.humongous_waste_bytes = 0
        self.total_stw_pause_ms = 0.0
        self.max_stw_pause_ms = 0.0
        self.gc_cause_breakdown = {
            "HUMONGOUS_ALLOCATION_FAILURE": 0,
            "TO_SPACE_EXHAUSTED": 0,
            "CONCURRENT_MODE_FAILURE": 0,
        }
        
        # Concurrent Mark 상태
        self.concurrent_mark_end_time: Optional[int] = None
        self.marking_duration_ms = config.get("marking_duration_ms", 100)
        self.current_time = 0

    def get_free_region_indices(self) -> List[int]:
        return [i for i, r in enumerate(self.regions) if r is None]

    def count_regions(self, r_type: str) -> int:
        return sum(1 for r in self.regions if r is not None and r["type"] == r_type)

    def get_old_gen_occupancy_ratio(self) -> float:
        old_count = sum(
            1 for r in self.regions if r is not None and r["type"] in ("OLD", "STARTS_HUM", "CONT_HUM")
        )
        return (old_count / self.total_regions) * 100.0

    def find_contiguous_free(self, count: int) -> int:
        """연속된 count개의 FREE 리전을 탐색하여 시작 인덱스를 반환. 없으면 -1 반환."""
        run = 0
        start = -1
        for i in range(self.total_regions):
            if self.regions[i] is None:
                if run == 0:
                    start = i
                run += 1
                if run == count:
                    return start
            else:
                run = 0
                start = -1
        return -1

    def trigger_full_gc(self, cause: str, time_ms: int) -> None:
        """전체 힙 대상 Stop-The-World Full GC 및 힙 인플레이스 압축(Compaction) 수행."""
        self.full_gc_count += 1
        self.gc_cause_breakdown[cause] += 1
        
        # 1. 힙 전체에서 살아있는 유효 객체 수집
        surviving_objects = []
        total_live_bytes = 0
        for r in self.regions:
            if r is not None:
                for obj in r.get("objects", []):
                    if obj["expiry_time"] > time_ms:
                        surviving_objects.append(obj)
                        total_live_bytes += obj["size_bytes"]
                        
        # 2. STW 정지 시간 산출: 기본 2,000ms + 활성 데이터 MB당 10ms
        live_mb = total_live_bytes / (1024 * 1024)
        stw = 2000.0 + (live_mb * 10.0)
        self.total_stw_pause_ms += stw
        if stw > self.max_stw_pause_ms:
            self.max_stw_pause_ms = stw
            
        # 3. 힙 초기화 및 생존 객체 조밀 압축 (Old 리전에 밀집 배치)
        self.regions = [None] * self.total_regions
        self.current_eden_idx = None
        self.concurrent_mark_end_time = None
        
        reg_idx = 0
        curr_offset = 0
        curr_objs = []
        
        for obj in surviving_objects:
            if obj["size_bytes"] >= self.humongous_threshold:
                if curr_objs:
                    self.regions[reg_idx] = {
                        "type": "OLD",
                        "objects": curr_objs,
                        "used_bytes": curr_offset,
                    }
                    reg_idx += 1
                    curr_offset = 0
                    curr_objs = []
                req = math.ceil(obj["size_bytes"] / self.region_size_bytes)
                for k in range(req):
                    self.regions[reg_idx + k] = {
                        "type": "STARTS_HUM" if k == 0 else "CONT_HUM",
                        "objects": [obj] if k == 0 else [],
                        "used_bytes": obj["size_bytes"] if k == 0 else 0,
                    }
                reg_idx += req
            else:
                if curr_offset + obj["size_bytes"] <= self.region_size_bytes:
                    curr_objs.append(obj)
                    curr_offset += obj["size_bytes"]
                else:
                    if curr_objs:
                        self.regions[reg_idx] = {
                            "type": "OLD",
                            "objects": curr_objs,
                            "used_bytes": curr_offset,
                        }
                        reg_idx += 1
                    curr_objs = [obj]
                    curr_offset = obj["size_bytes"]
                    
        if curr_objs:
            self.regions[reg_idx] = {
                "type": "OLD",
                "objects": curr_objs,
                "used_bytes": curr_offset,
            }
            reg_idx += 1

    def trigger_young_gc(self, time_ms: int) -> None:
        """Eden 및 Survivor 영역 대상 Young GC(Minor GC) 및 Eager Reclaim 수행."""
        self.young_gc_count += 1
        
        # 1. 만료된 Humongous 객체 조기 회수 (Eager Reclaim)
        for i, r in enumerate(self.regions):
            if r is not None and r["type"] == "STARTS_HUM":
                obj = r["objects"][0]
                if obj["expiry_time"] <= time_ms:
                    req = math.ceil(obj["size_bytes"] / self.region_size_bytes)
                    for k in range(req):
                        self.regions[i + k] = None
                        
        # 2. Eden/Survivor 객체 대피(Evacuation)
        surviving_young = []
        live_bytes = 0
        for i, r in enumerate(self.regions):
            if r is not None and r["type"] in ("EDEN", "SURVIVOR"):
                for obj in r.get("objects", []):
                    if obj["expiry_time"] > time_ms:
                        obj["age"] += 1
                        surviving_young.append(obj)
                        live_bytes += obj["size_bytes"]
                self.regions[i] = None
        self.current_eden_idx = None
        
        # 3. Young GC STW 정지 시간: 기본 5ms + 대피 MB당 1ms
        live_mb = live_bytes / (1024 * 1024)
        stw = 5.0 + (live_mb * 1.0)
        self.total_stw_pause_ms += stw
        if stw > self.max_stw_pause_ms:
            self.max_stw_pause_ms = stw
            
        # 4. 생존 객체 Survivor 또는 Old 리전으로 승격(Promotion)
        for obj in surviving_young:
            target_type = "OLD" if obj["age"] >= self.max_tenuring_threshold else "SURVIVOR"
            placed = False
            for r in self.regions:
                if r is not None and r["type"] == target_type:
                    if r["used_bytes"] + obj["size_bytes"] <= self.region_size_bytes:
                        r["objects"].append(obj)
                        r["used_bytes"] += obj["size_bytes"]
                        placed = True
                        break
            if not placed:
                free_indices = self.get_free_region_indices()
                if not free_indices:
                    # 빈 리전 부족으로 인한 승격 실패 (TO_SPACE_EXHAUSTED)
                    self.trigger_full_gc("TO_SPACE_EXHAUSTED", time_ms)
                    return
                new_idx = free_indices[0]
                self.regions[new_idx] = {
                    "type": target_type,
                    "objects": [obj],
                    "used_bytes": obj["size_bytes"],
                }
                
        # 5. IHOP 임계치 도달 여부 확인 후 백그라운드 마킹 시작
        if self.concurrent_mark_end_time is None:
            if self.get_old_gen_occupancy_ratio() >= self.ihop_percent:
                self.concurrent_mark_end_time = time_ms + self.marking_duration_ms

    def check_concurrent_mark(self, time_ms: int) -> None:
        """백그라운드 마킹 완료 시 Mixed GC를 통해 무효화된 Old 리전 반환."""
        if self.concurrent_mark_end_time is not None and time_ms >= self.concurrent_mark_end_time:
            self.concurrent_mark_end_time = None
            for i, r in enumerate(self.regions):
                if r is not None and r["type"] == "OLD":
                    alive_objs = [o for o in r["objects"] if o["expiry_time"] > time_ms]
                    if not alive_objs:
                        self.regions[i] = None
                    else:
                        r["objects"] = alive_objs
                        r["used_bytes"] = sum(o["size_bytes"] for o in alive_objs)

    def allocate(self, req_id: str, time_ms: int, size_bytes: int, lifetime_ms: int) -> None:
        """메모리 할당 요청 처리 (스트리밍 청킹 여부 분기)."""
        self.current_time = time_ms
        self.check_concurrent_mark(time_ms)
        
        if self.streaming_chunk_size_kb > 0:
            chunk_bytes = self.streaming_chunk_size_kb * 1024
            remaining = size_bytes
            idx = 0
            while remaining > 0:
                c_size = min(remaining, chunk_bytes)
                self._allocate_single(f"{req_id}_c{idx}", time_ms, c_size, lifetime_ms)
                remaining -= c_size
                idx += 1
        else:
            self._allocate_single(req_id, time_ms, size_bytes, lifetime_ms)

    def _allocate_single(self, req_id: str, time_ms: int, size_bytes: int, lifetime_ms: int) -> None:
        obj = {
            "id": req_id,
            "size_bytes": size_bytes,
            "created_time": time_ms,
            "expiry_time": time_ms + lifetime_ms,
            "age": 0,
        }
        
        # Humongous 객체 판정 (크기 >= 리전 크기의 50%)
        if size_bytes >= self.humongous_threshold:
            self.humongous_alloc_count += 1
            req_regions = math.ceil(size_bytes / self.region_size_bytes)
            waste = (req_regions * self.region_size_bytes) - size_bytes
            self.humongous_waste_bytes += waste
            
            # 마킹 중 올드젠 고갈 시 Concurrent Mode Failure
            if self.concurrent_mark_end_time is not None:
                if len(self.get_free_region_indices()) < req_regions:
                    self.trigger_full_gc("CONCURRENT_MODE_FAILURE", time_ms)
                    
            # 연속된 빈 리전 탐색
            start_idx = self.find_contiguous_free(req_regions)
            if start_idx == -1:
                # 단편화로 인한 연속 리전 획득 실패 -> Full GC 긴급 압축
                self.trigger_full_gc("HUMONGOUS_ALLOCATION_FAILURE", time_ms)
                start_idx = self.find_contiguous_free(req_regions)
                if start_idx == -1:
                    raise MemoryError(f"OOM: Cannot allocate {size_bytes} bytes even after Full GC")
                    
            for k in range(req_regions):
                self.regions[start_idx + k] = {
                    "type": "STARTS_HUM" if k == 0 else "CONT_HUM",
                    "objects": [obj] if k == 0 else [],
                    "used_bytes": size_bytes if k == 0 else 0,
                }
                
            if self.concurrent_mark_end_time is None:
                if self.get_old_gen_occupancy_ratio() >= self.ihop_percent:
                    self.concurrent_mark_end_time = time_ms + self.marking_duration_ms
            return

        # 일반 객체: Eden 영역 할당
        allocated = False
        if self.current_eden_idx is not None:
            r = self.regions[self.current_eden_idx]
            if r["used_bytes"] + size_bytes <= self.region_size_bytes:
                r["objects"].append(obj)
                r["used_bytes"] += size_bytes
                allocated = True
                
        if not allocated:
            eden_count = self.count_regions("EDEN")
            free_indices = self.get_free_region_indices()
            if eden_count < self.max_eden_regions and free_indices:
                new_eden_idx = free_indices[0]
                self.regions[new_eden_idx] = {
                    "type": "EDEN",
                    "objects": [obj],
                    "used_bytes": size_bytes,
                }
                self.current_eden_idx = new_eden_idx
                allocated = True
            else:
                # Eden 가득 참 또는 빈 리전 부족 -> Young GC 트리거
                self.trigger_young_gc(time_ms)
                free_indices = self.get_free_region_indices()
                if free_indices:
                    new_eden_idx = free_indices[0]
                    self.regions[new_eden_idx] = {
                        "type": "EDEN",
                        "objects": [obj],
                        "used_bytes": size_bytes,
                    }
                    self.current_eden_idx = new_eden_idx
                    allocated = True
                else:
                    self.trigger_full_gc("TO_SPACE_EXHAUSTED", time_ms)
                    free_indices = self.get_free_region_indices()
                    new_eden_idx = free_indices[0]
                    self.regions[new_eden_idx] = {
                        "type": "EDEN",
                        "objects": [obj],
                        "used_bytes": size_bytes,
                    }
                    self.current_eden_idx = new_eden_idx
                    allocated = True

    def get_summary(self) -> Dict[str, Any]:
        used_regions = sum(1 for r in self.regions if r is not None)
        hum_regions = sum(
            1 for r in self.regions if r is not None and r["type"] in ("STARTS_HUM", "CONT_HUM")
        )
        free_regions = self.total_regions - used_regions
        return {
            "young_gc_count": self.young_gc_count,
            "full_gc_count": self.full_gc_count,
            "humongous_allocation_count": self.humongous_alloc_count,
            "humongous_waste_bytes": self.humongous_waste_bytes,
            "total_stw_pause_ms": round(self.total_stw_pause_ms, 2),
            "max_stw_pause_ms": round(self.max_stw_pause_ms, 2),
            "gc_cause_breakdown": self.gc_cause_breakdown,
            "final_heap_status": {
                "total_regions": self.total_regions,
                "used_regions": used_regions,
                "humongous_regions": hum_regions,
                "free_regions": free_regions,
            },
        }


def solve(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """ZeliJudge Problem #161 solve 진입점."""
    sim = G1GCSimulator(
        heap_size_mb=input_data["heap_size_mb"],
        config=input_data.get("config", {}),
        initial_regions=input_data.get("initial_regions"),
    )
    for req in input_data.get("workload", []):
        sim.allocate(
            req_id=req["id"],
            time_ms=req["time_ms"],
            size_bytes=req["size_bytes"],
            lifetime_ms=req["lifetime_ms"],
        )
    return sim.get_summary()


if __name__ == "__main__":
    import json
    import sys

    raw = sys.stdin.read().strip()
    if raw:
        inp = json.loads(raw)
        out = solve(inp)
        print(json.dumps(out, indent=2))
