# 문제 308: 리눅스 커널 eBPF XDP(eXpress Data Path) 고속 패킷 필터 및 제로카피 리다이렉트 엔진 (Linux Kernel eBPF XDP Engine)

## 문제 배경
초당 수천만~수억 개의 패킷이 유입되는 100GbE 네트워크 환경과 대규모 테라비트급 분산 서비스 거부 공격(DDoS) 상황에서, 리눅스 커널의 표준 네트워크 스택은 각 패킷마다 `sk_buff` 구조체를 동적 할당하고 L2/L3/L4 계층을 순회하는 오버헤드로 인해 CPU가 순식간에 포화됩니다.

이를 해결하기 위해 리눅스 커널(`net/core/filter.c`)은 네트워크 장치 드라이버의 RX DMA 링 버퍼에서 패킷이 수신되는 즉시, 즉 **`sk_buff`가 할당되기 이전의 가장 원초적인 단계(Earliest Possible Point)**에서 eBPF 바이트코드를 실행하는 **XDP(eXpress Data Path)** 프레임워크를 도입했습니다.

XDP 프로그램은 각 패킷에 대해 다음 5가지 표준 판정(Verdict, `xdp_action`) 중 하나를 반환합니다:
1. **`XDP_ABORTED` (0)**: eBPF 프로그램의 메모리 경계 검사 실패 또는 예외 발생 시 드라이버가 패킷을 즉시 드롭하고 트레이스포인트를 트리거.
2. **`XDP_DROP` (1)**: 드라이버 단계에서 패킷을 즉시 폐기. `sk_buff` 할당이 전혀 발생하지 않아 초당 1억 개 이상의 악성 패킷을 무손실 차단.
3. **`XDP_PASS` (2)**: 일반적인 정상 패킷을 상위 커널 네트워크 스택(`napi_gro_receive` / `netif_receive_skb`)으로 전달하여 정상 처리.
4. **`XDP_TX` (3)**: 패킷이 수신된 바로 그 네트워크 인터페이스의 TX 링 버퍼로 패킷을 즉시 되돌려 반사(Hairpin Bounce). L2/L3 헤더를 스왑하여 ICMP Echo 응답 등에 활용.
5. **`XDP_REDIRECT` (4)**: 커널 스택을 완전히 우회하여:
   - **`AF_XDP` (XSKMAP)**: 제로카피 UMEM 링 버퍼를 통해 유저 공간 애플리케이션으로 직행.
   - **`DEVMAP`**: 다른 네트워크 카드로 즉시 L2/L3 포워딩 (고성능 라우터/게이트웨이).
   - **`CPUMAP`**: 멀티코어 간 RSS 부하 균등 분산을 위해 타 CPU의 백로그 큐로 전달.

본 문제에서는 XDP 프로그램의 5대 핵심 액션, BPF Map 기반의 블랙리스트 필터링, DEVMAP 라우팅 및 AF_XDP 제로카피 리다이렉트 파이프라인을 정밀하게 시뮬레이션하는 **eBPF XDP 커널 엔진**을 구현해야 합니다.

---

## 시스템 동작 규칙 및 엔진 명세

### 1. eBPF 검증자 경계 검사 (Verifier Bounds Check)
- 패킷 객체의 `corrupted_bounds` 플래그가 참인 경우:
  - 메모리 오버런 접근(`data + len > data_end`)으로 판정하여 액션 `"XDP_ABORTED"`를 반환하고 즉시 폐기합니다.

### 2. DDoS 블랙리스트 검사 (`XDP_DROP`)
- 수신 패킷의 출발지 IP(`src_ip`)가 `bpf_maps.blacklist_ips`에 존재하는 경우:
  - 액션 `"XDP_DROP"`을 반환하며, 상위 스택으로 일체의 메모리가 할당되지 않고 드라이버 레벨에서 즉시 소멸합니다.

