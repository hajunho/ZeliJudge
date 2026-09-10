# 리눅스 커널 eXpress Data Path (XDP)와 AF_XDP 제로카피(Zero-Copy) 링 버퍼 패킷 필터링 엔진

## 1. 개요 및 배경

초당 수천만 패킷(Mpps)이 인입되는 100GbE/400GbE 초고속 네트워크 환경에서 전통적인 리눅스 커널 네트워킹 스택(`netif_receive_skb` -> `sk_buff` 메모리 할당 -> TCP/IP 프로토콜 계층 순회 -> 유저스페이스 복사 `copy_to_user`)은 심각한 CPU 병목과 캐시 라인 오염을 초래합니다. 64바이트 최소 패킷 기준 10GbE는 초당 약 1,488만 패킷, 100GbE는 초당 약 1억 4,880만 패킷이 쏟아지며, 패킷당 처리 허용 시간은 불과 **6.72 나노초(ns)**에 불과합니다. 단 한 번의 `struct sk_buff` 동적 메모리 할당(약 240바이트 메타데이터)과 원자적 참조 카운트 증감 연산만으로도 이 예산은 즉각 초과되어 시스템은 패킷 드롭 참사에 직면합니다.

이 한계를 돌파하기 위해 리눅스 커널 4.8에 도입된 **eXpress Data Path (XDP)**는 네트워크 카드(NIC) 디바이스 드라이버의 수신(RX) 링 버퍼 단계에서 `sk_buff`를 할당하기 전, 순수 원시 패킷 버퍼(`struct xdp_buff`)에 eBPF 프로그램을 직접 실행합니다. 또한 커널 4.18에 도입된 **AF_XDP (XSK)** 소켓은 유저스페이스가 미리 등록한 연속 메모리 풀(**UMEM**)과 4개의 락프리 단일 생산자-단일 소비자(SPSC) 링 버퍼를 활용하여, 커널 TCP/IP 스택을 완전히 우회(Kernel Bypass)하는 제로카피(Zero-Copy) 패킷 전송을 달성합니다.

당신은 고성능 네트워크 엣지 방화벽 및 L4 로드밸런서(Katran/Unimog)를 위해, XDP 드라이버 훅과 AF_XDP UMEM 4대 링 버퍼, eBPF 기반 CIDR 블랙리스트 및 토큰 버킷(Token Bucket) 처리율 제한기를 정밀하게 시뮬레이션하는 **XDP 패킷 필터링 & 제로카피 링 버퍼 가상화 엔진**을 설계해야 합니다.

---

## 2. 시스템 아키텍처 및 XDP/AF_XDP 링 구조

```
                         [ 물리 NIC 수신 패킷 인입 ]
                                     │
                                     ▼
                   ┌───────────────────────────────────┐
                   │   NIC 드라이버 RX 링 (xdp_buff)   │
                   └─────────────────┬─────────────────┘
                                     │
                    [ eBPF XDP 훅 조기 패킷 검사 ]
                                     │
         ┌──────────────┬────────────┼─────────────┬─────────────┐
         ▼              ▼            ▼             ▼             ▼
   [XDP_DROP]       [XDP_TX]    [XDP_REDIRECT] [XDP_PASS]   [STARVATION]
    (블랙리스트     (헤어핀 MAC    (AF_XDP UMEM    (sk_buff      (Fill Ring
    /토큰버킷초과)   스왑 반환)      소켓 큐잉)     정상 스택)     고갈 드롭)
         │              │            │             │             │
     즉각 폐기       즉시 송신    유저 링 수신   커널 프로토콜  패킷 유실
    (0 메타데이터)   (0 복사)     (Zero-Copy)     (O(1) 비용)    (경고 로그)
                                     │
       ┌─────────────────────────────┴─────────────────────────────┐
       │                 AF_XDP UMEM 4대 링 버퍼                   │
       │                                                           │
       │  1. Fill Ring (User -> Kernel): 비어있는 UMEM 프레임 공급 │
       │  2. Rx Ring   (Kernel -> User): 패킷이 수신된 프레임 전달 │
       │  3. Tx Ring   (User -> Kernel): 송신할 패킷 프레임 제출   │
       │  4. Completion Ring (Kernel -> User): 송신 완료 프레임 반환│
       └───────────────────────────────────────────────────────────┘
```

