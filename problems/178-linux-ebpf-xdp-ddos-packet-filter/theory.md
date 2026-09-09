# Linux eBPF XDP(eXpress Data Path) 드라이버 레벨 패킷 필터링과 SYN Flood 커널 바이패스 방어

## 1. 개요: 초당 수천만 패킷(Mpps)의 DDoS 공격과 전통 커널의 한계

클라우드 엣지 인프라와 고성능 웹 서비스(Cloudflare, Netflix, Meta 등)는 일상적으로 수천만 pps(Packets Per Second) 규모의 볼류메트릭 DDoS(SYN Flood, UDP Flood, NTP Reflection 등) 위협에 노출됩니다.

100Gbps 네트워크 인터페이스 카드(NIC) 환경에서 64바이트 최소 크기 패킷이 유입될 때, 유입 속도는 **초당 약 1억 4,800만 패킷(148.8 Mpps)**에 달합니다. 즉, 단 하나의 패킷을 처리하는 데 허용된 시간은 **약 6.72 나노초(ns)**에 불과합니다.

그러나 기존 리눅스 커널의 표준 네트워킹 스택(Netfilter / iptables / nftables)은 이러한 초고속 패킷을 감당할 수 없도록 설계되어 있습니다.

---

## 2. 참사의 근원: 전통 리눅스 네트워크 스택과 `sk_buff` 할당 병목

### 2.1 전통적인 리눅스 패킷 수신 경로 (Rx Path)

```
[물리 NIC 패킷 도착]
        │
        ▼ (DMA 전송)
[NIC 수신 링 버퍼 (Rx Ring Buffer)]
        │
        ▼ (Hard IRQ 인터럽트 발생)
[NAPI 스케줄링 & SoftIRQ (NET_RX_SOFTIRQ)]
        │
        ▼ ⚠️ [치명적 병목: struct sk_buff 무거운 메모리 할당 (SLUB 캐시)]
[소켓 버퍼 (sk_buff) 구조체 생성 및 메타데이터 복사] (약 256 바이트 + 패킷 헤더 파싱)
        │
        ▼
[Netfilter / iptables (PREROUTING 체인)]
        │
        ▼ ⚠️ [치명적 병목: nf_conntrack 해시 락 경합 및 테이블 풀]
[커넥션 트래킹 (nf_conntrack)]
        │
        ▼
[TCP/IP 라우팅 및 소켓 수신 큐 (`sock->sk_receive_queue`)]
        │
        ▼
[유저스페이스 애플리케이션 (`epoll_wait()`, `recv()`)]
```

### 2.2 전통 스택의 3대 붕괴 지점

1. **`sk_buff` 할당 오버헤드**:
   - 리눅스 커널은 수신된 모든 패킷에 대해 거대한 메타데이터 제어 블록인 `struct sk_buff`(약 256B)를 할당합니다.
   - 초당 수백만 개의 위조된(Spoofed) SYN 패킷이 쏟아지면, CPU의 L1/L2/L3 캐시가 완전히 오염되고 SLUB 메모리 할당자 락 경합으로 인해 CPU가 100% `ksoftirqd`에 묶여 마비됩니다.
2. **`nf_conntrack` 테이블 고갈 (`table full, dropping packet`)**:
   - 모든 새로운 인바운드 연결 시도는 상태 추적 테이블에 등록됩니다.
   - SYN Flood 공격은 수십만 개의 위조된 IP와 무작위 포트를 사용하므로, conntrack 테이블의 최대 한도(`nf_conntrack_max`, 보통 262,144개)가 수 초 만에 고갈됩니다.
   - 결과적으로 테이블이 가득 차 정상적인 기존 고객의 요청(ACK, ESTABLISHED 세션)까지 무차별 드랍(`KERNEL_STACK_COLLAPSE_CONNTRACK_EXHAUSTION`)됩니다.
3. **처리 한계선**:
   - 고성능 멀티코어 서버라도 전통 커널 스택(iptables)으로는 단일 코어당 **100만~200만 pps(1~2 Mpps)** 처리가 한계입니다. 50M pps 공격이 유입되면 95% 이상의 패킷이 커널 문턱에서 강제 드랍됩니다.

---

## 3. 구원: eBPF와 XDP (eXpress Data Path) 아키텍처

Linux 4.8에서 Alexei Starovoitov와 Ingo Molnar, Daniel Borkmann 등에 의해 도입된 **XDP (eXpress Data Path)**는 리눅스 커널 네트워킹의 패러다임을 영구히 바꿨습니다.

XDP는 **`struct sk_buff`가 할당되기 전, NIC 디바이스 드라이버의 가장 최하단 링 버퍼 단계**에서 커널 내장 JIT 컴파일러로 컴파일된 eBPF 바이트코드를 직접 실행합니다!

