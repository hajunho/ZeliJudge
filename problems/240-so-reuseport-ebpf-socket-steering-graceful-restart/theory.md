# Problem 240 Theory: 리눅스 커널 네트워크 스택 심층 분석 — `SO_REUSEPORT`, 소켓 큐 구조, 무중단 재로드 RST 함정 및 eBPF 소켓 스티어링

고성능 네트워크 애플리케이션(NGINX, Envoy, HAProxy 등)의 아키텍처는 리눅스 커널의 네트워크 소켓 모델 진화와 궤를 같이합니다. 본 문서에서는 리눅스 커널의 TCP 연결 수립 및 리슨 소켓 아키텍처, `SO_REUSEPORT`의 메커니즘과 프로덕션 한계, 그리고 이를 해결하기 위한 eBPF 소켓 스티어링(`SO_ATTACH_REUSEPORT_EBPF`)의 작동 원리를 심층 분석합니다.

---

## 1. 리눅스 커널 TCP 리슨 아키텍처 및 큐 구조

TCP 서버 소켓이 `listen(fd, backlog)` 시스템 콜을 호출하면, 커널 내부에서는 두 개의 서로 다른 큐가 생성 및 관리됩니다.

```
                  TCP 3-Way Handshake와 두 개의 커널 소켓 큐
                  
      Client                                   Linux Kernel
         │                                          │
         │──── 1. SYN (seq=x) ─────────────────────►│
         │                                          ▼ [inet_csk_reqsk_queue_add]
         │                                    ┌──────────────────────┐
         │                                    │ SYN Queue (반개방 큐)  │
         │                                    │ struct request_sock  │
         │◄─── 2. SYN+ACK (seq=y, ack=x+1) ───┤ (SYN_RECV 상태)       │
         │                                    └──────────────────────┘
         │                                          │
         │──── 3. ACK (ack=y+1) ───────────────────►│
         │                                          ▼ [tcp_check_req -> inet_csk_complete_hashdance]
         │                                    ┌──────────────────────┐
         │                                    │ Accept Backlog Queue │
         │                                    │ (완결 수락 대기 큐)    │
         │                                    │ sk_receive_queue     │
         │                                    │ (ESTABLISHED 상태)   │
         │                                    └──────────────────────┘
         │                                          │
   Client App                                       ▼ accept(fd)
   (Connected)                                  Server Worker App
```

### 1.1 반개방 큐 (SYN Queue / `request_sock` 테이블)
- **상태**: `TCP_SYN_RECV`
- **역할**: 클라이언트로부터 최초 SYN 패킷을 수신한 후 SYN-ACK을 전송하고, 최종 ACK이 도착하기 전까지 미완결 연결 상태를 추적합니다.
- **자료구조**: `struct request_sock_queue` 내의 해시 테이블.
- **보호 기법**: SYN Flood 공격으로 큐가 가득 차면, 리눅스는 `tcp_syncookies` 메커니즘을 가동하여 연결 상태를 메모리에 저장하지 않고 암호화된 시퀀스 번호(Cookie)를 SYN-ACK에 실어 전송합니다.

### 1.2 완결 수락 대기 큐 (Accept Backlog Queue / `sk_receive_queue`)
- **상태**: `TCP_ESTABLISHED`
- **역할**: 3-way 핸드셰이크가 완벽하게 완료되었으나, 유저스페이스 애플리케이션이 `accept()` 시스템 콜을 호출하여 유저 레벨 소켓 디스크립터로 가져가기 전까지 대기하는 소켓 큐입니다.
- **최대 수용 용량**: `min(backlog, /proc/sys/net/core/somaxconn)`
- **오버플로우 시의 커널 동작**:
  - Accept Backlog Queue가 가득 차면 커널은 새로 도착한 최종 3단계 ACK 패킷을 처리할 수 없습니다.
  - `/proc/sys/net/ipv4/tcp_abort_on_overflow`가 `0`(기본값)인 경우: 커널은 수신된 ACK을 사일런트 드롭합니다. 클라이언트는 연결이 완료된 것으로 간주하지만 데이터를 전송하면 서버가 응답하지 않아 SYN/ACK 재전송 루프에 빠집니다.
  - `tcp_abort_on_overflow`가 `1`인 경우: 커널은 즉시 클라이언트에게 **TCP RST**를 보내 연결을 강제 파기합니다.
  - 커널 메트릭 `TcpExtListenOverflows` 및 `TcpExtListenDrops`가 증가합니다.

