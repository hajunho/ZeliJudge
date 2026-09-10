# 기술 이론: 리눅스 커널 eBPF XDP(eXpress Data Path) 내부 아키텍처

## 1. 개요 및 설계 철학
기존 리눅스 커널 네트워크 스택의 치명적 한계는 **패킷당 처리 비용(Per-Packet Overhead)**입니다:
1. 하드웨어 DMA 수신 완료 인터럽트 발생.
2. `sk_buff` 구조체 할당 (메모리 256 바이트 이상 + 페이로드 버퍼 할당).
3. 넷필터(Netfilter / iptables) 규칙 체인 순회.
4. 라우팅 테이블 조회(FIB Lookup) 및 소켓 버퍼 락 획득.

이 과정으로 인해 100GbE 회선의 최대 패킷 처리량인 148 Mpps를 처리하려면 수십 개의 고사양 CPU 코어가 100% 포화됩니다.

클라우드플레어(Cloudflare)와 메타(Meta Katran L4LB)가 주도하여 리눅스 커널에 도입한 **XDP(eXpress Data Path)**는 이 모든 과정을 무력화하고, NIC RX 링 버퍼에 패킷이 안착하자마자 eBPF 코드로 즉시 판단을 내립니다:

```
        [ 하드웨어 NIC RX DMA Ring Buffer ]
                         │
             xdp_buff (원시 메모리 포인터)
                         ▼
        ┌──────────────────────────────────┐
        │  eBPF XDP 드라이버 훅             │
        │  (bpf_prog_run_xdp)              │
        └────────────────┬─────────────────┘
                         │ 5대 XDP 판정 (xdp_action)
         ┌───────────────┼───────────────┬───────────────┐
         ▼               ▼               ▼               ▼
     [ XDP_DROP ]    [ XDP_TX ]   [ XDP_REDIRECT ]  [ XDP_PASS ]
     (라인레이트 차단) (헤어핀 반사) (DEVMAP/AF_XDP) (커널 skb 전달)
```

---

## 2. 5대 XDP 액션의 커널 내부 메커니즘

| 판정 (Verdict) | 커널 내부 처리 | 대표 활용 사례 |
| :--- | :--- | :--- |
| **`XDP_ABORTED`** | 프로그램 결함, `xdp_aborted` 트레이스포인트 트리거 후 드롭 | eBPF 메모리 안정성 버그 감지 |
| **`XDP_DROP`** | RX 링 버퍼 디스크립터를 즉시 재사용 대기 상태로 반환 | 테라비트급 SYN Flood / UDP DDoS 방어 |
| **`XDP_PASS`** | 커널이 비로소 `build_skb()`를 호출하여 정상 네트워크 스택 진입 | 로컬 웹 서버(NGINX), SSH 트래픽 |
| **`XDP_TX`** | L2/L3 헤더 스왑 후 인그레스 인터페이스의 TX 링으로 직접 큐잉 | 초저지연 ICMP Echo 응답, 패킷 반사 |
| **`XDP_REDIRECT`** | `xdp_do_redirect()`: DEVMAP, CPUMAP, AF_XDP 소켓으로 전달 | L4 로드밸런서(Katran), 금융 초저지연 거래 |

---

## 3. AF_XDP와 제로카피 커널 바이패스 (Kernel Bypass)

전통적인 DPDK(Data Plane Development Kit)는 커널을 완전히 무시하고 NIC를 유저 공간 프로세스가 독점하므로 다음과 같은 치명적 단점이 있었습니다:
- 표준 리눅스 보안 도구, 컨테이너 네트워크, 소켓 API 사용 불가.
- 전용 CPU 코어를 100% 폴링(Busy-polling)으로 소모하여 전력 낭비 극심.

**AF_XDP(`XSKMAP`)**는 유저 공간 메모리(`UMEM`) 링 버퍼를 드라이버 RX 링과 직접 매핑(Zero-Copy)함으로써:
- 커널 공간으로의 메모리 복사 0바이트.
- 표준 리눅스 권한 관리 및 eBPF 필터링 기능 유지.
- 초당 수천만 pps의 패킷을 유저 공간 C/Rust/Go 애플리케이션으로 손실 없이 직통 배달.