```
[물리 NIC 패킷 도착]
        │
        ▼ (DMA 전송)
[NIC 수신 링 버퍼 (Rx Ring Buffer)]
        │
  ⚡️ [eBPF XDP Hook 실행!] (초당 2,400만 pps 단일 코어 라인 레이트 처리)
  ├── 1. 메모리 raw 버퍼 직접 검사 (xdp_md -> data, data_end)
  ├── 2. BPF Map (LRU Hash / Per-CPU Array) 초고속 조회
  └── 3. XDP 조치 판정:
        ├── XDP_DROP     -> 버퍼 즉각 재활용! (sk_buff 할당 0, CPU 점유율 0%)
        ├── XDP_TX       -> 들어온 NIC 포트로 즉시 패킷 바운스 (SYN Cookie 반환)
        ├── XDP_REDIRECT -> 다른 NIC / 가상 스위치 / AF_XDP 유저 공간 바이패스
        └── XDP_PASS     -> 정상 패킷만 상위 전통 리눅스 스택으로 승격
```

### 3.1 XDP의 4대 핵심 액션 코드

| 액션 코드 | 설명 및 내부 동작 | 활용 사례 |
| :--- | :--- | :--- |
| `XDP_DROP` | 패킷을 최하단 링 버퍼에서 즉시 폐기하고 RX 디스크립터를 즉시 반환 | 블랙리스트 IP 차단, SYN Flood, UDP 증폭 공격 방어 |
| `XDP_PASS` | 패킷에 `sk_buff`를 할당하고 표준 리눅스 TCP/IP 스택으로 정상 전달 | 합법적 사용자 트래픽, 내부 관리용 SSH 등 |
| `XDP_TX` | 패킷 헤더(MAC/IP)를 조작하여 패킷이 수신된 동일한 인터페이스로 즉시 반사 전송 | 무상태 SYN Cookie 생성, ICMP Echo 즉각 응답 |
| `XDP_REDIRECT` | 다른 인터페이스나 AF_XDP 제로카피 소켓(`AF_XDP UMEM`)으로 직접 우회 | 고성능 소프트웨어 라우터, L4 로드 밸런서 (Katran) |

---

## 4. XDP BPF 맵(Maps)을 활용한 실시간 상태 추적과 방어 기법

eBPF 프로그램은 기본적으로 이벤트 기반의 무상태(Stateless) 함수지만, 커널 메모리에 할당된 **BPF Maps**를 통해 유저스페이스 및 코어 간 상태를 공유할 수 있습니다.

### 4.1 BPF_MAP_TYPE_HASH / LRU_HASH
- **블랙리스트 차단**: 알려진 악성 봇넷 IP 목록을 해시 맵에 등록해 두고, 패킷 IP 헤더가 파싱되자마자 $O(1)$로 조회하여 즉시 `XDP_DROP`을 반환합니다.
- **동적 속도 제한 (Rate Limiting)**: 출발지 IP 또는 서브넷별로 초당/틱당 수신된 SYN 패킷 카운터를 LRU 맵에 기록합니다. 임계치(`xdp_syn_rate_limit`)를 초과하는 패킷은 즉시 폐기됩니다.

### 4.2 XDP 무상태 SYN Cookie (Stateless SYN Cookie at Line Rate)
전통 리눅스 커널의 SYN Cookie는 커널 TCP 스택까지 들어와야 연산되므로 여전히 softirq 오버헤드가 발생합니다.
반면 XDP 계층에서 직접 SYN Cookie를 구현하면:
1. 공격자가 대량의 SYN 패킷을 보낼 때, XDP는 커널 메모리나 소켓 큐를 일체 건드리지 않습니다.
2. 비밀 키와 IP, 포트, 타임스탬프를 조합하여 암호학적 해시(CRC32 / SipHash)로 SYN Cookie 시퀀스 번호를 산출합니다.
3. 패킷의 출발지/목적지 IP와 MAC 주소를 스왑하고 `SYN-ACK` 플래그를 세팅한 뒤 **`XDP_TX`를 호출하여 네트워크 카드로 즉각 튕겨냅니다!**
4. 공격자는 가짜 IP를 사용하므로 이 SYN-ACK에 응답하지 못합니다 (공격 무력화).
5. 정상 사용자는 올바른 ACK 번호(`cookie + 1`)를 담아 최종 ACK 패킷을 보냅니다.
6. XDP는 들어온 ACK 번호를 검증하고, 유효한 경우에만 `XDP_PASS`를 내려 커널 스택으로 올려보내 실제 TCP 연결을 맺습니다!

---

## 5. 실무 지표 비교: 전통 스택 vs eBPF XDP

| 성능 지표 | 전통 리눅스 커널 (iptables) | eBPF XDP (Driver Mode) | 개선 효과 |
| :--- | :--- | :--- | :--- |
| 단일 코어 패킷 처리량 | ~1.5 Mpps | **~24.0 Mpps** | **16배 이상 향상** |
| `sk_buff` 메모리 할당 | 모든 유입 패킷마다 256B 할당 | `XDP_DROP` 시 **0 Byte (완전 생략)** | 메모리 고갈 원천 방지 |
| CPU 점유율 (공격 10Mpps 시) | **100% (ksoftirqd 포화, 서버 다운)** | **5% 미만 (드라이버 레벨 즉각 폐기)** | 시스템 생존성 100% |
| conntrack 테이블 오염 | 위조된 IP로 100% 고갈 | 정상 인증 세션만 전달되어 0% 오염 | 합법적 고객 100% 연결 유지 |