---

## 2. 단일 리슨 소켓에서 `SO_REUSEPORT`로의 진화

### 2.1 단일 리슨 소켓 모델의 한계
초기 멀티 프로세스 서버(예: 전통적인 NGINX master-worker 모델)는 마스터 프로세스가 리슨 소켓 1개를 생성한 후 `fork()`하여 워커들이 동일한 리슨 소켓을 공유했습니다.
- **Thundering Herd 문제**: 신규 연결이 들어오면 `epoll_wait()` 중이던 모든 워커가 깨어나 `accept()`를 호출하지만, 오직 한 워커만 성공하고 나머지는 `EAGAIN` 에러를 반환하여 심각한 CPU 컨텍스트 스위칭 낭비가 발생했습니다 (`EPOLLEXCLUSIVE` 플래그 도입으로 일부 완화).
- **소켓 락 경합 (`sk->sk_lock`)**: 모든 워커 스레드가 동일한 소켓의 큐와 락에 접근하므로 코어 수가 증가할수록 캐시 무효화와 락 병목이 발생했습니다.

### 2.2 `SO_REUSEPORT` 메커니즘 (Linux 3.9+)
`SO_REUSEPORT` 옵션을 설정하면, 동일한 `uid`를 가진 독립적인 프로세스들이 동일한 IP와 포트에 바인딩된 여러 개의 리슨 소켓을 생성할 수 있습니다.

커널은 동일 포트에 바인딩된 소켓들을 `struct sock_reuseport` 배열(`reuse->socks[]`)로 관리합니다.

```c
// net/core/sock_reuseport.c (커널 소스 발췌 개념도)
struct sock *reuseport_select_sock(struct sock *sk, u32 hash, struct sk_buff *skb, int flag) {
    struct sock_reuseport *reuse = rcu_dereference(sk->sk_reuseport_cb);
    u16 socks = reuse->num_socks;
    u32 index = reciprocal_scale(hash, socks); // hash % socks
    return reuse->socks[index];
}
```

새로운 SYN 패킷이 도착하면 커널의 `inet_lookup_listener()` 함수는 패킷의 4-튜플(`src_ip`, `src_port`, `dst_ip`, `dst_port`)을 커널 내장 해시 함수(`skb_get_hash()`)로 해싱한 후 모듈로 연산을 통해 타깃 소켓을 선택합니다.

---

## 3. 프로덕션 환경에서의 `SO_REUSEPORT` 3대 결함

### 3.1 4-튜플 해시 편중과 큐 오버플로우
- **문제의 원인**: 대규모 CDN(Cloudflare, Akamai), 클라우드 NAT 게이트웨이(AWS NAT Gateway), 또는 기업 전용망 프록시를 경유하는 트래픽은 출발지 IP의 종류가 극히 제한적입니다.
- **결과**: 아무리 많은 워커 스레드를 띄워도 4-튜플 해시 알고리즘은 무상태(stateless) 정적 해시이므로 특정 워커 $W_0$의 소켓으로 트래픽이 쏠립니다. $W_0$의 백로그 큐가 꽉 차서 수많은 클라이언트 연결이 타임아웃되고 드롭되는 동안, $W_1 \sim W_{N-1}$은 CPU 점유율 0%로 놀고 있는 비극이 발생합니다.

### 3.2 무중단 롤링 재로드(Graceful Reload) 중 연결 리셋(RST) 함정
NGINX나 Envoy 같은 고성능 프록시는 무중단 바이너리 업그레이드 또는 설정 핫 리로드를 지원합니다. 그러나 커널 기본 `SO_REUSEPORT` 환경에서는 무중단 배포 시 반드시 연결 끊김이 발생합니다.