### 3. AF_XDP 유저 공간 제로카피 리다이렉트 (`XDP_REDIRECT` -> AF_XDP)
- 패킷의 목적지 포트(`dst_port`)가 `bpf_maps.xskmap`에 등록되어 있는 경우:
  - 액션 `"XDP_REDIRECT"`를 반환하며, `redirect_target = "AF_XDP_UMEM"`, `target_port = dst_port`로 기록합니다.

### 4. DEVMAP 인터페이스 포워딩 (`XDP_REDIRECT` -> DEVMAP)
- 수신 패킷의 목적지 IP(`dst_ip`)가 `bpf_maps.devmap`에 라우팅되어 있는 경우:
  - 액션 `"XDP_REDIRECT"`를 반환합니다.
  - L2/L3 헤더 수정: 출발지 MAC 주소를 목적지 인터페이스의 MAC(`out_mac`)으로 재작성하고, IP `ttl`을 1 감소시킵니다.
  - `redirect_target = "DEVMAP"`, `target_ifindex = target_ifindex`로 기록합니다.

### 5. 헤어핀 TX 반사 (`XDP_TX`)
- 패킷 프로토콜이 `ICMP`인 경우:
  - 수신된 인터페이스와 동일한 인터페이스(`tx_ifindex = rx_ifindex`)로 즉시 되돌려 보냅니다.
  - 헤더 스왑: `src_mac <-> dst_mac`, `src_ip <-> dst_ip`를 상호 교환합니다.

### 6. CPUMAP 멀티코어 재분배 (`XDP_REDIRECT` -> CPUMAP)
- `bpf_maps.cpumap_hash_enabled`가 참인 경우:
  - 5-튜플 해시를 계산하여 대상 CPU를 결정합니다.
  - 대상 CPU가 현재 수신 CPU(`rx_cpu`)와 다를 경우:
    - 액션 `"XDP_REDIRECT"`, `redirect_target = "CPUMAP"`, `target_cpu = target_cpu`로 분산합니다.

### 7. 정상 패킷 전달 (`XDP_PASS`)
- 위 조건에 해당하지 않는 정상 트래픽은 `"XDP_PASS"`로 판정되어 리눅스 커널 네트워크 스택으로 전달(`sk_buff` 할당)됩니다.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "config": {
    "interfaces": [{"ifindex": 1, "name": "eth0", "mac": "52:54:00:12:34:56"}],
    "cpu_cores": 4
  },
  "bpf_maps": {
    "blacklist_ips": ["198.51.100.44"],
    "devmap": {},
    "xskmap": [53],
    "cpumap_hash_enabled": false
  },
  "packets": [
    {
      "pkt_id": 1,
      "rx_ifindex": 1,
      "rx_cpu": 0,
      "eth": {"src_mac": "aa:bb:cc:dd:ee:01", "dst_mac": "52:54:00:12:34:56"},
      "ip": {"src_ip": "198.51.100.44", "dst_ip": "10.0.0.1", "proto": "UDP", "ttl": 64},
      "l4": {"src_port": 5353, "dst_port": 80},
      "payload_bytes": 1024,
      "corrupted_bounds": false
    }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 JSON 객체를 단일 행으로 출력합니다:

```json
{
  "summary": {
    "total_packets_processed": 1,
    "verdict_counts": {
      "XDP_ABORTED": 0,
      "XDP_DROP": 1,
      "XDP_PASS": 0,
      "XDP_TX": 0,
      "XDP_REDIRECT": 0
    },
    "line_rate_efficiency": 1.0
  },
  "packets": [
    {
      "pkt_id": 1,
      "action": "XDP_DROP",
      "detail": "Source IP 198.51.100.44 dropped by eBPF DDoS blacklist map"
    }
  ]
}
```

---

## 제약 사항
- `1 <= len(packets) <= 5,000`
- `1 <= cpu_cores <= 64`
- `line_rate_efficiency`는 드라이버 레벨에서 처리된 패킷 비율(`(DROP + TX + REDIRECT) / total`)로 소수점 넷째 자리까지 반올림합니다.