---

## 3. 핵심 규칙 및 알고리즘 명세

### 3.1 UMEM 및 4대 링 버퍼 상태 관리
- **UMEM 프레임 풀**: 크기 `frame_size`(예: 2048 또는 4096 바이트)의 고정 블록들로 구성되며, 각각 고유한 정수 `frame_id`를 갖습니다.
- **Fill Ring**: 드라이버가 패킷을 DMA 수신할 수 있도록 유저스페이스가 사전에 적재해 둔 `frame_id` 대기 큐(FIFO 리스트)입니다.
- **Rx Ring**: 특정 AF_XDP 소켓(`socket_id`)에 도착한 패킷 정보(`pkt_id`, `frame_id`, `len`)가 저장되는 FIFO 큐입니다.
- **Tx Ring**: 유저스페이스가 송신을 요청한 프레임(`socket_id`, `frame_id`, `pkt_id`, `len`)이 대기하는 드라이버 송신 대기열입니다.
- **Completion Ring**: NIC가 패킷 전송을 마친 후 유저스페이스가 해당 프레임을 재사용할 수 있도록 반환하는 FIFO 큐입니다.

### 3.2 패킷 수신(`RX_PACKET`) 처리 파이프라인
패킷이 도착하면 다음 순서로 엄격하게 eBPF 룰을 평가합니다:

1. **블랙리스트 CIDR / IP 검사**:
   - 패킷의 `src_ip` 또는 `dst_ip`가 `blacklist_cidrs` 목록의 서브넷/IP에 포함되면 즉시 `XDP_DROP` 처리합니다 (`reason: "BLACKLIST_MATCH"`).
   - 어떠한 메모리 할당이나 링 버퍼 소비 없이 즉각 폐기됩니다.
2. **eBPF 맵 기반 IP별 토큰 버킷 처리율 제한 (DDoS 방어)**:
   - `rate_limiting.enabled == true`이고 `src_ip`가 `exempt_ips`에 속하지 않는 경우 검사합니다.
   - 각 `src_ip`별 상태는 버킷 내 토큰 수(`tokens`)와 마지막 갱신 시각(`last_ms`)을 추적합니다.
   - 최초 패킷 인입 시 `tokens = capacity`, `last_ms = timestamp_ms`로 초기화됩니다.
   - 이후 패킷 도착 시 경과 시간 $\Delta t = \max(0, rac{	ext{timestamp\_ms} - 	ext{last\_ms}}{1000})$ 초를 계산하여 충전합니다:
     $$	ext{tokens} = \min\left(	ext{capacity}, 	ext{tokens} + \Delta t 	imes 	ext{refill\_rate}ight)$$
     $$	ext{last\_ms} = 	ext{timestamp\_ms}$$
   - 충전 후 $	ext{tokens} < 1.0$이면 토큰 고갈로 간주하여 `XDP_DROP` 처리합니다 (`reason: "RATE_LIMITED"`).
   - $	ext{tokens} \ge 1.0$이면 $1.0$ 토큰을 차감하고 통과시킵니다.
3. **헤어핀 에코 반환 (`XDP_TX`)**:
   - 패킷의 `dst_port`가 `reflect_ports`에 포함되어 있으면 드라이버 수준에서 즉시 송신 포트로 반사합니다.
   - 액션은 `XDP_TX`이며, 상세 정보에 `reflected_dst_mac = src_mac`, `reflected_src_mac = dst_mac`, `len = pkt_len`을 기록합니다.
4. **AF_XDP 제로카피 리다이렉트 (`XDP_REDIRECT`)**:
   - eBPF 맵 `redirect_map`에서 `PROTO:PORT`(예: `"UDP:53"`) 또는 `IP:PORT`를 조회하여 대상 `socket_id`를 찾습니다.
   - 대상 소켓이 존재하는 경우:
     - **Fill Ring 기아 검사**: 만약 `fill_ring`이 비어있다면(`len == 0`), 하드웨어 DMA 버퍼가 고갈된 상태이므로 `DROP_STARVATION` 액션 및 `reason: "FILL_RING_EMPTY"`로 패킷이 드롭됩니다.
     - `fill_ring`에 사용 가능한 프레임이 있다면 가장 앞의 `frame_id`를 pop하여 대상 소켓의 `rx_ring`에 인큐하고 `XDP_REDIRECT` 액션을 기록합니다. 소켓의 `packets_received`를 1 증가시킵니다.
