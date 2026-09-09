"""
[Problem #163] BGP Anycast 라우팅과 Maglev 일관된 해싱: ECMP 패킷 리셔플링과 TCP RST 폭발 참사
Solution Implementation

이 모듈은 Google Maglev(NSDI '16) 논문 기반의 일관된 해싱(Consistent Hashing) 알고리즘과
BGP Anycast ECMP 라우팅 환경에서의 L4 로드 밸런서(Director) 장애 조치 및 무중단 스케일아웃을 정밀 시뮬레이션합니다.
"""

import hashlib
import json
import sys
from typing import Any, Dict, List, Optional


def hash_32(val: str, seed: int = 0) -> int:
    """결정론적 32비트 정수 해시 함수."""
    h = hashlib.sha256(f"{seed}:{val}".encode("utf-8")).hexdigest()
    return int(h[:8], 16)


class MaglevTable:
    """Google Maglev 논문 기반 일관된 해시 룩업 테이블 ($M$ 슬롯)."""

    def __init__(self, backends: List[str], M: int = 997):
        self.M = M
        self.backends = list(backends)
        self.table = self._build()

    def _build(self) -> List[str]:
        N = len(self.backends)
        if N == 0:
            return []
        
        # 1. 각 백엔드별 결정론적 순열(Permutation) 생성
        permutations = {}
        for b in self.backends:
            offset = hash_32(b, seed=1) % self.M
            skip = (hash_32(b, seed=2) % (self.M - 1)) + 1
            permutations[b] = [(offset + j * skip) % self.M for j in range(self.M)]
            
        # 2. 라운드로빈 방식으로 룩업 테이블 채우기
        entry: List[Optional[str]] = [None] * self.M
        next_idx = {b: 0 for b in self.backends}
        n_filled = 0
        
        while n_filled < self.M:
            for b in self.backends:
                while next_idx[b] < self.M:
                    c = permutations[b][next_idx[b]]
                    next_idx[b] += 1
                    if entry[c] is None:
                        entry[c] = b
                        n_filled += 1
                        break
        return [b for b in entry if b is not None]

    def lookup(self, flow_key: str) -> str:
        if not self.table:
            raise RuntimeError("No active backends in Maglev table")
        slot = hash_32(flow_key, seed=0) % self.M
        return self.table[slot]


class DirectorNode:
    """소프트웨어 L4 디렉터(로드 밸런서) 노드."""

    def __init__(self, node_id: str, director_type: str, M: int = 997, enable_conntrack: bool = True):
        self.node_id = node_id
        self.director_type = director_type
        self.enable_conntrack = enable_conntrack
        self.conntrack: Dict[str, str] = {}
        self.maglev_table: Optional[MaglevTable] = None
        self.backends: List[str] = []
        self.M = M
        self.rr_idx = 0

    def update_backends(self, backends: List[str]):
        self.backends = list(backends)
        if self.director_type == "MAGLEV":
            self.maglev_table = MaglevTable(self.backends, self.M)

    def route_packet(self, flow_key: str, packet_type: str) -> str:
        # 1. 로컬 커넥션 트래킹(Conntrack) 확인
        if self.enable_conntrack and flow_key in self.conntrack:
            assigned = self.conntrack[flow_key]
            if assigned in self.backends:
                if packet_type == "FIN":
                    del self.conntrack[flow_key]
                return assigned
            else:
                del self.conntrack[flow_key]
                
        # 2. Conntrack 미스 시 폴백 라우팅
        if self.director_type == "MAGLEV":
            assert self.maglev_table is not None
            backend = self.maglev_table.lookup(flow_key)
        elif self.director_type == "NAIVE_MODULO":
            if not self.backends:
                raise RuntimeError("No backends")
            idx = hash_32(flow_key, seed=0) % len(self.backends)
            backend = self.backends[idx]
        elif self.director_type == "ROUND_ROBIN":
            if not self.backends:
                raise RuntimeError("No backends")
            backend = self.backends[self.rr_idx % len(self.backends)]
            self.rr_idx += 1
        else:
            raise ValueError(f"Unknown director type: {self.director_type}")

        # Conntrack 등록 (FIN 제외)
        if self.enable_conntrack and packet_type != "FIN":
            self.conntrack[flow_key] = backend
            
        return backend


class BackendServer:
    """애플리케이션 백엔드 서버 (TCP 소켓 상태 관리)."""

    def __init__(self, server_id: str):
        self.server_id = server_id
        self.active_flows: Dict[str, str] = {}

    def handle_packet(self, flow_key: str, packet_type: str) -> Dict[str, Any]:
        if packet_type == "SYN":
            self.active_flows[flow_key] = "ESTABLISHED"
            return {"status": "SUCCESS_NEW_CONNECTION", "server_id": self.server_id}
        elif packet_type in ("DATA", "ACK"):
            if flow_key in self.active_flows:
                return {"status": "SUCCESS_DATA_PROCESSED", "server_id": self.server_id}
            else:
                # 미등록된 TCP 플로우로 인한 TCP RST 발생
                return {
                    "status": "TCP_RST_CONNECTION_SEVERED",
                    "server_id": self.server_id,
                    "error": f"Connection {flow_key} not found on {self.server_id}. TCP RST sent.",
                }
        elif packet_type == "FIN":
            if flow_key in self.active_flows:
                del self.active_flows[flow_key]
                return {"status": "SUCCESS_CLOSED", "server_id": self.server_id}
            else:
                return {
                    "status": "TCP_RST_CONNECTION_SEVERED",
                    "server_id": self.server_id,
                    "error": f"Connection {flow_key} not found on {self.server_id} during FIN.",
                }
        else:
            raise ValueError(f"Unknown packet type: {packet_type}")


