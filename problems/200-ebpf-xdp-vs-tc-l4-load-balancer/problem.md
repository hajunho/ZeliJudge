# 리눅스 커널 네트워킹: eBPF XDP vs TC L4 로드 밸런서(Katran)와 연결 추적(Conntrack) 우회 및 DSR(Direct Server Return)

## 문제 배경 및 개요
글로벌 하이퍼스케일러(Meta Katran, Cloudflare Unimog, Google Maglev, Cilium)의 인프라 에지 게이트웨이는 초당 수천만 개(Tens of Millions PPS)의 TCP/UDP 패킷을 L4 로드 밸런싱해야 합니다.
그러나 전통적인 리눅스 커널 기반 L4 로드 밸런서(LVS/IPVS, iptables NAT)는 극심한 트래픽 환경에서 두 가지 치명적인 물리적 한계에 직면하여 서버 전체가 마비됩니다:

1. **Netfilter Conntrack 연결 추적 테이블 포화 및 락 경합 (`nf_conntrack`)**:
   - 모든 유입 패킷이 커널 `nf_conntrack` 모듈을 통과하며 튜플 해시 버킷의 스핀락(Spinlock)을 획득하고 엔트리를 할당합니다.
   - 대규모 동시 접속 폭주나 SYN 버스트 발생 시 테이블이 가득 차(`conntrack: table full, dropping packet`), 정상 패킷이 무차별 폐기되고 소프트웨어 인터럽트(`ksoftirqd`)가 CPU 100%를 독점합니다.
2. **대칭형 SNAT(Source NAT)의 반환 트래픽 병목 (Asymmetric Bandwidth Collapse)**:
   - 일반적인 NAT 기반 로드 밸런서는 백엔드 서버의 응답 패킷을 다시 수신하기 위해 클라이언트 출발지 IP를 LB IP로 변환(SNAT)합니다.
   - 클라이언트의 요청 패킷은 수십~수백 바이트에 불과하지만, 백엔드가 전송하는 응답 데이터(HTML, 이미지, 동영상 스트리밍)는 수 메가바이트로 수십~수백 배 거대합니다.
   - 결과적으로 로드 밸런서의 송신(TX) 대역폭이 응답 트래픽에 의해 질식사합니다.

이를 해결하기 위해 현대 데이터센터는 **eBPF XDP(eXpress Data Path)와 DSR(Direct Server Return)** 아키텍처로 전면 전환했습니다:
- **XDP (Driver Level Packet Hook)**: 리눅스 커널이 무거운 `struct sk_buff` 소켓 버퍼를 할당하기 전, NIC 드라이버 링 버퍼 최하단에서 패킷을 가로채어 1마이크로초 미만으로 초고속 처리(`XDP_TX`).
- **DSR (Direct Server Return)**: 유입 패킷에 출발지 IP를 보존한 채 IPIP(IP-in-IP) 캡슐화만 덧씌워 백엔드(Real Server)로 전송합니다. 백엔드는 이를 수신한 후 **응답을 로드 밸런서를 거치지 않고 인터넷 클라이언트에게 직접(Direct) 전송**하여 LB 대역폭 병목을 100% 제거합니다.
- **Maglev 일관된 해싱 & BPF LRU 연결 테이블**:
   - 소수(Prime) 크기의 Maglev 조회 테이블로 백엔드 장애나 추가 시에도 기존 세션의 재배치를 최소화합니다.
   - BPF LRU 해시 맵(`connection_table`)을 통해 활성 TCP 플로우의 서버 고정(Flow Affinity)을 보장하며, FIN/RST 플래그 감지 시 즉각 메모리를 회수합니다.

당신은 차세대 클라우드 네트워킹 인프라 엔지니어로서, 전통적인 Conntrack NAT 방식, TC(Traffic Control) cls_bpf 방식, 그리고 eBPF XDP Katran 최적화 방식의 L4 로드 밸런서를 정밀 시뮬레이션하고 성능을 검증해야 합니다.

---