5. **정상 커널 스택 전달 (`XDP_PASS`)**:
   - 위 조건에 모두 해당하지 않는 일반 패킷은 `XDP_PASS` 액션을 부여받고 리눅스 커널 전통 프로토콜 스택(`KERNEL_SKB_STACK`)으로 전달되며, `skb_allocations` 카운터가 1 증가합니다.

### 3.3 유저스페이스 링 제어 이벤트
- `USER_CONSUME_RX`: 유저스페이스가 `socket_id`의 `rx_ring`에서 최대 `count`개의 프레임을 소비합니다. 소비된 프레임 ID들은 `recycled_frames`에 수집되며, `replenish_fill == true`인 경우 즉시 커널 `fill_ring`의 뒤에 재적재(extend)됩니다.
- `USER_ENQUEUE_TX`: 유저스페이스가 `socket_id`를 통해 `frame_id`와 패킷 메타데이터를 드라이버 `tx_ring`에 제출합니다.
- `TX_POLL`: 드라이버가 `tx_ring`에 대기 중인 모든 송신 프레임을 네트워크 선로로 일괄 플러시합니다. 플러시된 프레임들은 해당 소켓의 `completion_ring`으로 이동하여 유저스페이스가 재사용할 수 있도록 알립니다 (`packets_transmitted` 증가, `tx_completed` 증가).
- `USER_CONSUME_COMPLETION`: 유저스페이스가 `completion_ring`에서 최대 `count`개의 완료 프레임을 회수합니다. `return_to_fill == true`이면 `fill_ring`에 즉시 환원됩니다.

---

## 4. 입출력 형식 및 제약 조건

### 입력 형식 (JSON)
표준 입력(stdin)으로 단일 JSON 객체가 주어집니다:
```json
{
  "umem_config": { "frame_size": 2048, "total_frames": 16 },
  "rings_initial": { "fill_ring": [0, 1, 2, 3] },
  "bpf_rules": {
    "blacklist_cidrs": ["10.0.0.0/8"],
    "rate_limiting": {
      "enabled": true,
      "capacity": 5,
      "refill_rate": 2,
      "exempt_ips": ["127.0.0.1"]
    },
    "redirect_map": { "UDP:53": "xsk_dns", "TCP:8080": "xsk_web" },
    "reflect_ports": [7]
  },
  "sockets": ["xsk_dns", "xsk_web"],
  "events": [ ... ]
}
```

### 출력 형식 (JSON)
표준 출력(stdout)으로 다음 스키마의 JSON을 공백 없이(compact) 출력합니다:
```json
{
  "stats": {
    "xdp_drop_blacklist": 1,
    "xdp_drop_ratelimit": 0,
    "xdp_pass": 1,
    "xdp_tx": 1,
    "xdp_redirect": 4,
    "rx_starvation_drop": 0,
    "skb_allocations": 1,
    "tx_completed": 0
  },
  "zero_copy_ratio_pct": 66.67,
  "fill_ring_remaining": 0,
  "tx_ring_remaining": 0,
  "socket_reports": {
    "xsk_dns": {
      "rx_ring_remaining": 4,
      "completion_ring_remaining": 0,
      "packets_received": 4,
      "packets_transmitted": 0
    },
    "xsk_web": { ... }
  },
  "packet_logs": [ ... ]
}
```

*참고: `zero_copy_ratio_pct`는 드롭되지 않고 생존한 총 유효 인입 패킷($	ext{xdp\_pass} + 	ext{xdp\_tx} + 	ext{xdp\_redirect}$) 중 `xdp_redirect`(AF_XDP 제로카피)가 차지하는 비율(백분율, 소수점 둘째 자리 반올림)입니다. 생존 패킷이 0개인 경우 0.0으로 계산합니다.*