class L4LoadBalancerCluster:
    """BGP Anycast ECMP 라우터 및 L4 디렉터 클러스터 통합 시뮬레이터."""

    def __init__(self, config: Dict[str, Any]):
        self.director_type = config.get("director_type", "MAGLEV")
        self.enable_conntrack = config.get("enable_conntrack", True)
        self.M = config.get("lookup_table_size", 997)
        self.directors: Dict[str, DirectorNode] = {}
        for d_id in config.get("directors", []):
            self.directors[d_id] = DirectorNode(d_id, self.director_type, self.M, self.enable_conntrack)
            
        self.backends: Dict[str, BackendServer] = {}
        for b_id in config.get("backends", []):
            self.backends[b_id] = BackendServer(b_id)
            
        active_b_list = list(self.backends.keys())
        for d in self.directors.values():
            d.update_backends(active_b_list)
            
        self.total_packets = 0
        self.success_packets = 0
        self.tcp_rst_count = 0
        self.conntrack_hits = 0
        self.conntrack_misses = 0
        self.director_hop_counts: Dict[str, int] = {d: 0 for d in self.directors}
        self.backend_packet_counts: Dict[str, int] = {b: 0 for b in self.backends}

    def ecmp_dispatch(self, flow_key: str) -> DirectorNode:
        """상위 BGP 라우터의 5-tuple 기반 ECMP 분배."""
        sorted_directors = sorted(self.directors.keys())
        if not sorted_directors:
            raise RuntimeError("No active directors")
        idx = hash_32(flow_key, seed=99) % len(sorted_directors)
        chosen_id = sorted_directors[idx]
        self.director_hop_counts[chosen_id] = self.director_hop_counts.get(chosen_id, 0) + 1
        return self.directors[chosen_id]

    def process_packet(self, packet: Dict[str, Any]) -> Dict[str, Any]:
        self.total_packets += 1
        flow_key = packet["flow_key"]
        p_type = packet["packet_type"]
        
        # 1. 상위 ECMP 라우터 디스패치
        director = self.ecmp_dispatch(flow_key)
        
        # Conntrack 적중률 통계
        if self.enable_conntrack:
            if flow_key in director.conntrack:
                self.conntrack_hits += 1
            else:
                self.conntrack_misses += 1
        else:
            self.conntrack_misses += 1
            
        # 2. 디렉터의 백엔드 라우팅
        assigned_backend_id = director.route_packet(flow_key, p_type)
        self.backend_packet_counts[assigned_backend_id] = (
            self.backend_packet_counts.get(assigned_backend_id, 0) + 1
        )
        
        # 3. 백엔드 패킷 처리 및 RST 감지
        backend = self.backends[assigned_backend_id]
        res = backend.handle_packet(flow_key, p_type)
        
        if res["status"] == "TCP_RST_CONNECTION_SEVERED":
            self.tcp_rst_count += 1
        else:
            self.success_packets += 1
            
        return {
            "flow_key": flow_key,
            "packet_type": p_type,
            "director_id": director.node_id,
            "backend_id": assigned_backend_id,
            "status": res["status"],
            "error": res.get("error"),
        }

    def handle_admin_event(self, event: Dict[str, Any]):
        action = event["action"]
        if action == "ADD_DIRECTOR":
            d_id = event["director_id"]
            node = DirectorNode(d_id, self.director_type, self.M, self.enable_conntrack)
            node.update_backends(list(self.backends.keys()))
            self.directors[d_id] = node
            self.director_hop_counts[d_id] = 0
        elif action == "REMOVE_DIRECTOR":
            d_id = event["director_id"]
            if d_id in self.directors:
                del self.directors[d_id]
        elif action == "ADD_BACKEND":
            b_id = event["backend_id"]
            self.backends[b_id] = BackendServer(b_id)
            self.backend_packet_counts[b_id] = 0
            active_b = list(self.backends.keys())
            for d in self.directors.values():
                d.update_backends(active_b)
        elif action == "REMOVE_BACKEND":
            b_id = event["backend_id"]
            if b_id in self.backends:
                del self.backends[b_id]
            active_b = list(self.backends.keys())
            for d in self.directors.values():
                d.update_backends(active_b)
        else:
            raise ValueError(f"Unknown admin action: {action}")

    def get_summary(self) -> Dict[str, Any]:
        return {
            "total_packets": self.total_packets,
            "success_packets": self.success_packets,
            "tcp_rst_count": self.tcp_rst_count,
            "rst_rate_percent": round((self.tcp_rst_count / max(1, self.total_packets)) * 100.0, 2),
            "conntrack_hits": self.conntrack_hits,
            "conntrack_misses": self.conntrack_misses,
            "active_directors": len(self.directors),
            "active_backends": len(self.backends),
            "backend_packet_distribution": self.backend_packet_counts,
        }


def solve(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """ZeliJudge Problem #163 solve 진입점."""
    cluster = L4LoadBalancerCluster(input_data["config"])
    for op in input_data.get("operations", []):
        if op["type"] == "PACKET":
            cluster.process_packet(op)
        elif op["type"] == "ADMIN":
            cluster.handle_admin_event(op)
    return cluster.get_summary()


if __name__ == "__main__":
    raw = sys.stdin.read().strip()
    if raw:
        inp = json.loads(raw)
        out = solve(inp)
        print(json.dumps(out, indent=2))