```
[SO_REUSEPORT 무중단 배포 시 발생하는 RST Drop 딜레마]

시나리오 1: 구버전 워커가 종료 시 소켓을 즉시 close()할 경우
┌────────────────────────────────────────────────────────────────────────┐
│ 1. 클라이언트와 커널 간 3-way 핸드셰이크 완료 (ESTABLISHED in backlog)   │
│ 2. 구버전 워커가 SIGTERM 수신 후 listen fd를 close()                      │
│ 3. 커널 net/ipv4/inet_connection_sock.c: inet_csk_listen_stop() 호출    │
│    - Backlog Queue에 남아있던 미수락 소켓 순회                          │
│    - tcp_disconnect(sk, O_NONBLOCK) -> 클라이언트로 강제 TCP RST 발송!  │
│ 4. 결과: 클라이언트 앱에서 "Connection reset by peer" 에러 발생          │
└────────────────────────────────────────────────────────────────────────┘

시나리오 2: 구버전 워커가 기존 연결만 drain하고 소켓을 열어둘 경우
┌────────────────────────────────────────────────────────────────────────┐
│ 1. 구버전 워커는 신규 요청 accept()를 중단하고 기존 활성 요청만 처리     │
│ 2. 그러나 커널의 reuse->socks[]에는 여전히 구버전 소켓이 등록되어 있음 │
│ 3. 신규 인입되는 클라이언트 SYN의 약 50%가 구버전 소켓으로 해싱 분배됨 │
│ 4. 구버전 워커는 accept()를 호출하지 않으므로 백로그에 영구 체류        │
│ 5. 결과: 클라이언트 연결 지연 타임아웃 (Connection Timeout) 발생        │
└────────────────────────────────────────────────────────────────────────┘
```

이 딜레마로 인해 단순 `SO_REUSEPORT`는 대규모 무중단 재로드 환경에서 사용이 기피되었습니다.

### 3.3 NUMA & RSS 인터럽트 코어 불일치로 인한 오버헤드
최신 100GbE+ NIC는 RSS(Receive Side Scaling) 하드웨어를 통해 인바운드 패킷을 복수의 하드웨어 RX 링 버퍼로 분산하고 각 링 버퍼를 특정 CPU 코어에 인터럽트(IRQ)로 연결합니다.
- 패킷이 Core 0의 NIC 드라이버 NAPI 폴링 루틴에서 수신되었습니다.
- 커널 `SO_REUSEPORT` 4-튜플 해시 계산 결과, 이 소켓은 Core 7(다른 NUMA 노드)에 위치한 워커 소켓에 할당됩니다.
- 패킷 skb 구조체와 메모리가 Core 0에서 Core 7로 넘어가면서 프로세서 간 인터럽트(IPI), L1/L2 캐시 미스, QPI/UPI 인터커넥트 대역폭 소모가 발생합니다.

---

## 4. eBPF 소켓 스티어링 (`SO_ATTACH_REUSEPORT_EBPF`)

리눅스 커널 4.5부터 `SO_ATTACH_REUSEPORT_EBPF`가 도입되었고, 커널 4.19에서 `BPF_PROG_TYPE_SK_REUSEPORT` 및 `BPF_MAP_TYPE_REUSEPORT_SOCKARRAY`가 추가되어 유저스페이스에서 C/eBPF 코드를 통해 소켓 선택 로직을 커널 레벨에서 프로그래밍할 수 있게 되었습니다.

```
       eBPF 기반 프로그래머블 소켓 선택 아키텍처
       
   Incoming SYN Packet
           │
           ▼
┌────────────────────────────────────────────────────────┐
│ BPF_PROG_TYPE_SK_REUSEPORT                             │
│                                                        │
│ 1. CPU 로컬리티 조회:                                   │
│    u32 cpu = bpf_get_smp_processor_id();              │
│ 2. 맵 기반 소켓 조회 및 상태 검사:                      │
│    struct bpf_sock *sk = bpf_map_lookup_elem(...);    │
│    if (sk->state == DRAINING) skip;                    │
│ 3. 큐 백로그 부하 검사:                                 │
│    if (backlog > watermark) divert_to_least_loaded();  │
│ 4. 목적지 소켓 결정:                                   │
│    bpf_sk_select_reuseport(ctx, &sock_map, index, 0);  │
└────────────────────────────────────────────────────────┘
           │
           ▼
Selected Worker Listen Socket (Zero Drop, Local Core)
```

