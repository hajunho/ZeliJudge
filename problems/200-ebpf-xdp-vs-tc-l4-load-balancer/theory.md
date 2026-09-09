# eBPF XDP vs TC L4 로드 밸런싱: Conntrack 우회, Maglev 해싱 및 Direct Server Return(DSR) 심층 분석

## 1. 전통적 L4 로드 밸런서의 구조적 병목 (LVS/IPVS & iptables)

### 1.1 Netfilter Conntrack 락 경합 및 테이블 포화
리눅스 네트워크 스택에서 `nf_conntrack`은 유입되는 모든 5-튜플 패킷에 대해 연결 상태(`ESTABLISHED`, `NEW`, `TIME_WAIT`)를 추적합니다:
- 각 패킷은 `__nf_conntrack_find_get()`을 호출하며 해시 버킷의 스핀락을 획득합니다.
- 멀티코어 서버(32~128 코어)에서 코어 간 락 경합(Lock Contention)으로 인해 패킷 처리 성능이 급격히 저하됩니다.
- 대규모 SYN Flood 또는 수백만 개의 동시 접속 발생 시 `nf_conntrack: table full, dropping packet` 오류와 함께 정상 트래픽이 전량 폐기됩니다.

### 1.2 대칭형 NAT(SNAT/DNAT)의 비대칭 대역폭 참사
일반적인 Full-NAT 구성:
- 클라이언트 요청: 100 바이트 (Client -> LB -> Server)
- 서버 응답: 10 MB 스트리밍 (Server -> LB -> Client)
- 로드 밸런서의 NIC 송신(TX) 대역폭이 100배 거대한 응답 트래픽으로 가득 차서, 정작 중요한 유입 패킷을 수신하지 못하는 대역폭 붕괴 현상이 발생합니다.

---

## 2. eBPF XDP (eXpress Data Path)의 혁신

### 2.1 커널 스택 계층 비교: XDP vs TC vs 소켓 계층

```
+-------------------------------------------------------------+
|                      User Application                       |
+-------------------------------------------------------------+
                              ^
                              | (sys_recv / epoll)
+-------------------------------------------------------------+
|                      TCP/IP Stack (L4)                      |
|                  nf_conntrack, iptables                     |
+-------------------------------------------------------------+
                              ^
                              | (struct sk_buff allocated)
+-------------------------------------------------------------+
|                     TC (Traffic Control)                    |  <- cls_bpf hook
+-------------------------------------------------------------+
                              ^
                              | (struct xdp_buff - Raw Memory)
+-------------------------------------------------------------+
|                 XDP (eXpress Data Path)                     |  <- Katran Native Driver Hook
+-------------------------------------------------------------+
                              ^
                              | DMA Ring Buffer
+-------------------------------------------------------------+
|                  NIC Hardware (100GbE / 200GbE)             |
+-------------------------------------------------------------+
```

- **XDP (Driver Mode)**:
  - 커널이 `struct sk_buff` (약 256바이트의 무거운 메타데이터 구조체)를 할당하기 **전**에 동작합니다.
  - NIC의 수신 링 버퍼에서 원시 메모리(`xdp_buff`)를 직접 읽어 처리합니다.
  - 패킷을 다른 인터페이스로 전달할 때 `XDP_TX` 또는 `XDP_REDIRECT`를 사용하여 커널 스택을 100% 우회합니다.
  - 단일 호스트에서 4천만 PPS(Packets Per Second) 이상의 유선 한계 속도(Line-Rate)를 달성합니다.
- **TC (Traffic Control cls_bpf)**:
  - 패킷이 이미 `struct sk_buff`로 래핑된 후 유입(Ingress)/송출(Egress) 지점에서 동작합니다.
  - XDP보다 다양한 커널 소켓 메타데이터에 접근할 수 있으나, 메모리 할당 및 해제 오버헤드로 인해 초당 패킷 처리량이 XDP 대비 약 1/3~1/5 수준으로 낮습니다.

---

## 3. Direct Server Return (DSR) 원리

```
                   [Client]
                  /        ^
        1. SYN   /          \  3. Response Data
       (100 B)  /            \   (10 MB Direct!)
               v                   [XDP Load Balancer]                      |                      2. IPIP Encap                     (Client IP preserved)                     |                                  v                           [Backend Real Server] --------+
```

1. **클라이언트 요청**: 목적지 IP가 VIP인 패킷을 로드 밸런서로 전송합니다.
2. **LB 포워딩 (DSR IPIP Encapsulation)**:
   - 로드 밸런서는 출발지 클라이언트 IP를 변조하지 않습니다.
   - 외부 IP 헤더(LB -> RealServer)를 덧씌워 IPIP 터널로 백엔드에 포워딩합니다.
3. **백엔드 직접 응답 (Direct Server Return)**:
   - 백엔드는 터널을 해제하고 내부 패킷의 출발지가 클라이언트 IP임을 확인합니다.
   - 백엔드의 루프백 인터페이스(`lo:0`)에 VIP가 바인딩되어 있으므로 정상 처리 후, **출발지를 VIP, 목적지를 클라이언트 IP로 지정하여 로드 밸런서를 거치지 않고 다이렉트로 전송**합니다!
   - 로드 밸런서는 오직 초소형 인그레스 트래픽만 처리하므로 수백 Gbps 서비스도 저가형 서버 몇 대로 거뜬히 소화합니다.

---

## 4. Google Maglev 일관된 해싱 알고리즘

Maglev 해싱은 백엔드 풀의 서버가 추가/제거될 때 기존 연결의 불필요한 재배치를 최소화하는 룩업 테이블 알고리즘입니다:

1. **테이블 크기 M**: 큰 소수(Prime Number, 예: 65537)를 선택합니다.
2. **순열 생성**: 각 백엔드 $B_i$에 대해 두 개의 독립적인 해시 함수 $h_1, h_2$를 사용하여 오프셋과 스킵 값을 계산합니다:
   $$	ext{offset} = h_1(B_i) \pmod M, \quad 	ext{skip} = h_2(B_i) \pmod{M - 1} + 1$$
3. **라운드로빈 슬롯 채우기**: 모든 백엔드가 차례대로 자신의 순열 위치 $(	ext{offset} + c \cdot 	ext{skip}) \pmod M$가 비어있으면 백엔드 ID를 기입하고, 충돌 시 다음 위치로 이동하여 $M$개 슬롯이 모두 찰 때까지 반복합니다.
4. **결과**: 백엔드 1대가 다운되어도 $1/N$의 트래픽만 재배치되고 나머지 $(N-1)/N$ 트래픽은 기존 백엔드에 그대로 유지됩니다.

---

## 5. 엔터프라이즈 하이퍼스케일러 L4 LB 아키텍처 비교

| 아키텍처 | 처리 계층 | 패킷 처리 메커니즘 | 반환 경로 | 최대 처리량 (단일 노드) |
| :--- | :--- | :--- | :--- | :--- |
| **Linux IPVS / iptables** | Netfilter (L4) | `struct sk_buff` + conntrack 락 | 대칭형 SNAT (LB 경유) | ~1.5M PPS |
| **Linux TC eBPF (Cilium)** | TC Ingress (L3/L4) | `struct sk_buff` + BPF Map | DSR (IPIP / Geneve) | ~6M PPS |
| **Meta Katran (XDP)** | NIC Driver Ring Buffer | Raw Memory + Maglev + BPF LRU | DSR (IPIP / GUE) | **40M+ PPS (Line Rate)** |
| **Cloudflare Unimog** | XDP / TC Hybrid | Consistent Hash + Flow Sticking | DSR (L2 MAC Rewrite) | **Line Rate** |