## 입력 형식
입력은 표준 입력(Standard Input)으로 단일 JSON 객체가 주어집니다:
```json
{
  "vip": "198.51.100.1:443",
  "backends": [
    {"id": "RS1", "ip": "10.0.1.1:443", "weight": 1, "healthy": true},
    {"id": "RS2", "ip": "10.0.1.2:443", "weight": 1, "healthy": true}
  ],
  "mode": "XDP_KATRAN_OPTIMAL",
  "config": {
    "conntrack_capacity": 1000,
    "maglev_table_size": 1021,
    "lru_connection_limit": 50000
  },
  "traffic_events": [
    {
      "timestamp_ms": 10.0,
      "flow": {"src_ip": "192.168.1.1", "src_port": 12345, "proto": "TCP"},
      "flags": ["SYN"],
      "payload_bytes": 60
    }
  ],
  "backend_updates": [
    {"timestamp_ms": 50.0, "action": "DOWN", "backend_id": "RS2"}
  ]
}
```

- `vip`: 가상 서비스 IP 및 포트.
- `backends`: 백엔드 리얼 서버 목록 (`id`, `ip`, `weight`, `healthy`).
- `mode`: 시뮬레이션 모드 (`"XDP_KATRAN_OPTIMAL"`, `"TC_EBPF_DSR"`, `"TRADITIONAL_CONNTRACK_NAT"`).
- `config`: 로드 밸런서 튜닝 설정 (`conntrack_capacity`, `maglev_table_size`, `lru_connection_limit`).
- `traffic_events`: 유입 패킷 스트림 (`timestamp_ms`, `flow`, `flags`, `payload_bytes`).
- `backend_updates`: 런타임 백엔드 상태 변경 이벤트 (`timestamp_ms`, `action`, `backend_id`).
  - `action`: `"DOWN"`, `"UP"`, `"WEIGHT_CHANGE"`, `"ADD"`, `"DRAIN"`.

---

## 출력 형식
표준 출력(Standard Output)으로 시뮬레이션 결과 지표를 JSON 형태로 출력합니다:
```json
{
  "mode_used": "XDP_KATRAN_OPTIMAL",
  "metrics": {
    "total_ingress_packets": 60,
    "total_ingress_bytes": 22440,
    "forwarded_packets": 60,
    "dropped_packets": 0,
    "drop_reasons": {},
    "active_flows_count": 20,
    "conntrack_peak_usage": 20,
    "backend_distribution": {
      "RS1": 15,
      "RS2": 15,
      "RS3": 15,
      "RS4": 15
    },
    "broken_connection_resets": 0,
    "lb_egress_bytes": 24840,
    "cpu_processing_cost_units": 6.0,
    "verdict": "OPTIMAL_XDP_DSR_LINE_RATE"
  }
}
```

- 패킷 드롭 발생 시 `verdict`는 `"CONNTRACK_EXHAUSTION_COLLAPSE"`.
- `XDP_KATRAN_OPTIMAL` 성공 시 `verdict`는 `"OPTIMAL_XDP_DSR_LINE_RATE"`.
- `TC_EBPF_DSR` 성공 시 `verdict`는 `"TC_DSR_SUBOPTIMAL"`.

---

## 판정 기준 (Verdict Rules)
1. **DSR 송신 대역폭 절감**: DSR 모드에서는 반환 응답 트래픽(10x 바이트)이 로드 밸런서를 거치지 않아야 합니다 (`lb_egress_bytes` 절감).
2. **Conntrack 고갈 방어**: Netfilter 기반 전통 모드에서 테이블 포화 시 드롭을 정확히 기록해야 하며, eBPF LRU 맵을 통해 이를 원천 차단해야 합니다.
3. **Maglev 일관성 및 세션 친화성**: 백엔드 증설/변경 시 기존 연결이 유지되어야 하며(`broken_connection_resets == 0`), 장애 발생 시에만 즉각적인 안전 재배치가 이루어져야 합니다.
4. **연결 수명주기 감지**: FIN/RST 수신 시 BPF 맵 엔트리를 즉시 회수하여 메모리 누수를 방지해야 합니다.