### 4.1 핵심 BPF API 및 동작 원리
- **`BPF_MAP_TYPE_REUSEPORT_SOCKARRAY`**: 리슨 소켓들의 참조를 저장하는 특별한 BPF 맵입니다. 유저스페이스 데몬은 소켓 fd를 이 맵의 특정 인덱스에 등록(`BPF_MAP_UPDATE_ELEM`)하거나 삭제할 수 있습니다.
- **`bpf_sk_select_reuseport(ctx, map, key, flags)`**: eBPF 프로그램이 커널에 목적지 소켓 인덱스를 직접 지정하는 헬퍼 함수입니다. 이 함수가 성공하면 커널은 기본 4-튜플 해시를 건너뛰고 지정된 소켓의 백로그 큐로 패킷을 즉시 전달합니다.

### 4.2 세 가지 고도화 패턴

#### 패턴 A: CPU 코어 친화성 라우팅 (`EBPF_CPU_AFFINITY`)
```c
SEC("sk_reuseport")
int select_by_core(struct sk_reuseport_md *ctx) {
    u32 cpu = bpf_get_smp_processor_id();
    // 현재 패킷을 처리 중인 NIC RSS 인터럽트 코어와 동일한 번호의 워커 소켓으로 직결
    bpf_sk_select_reuseport(ctx, &reuse_sock_map, &cpu, 0);
    return SK_PASS;
}
```
- 패킷 수신 인터럽트를 처리한 코어의 L1/L2 캐시가 워커 스레드의 유저 메모리 버퍼와 동일한 CPU에 상주하므로 캐시 라인 바운싱이 완전히 제거됩니다.

#### 패턴 B: 백로그 수심 기반 동적 밸런싱 (`EBPF_LOAD_AWARE`)
- eBPF 맵을 통해 각 워커의 백로그 길이 또는 유저스페이스 큐 상태를 공유합니다.
- 특정 워커의 큐가 고수위(`load_watermark_pct`, 예: 80%)에 도달하면, 해시 결과와 무관하게 가장 한가한 워커의 소켓 인덱스로 즉시 경로를 전환하여 `ListenOverflows`를 원천 방지합니다.

#### 패턴 C: 무중단 드레이닝 상태 머신 (`EBPF_GRACEFUL_RELOAD`)
1. **재로드 트리거**: 신규 워커 프로세스가 기동되어 소켓을 열고 BPF 맵의 신규 슬롯에 `ACTIVE` 상태로 등록합니다.
2. **구버전 소켓 마스킹**: BPF 맵에서 구버전 소켓의 상태를 `DRAINING`으로 플래그합니다.
3. **eBPF 라우터의 배제**: eBPF 프로그램은 신규 인입되는 모든 SYN 패킷에 대해 `DRAINING` 상태인 소켓 인덱스를 검색 후보에서 완전히 제외합니다.
4. **안전한 드레인 및 클로즈**: 구버전 워커는 더 이상 신규 SYN이 들어오지 않는 상태에서 자신의 백로그 큐에 남아있는 모든 연결을 완전히 `accept()`하여 큐 수심을 0으로 만듭니다. 이후 안전하게 `close()`를 호출하므로 단 1건의 TCP RST도 유발하지 않는 진정한 **Zero-Downtime Graceful Reload**가 완성됩니다.

---

## 5. 실무 커널 모니터링 및 튜닝 체크리스트

| 항목 | 명령 / 파라미터 | 프로덕션 권장 기준 및 의미 |
| :--- | :--- | :--- |
| **최대 백로그 용량** | `sysctl net.core.somaxconn` | 대규모 프록시 환경에서는 `4096` ~ `65535` 이상으로 상향하여 버스트 흡수 |
| **SYN 백로그 용량** | `sysctl net.ipv4.tcp_max_syn_backlog` | 반개방 연결 수용 한도로 보통 `somaxconn`과 동일 수준으로 설정 |
| **오버플로우 시 RST 송신** | `sysctl net.ipv4.tcp_abort_on_overflow` | 기본값 `0`(사일런트 드롭 후 재전송 기대). 명시적 빠른 실패를 원할 시 `1` |
| **드롭 지표 모니터링** | `nstat -az TcpExtListenOverflows TcpExtListenDrops` | 0이 유지되어야 함. 카운트가 증가하면 해시 불균형 또는 accept 지연 발생 증거 |
| **소켓별 큐 깊이 확인** | `ss -lnt` | `Recv-Q`(현재 백로그 큐에 체류 중인 미수락 연결 수)와 `Send-Q`(최대 백로그 크기) 비교 |
