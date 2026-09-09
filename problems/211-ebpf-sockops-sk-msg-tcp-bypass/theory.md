# Problem 211 심층 이론: 리눅스 커널 eBPF sockops 및 sk_msg를 통한 로컬 컨테이너 간 TCP/IP 스택 바이패스와 conntrack 고갈 방어

## 1. 레거시 컨테이너 네트워킹의 구조적 비효율과 병목

쿠버네티스(Kubernetes) 환경에서 컨테이너 간 통신은 각 파드에 독립된 네트워크 네임스페이스(Network Namespace)를 부여하고, 이를 호스트 루트 네임스페이스(Host Root Namespace)와 연결하기 위해 **가상 이더넷 페어(veth pair)** 및 **리눅스 브리지(Linux Bridge)** 또는 **OVS(Open vSwitch)**를 사용하는 것이 오랜 표준이었습니다.

하지만 마이크로서비스 아키텍처(MSA) 및 서비스 메시(Service Mesh, 예: Istio Envoy 사이드카)가 보편화되면서, 동일한 워커 노드(Worker Node) 내부에서 실행 중인 로컬 파드 간(예: App Pod ↔ Envoy Proxy Pod) 통신 비중이 전체 트래픽의 70% 이상을 차지하게 되었습니다. 이 환경에서 레거시 네트워크 스택은 극심한 CPU 오버헤드와 장애를 유발합니다.

```
[레거시 veth 기반 동일 노드 파드 간 패킷 경로: 2번의 완전한 커널 TCP/IP 스택 순회]

+------------------------+                               +------------------------+
| App Pod (NS 1)         |                               | Envoy Pod (NS 2)       |
| Socket A (10.244.1.15) |                               | Socket B (10.244.1.16) |
+-----------+------------+                               +-----------▲------------+
            │ send()                                                 │ recv()
            ▼                                                        │
    [TCP 계층]                                               [TCP 계층]
    - 세그먼트 생성, SEQ/ACK, 체크섬                          - 순서 정렬, 소켓 수신 버퍼 큐잉
            │                                                        ▲
            ▼                                                        │
    [IP 계층 & Netfilter]                                    [IP 계층 & Netfilter]
    - 라우팅 룩업, PREROUTING/OUTPUT                         - INPUT 체인 iptables 평가
    - iptables 규칙 순회                                             ▲
    - nf_conntrack 엔트리 생성/갱신                                  │
            │                                                        │
            ▼                                                        │
    [veth0 (Pod NS)] ──(패킷 캡슐화)──► [veth_host1 (Root NS)]       │
                                             │                       │
                                             ▼                       │
                                     [Linux Bridge / ebtables]       │
                                     - iptables FORWARD 체인 평가    │
                                             │                       │
                                             ▼                       │
    [veth1 (Pod NS)] ◄──(패킷 역캡슐화)─ [veth_host2 (Root NS)] ─────┘
```

### 1.1 2회에 걸친 완전한 커널 네트워크 스택 순회
동일한 호스트 메모리에 상주하는 두 프로세스(App과 Envoy)가 통신함에도 불구하고, 패킷(`struct sk_buff`)은 다음 과정을 두 번씩 거칩니다:
1. **소켓 버퍼 복사**: 유저 공간 메모리에서 커널 `sk_buff`로 복사.
2. **TCP 프로토콜 처리**: 시퀀스 번호 계산, 슬라이딩 윈도우, 체크섬 오프로드 검증.
3. **IP 계층 처리**: FIB(Forwarding Information Base) 라우팅 테이블 룩업.
4. **Netfilter iptables 규칙 체인 순회**: 노드에 수천~수만 개의 쿠버네티스 서비스(ClusterIP, NodePort) 규칙이 등록되어 있을 경우, $O(N)$ 선형 탐색으로 인한 심각한 CPU 캐시 미스와 코어 점유 발생.
5. **Netfilter conntrack (연결 추적)**: 튜플(Tuple: `src_ip, src_port, dst_ip, dst_port, proto`)을 해시 테이블에 기록하고 스핀락(Spinlock) 경쟁 발생.
6. **veth 페어 간 컨텍스트 스위칭**: 가상 인터페이스 큐를 거쳐 소프트웨어 인터럽트(SoftIRQ, `ksoftirqd`) 스케줄링.

이로 인해 단순한 로컬 IPC 수준의 통신이어야 할 트래픽에 무려 **$30 \sim 55\,\mu\text{s}$**의 왕복 지연시간이 소모됩니다.

---

## 2. conntrack 테이블 고갈(Exhaustion) 참사와 커널 패닉 메커니즘

### 2.1 nf_conntrack의 동작 원리
리눅스 넷필터의 conntrack 모듈은 모든 연결 상태(NEW, ESTABLISHED, RELATED, TIME_WAIT 등)를 `nf_conn` 슬래브(Slab) 캐시 구조체로 추적합니다.
- 테이블의 최대 크기는 커널 파라미터 `net.netfilter.nf_conntrack_max`로 정의됩니다 (예: 기본 65,536 또는 262,144).
- 신규 TCP 연결(SYN)이 들어오면 해시 버킷을 탐색하고 새로운 `nf_conn` 엔트리를 할당합니다.

### 2.2 단기 연결 폭증(Microservice Burst)과 테이블 고갈
마이크로서비스 환경에서 Keep-Alive를 쓰지 않는 HTTP/1.1 클라이언트나 짧은 RPC 호출이 초당 수만 건 발생하면:
1. 소켓이 정상 종료(`FIN/ACK`)되더라도 conntrack 엔트리는 즉시 해제되지 않고, `nf_conntrack_tcp_timeout_close_wait`(기본 60초), `nf_conntrack_tcp_timeout_time_wait`(기본 120초) 동안 메모리에 잔류합니다.
2. 이로 인해 활성 연결이 많지 않더라도 잔류 엔트리가 누적되어 `nf_conntrack_count >= nf_conntrack_max`에 도달합니다.
3. 테이블이 가득 차면 커널은 더 이상 패킷을 수용하지 못하고 즉시 드롭합니다:
   ```
   kernel: nf_conntrack: table full, dropping packet
   ```
4. 결과적으로 로컬 파드 간의 헬스체크(Liveness/Readiness Probe) 패킷까지 드롭되어 파드가 강제 재시작되는 연쇄 장애(Cascading Failure)로 이어집니다.

---

## 3. eBPF sockops 및 sk_msg를 통한 혁신적 해결책

Cilium 등 최신 eBPF 기반 네트워킹 스택은 커널 버전 4.14+ 및 5.x+부터 도입된 **소켓 계층 eBPF 프로그램(`BPF_PROG_TYPE_SOCK_OPS`, `BPF_PROG_TYPE_SK_MSG`)**과 **소켓 맵(`BPF_MAP_TYPE_SOCKHASH`, `BPF_MAP_TYPE_SOCKMAP`)**을 결합하여 이 문제를 완벽히 해결합니다.

```
[eBPF 기반 호스트 소켓 다이렉트 바이패스 아키텍처]

App Pod (Socket A)                                       Envoy Pod (Socket B)
    │                                                            ▲
    │ sendmsg() 시스템 콜                                        │ sk_receive_queue
    ▼                                                            │
+───┴────────────────────────────────────────────────────────────┴───+
│ 리눅스 커널 소켓 계층 (Socket Layer)                               │
│                                                                    │
│ 1. BPF_PROG_TYPE_SOCK_OPS (cgroup hook)                            │
│    - TCP 3-Way Handshake 완료 시 (BPF_SOCK_OPS_ACTIVE/PASSIVE_EST) │
│    - 로컬 호스트 소켓임을 감지                                     │
│    - bpf_sock_hash_update() 호출하여 SOCKHASH 맵에 소켓 포인터 등록 │
│                                                                    │
│    [ BPF SOCKHASH Map ]                                            │
│    Key: {10.244.1.15, port_A, 10.244.1.16, port_B} ──> struct sock*│
│                                                                    │
│ 2. BPF_PROG_TYPE_SK_MSG (sk_msg hook)                              │
│    - sendmsg() 버퍼 가로채기                                       │
│    - bpf_msg_redirect_hash(msg, &sock_hash, &key, BPF_F_INGRESS)   │
│    - TCP/IP 스택, Netfilter, iptables, conntrack, veth 완전 스킵!  │
│    - Socket A 송신 페이로드를 Socket B 수신 큐로 즉시 다이렉트 전송! │
+────────────────────────────────────────────────────────────────────+
```

### 3.1 `BPF_PROG_TYPE_SOCK_OPS` (소켓 상태 추적 및 등록)
- cgroup v2 루트 또는 파드의 cgroup에 부착(attach)됩니다.
- 소켓 상태 머신의 전이(State Transition) 이벤트를 가로챕니다:
  - `BPF_SOCK_OPS_ACTIVE_ESTABLISHED_CB`: 클라이언트 소켓의 핸드셰이크 성공.
  - `BPF_SOCK_OPS_PASSIVE_ESTABLISHED_CB`: 서버 소켓의 핸드셰이크 수신 완료.
- 소켓 메타데이터(`sk->sk_rcv_saddr`, `sk->sk_daddr`, 포트 번호 등)를 검사하여 송수신자가 모두 로컬 호스트(동일 커널 인스턴스)에 위치함을 확인합니다.
- 확인된 소켓 객체 포인터(`struct sock *`)를 4-튜플 키와 함께 BPF `SOCKHASH` 또는 `SOCKMAP`에 등록합니다.

### 3.2 `BPF_PROG_TYPE_SK_MSG` (메시지 레벨 직접 리다이렉션)
- BPF 소켓 맵에 부착되는 프로그램입니다.
- 유저 애플리케이션이 `sendmsg()`, `write()`, `sendfile()` 등의 시스템 콜을 실행하는 순간, 커널이 패킷(`sk_buff`)을 생성하고 TCP 세그먼트 헤더를 씌우기 **직전**에 동작합니다.
- `bpf_msg_redirect_hash(msg, &sock_map, &key, BPF_F_INGRESS)` 헬퍼 함수를 호출합니다.
- 이 함수는 송신 버퍼의 데이터 메모리 조각(Scatter-gather memory chunks)을 상대방 수신 소켓(`Socket B`)의 수신 큐(`sk_receive_queue`)로 **직접 이동/포인터 연결**합니다.

### 3.3 로컬 바이패스가 가져오는 극적인 이점
1. **TCP/IP 스택 완전 우회**: IP 계층, FIB 라우팅, TCP SEQ/ACK 세그먼트 생성 연산이 완전히 생략됩니다.
2. **iptables & Netfilter 순회 0건**: 수백~수천 개의 iptables 체인 탐색이 발생하지 않으므로 CPU 사용률이 급감합니다.
3. **conntrack 오염 및 고갈 원천 차단**: 넷필터 훅을 아예 타지 않으므로 `nf_conn` 엔트리가 전혀 생성되지 않습니다. 수십만 건의 단기 연결이 폭증해도 conntrack 테이블은 0개 상태를 유지하여 패킷 드롭이 원천적으로 불가능해집니다.
4. **초저지연(Ultra Low Latency)**: 패킷 처리 지연시간이 기존 $33 \sim 50\,\mu\text{s}$에서 **$4.2\,\mu\text{s}$** 내외로 8배 이상 단축됩니다.

---

## 4. 원격 통신 시의 안전한 폴백(Fallback) 메커니즘

eBPF sockops 및 sk_msg는 로컬 소켓 간의 통신에만 적용 가능합니다. 대상 목적지 IP가 다른 물리 노드(Remote Node)에 있는 파드인 경우:
1. `BPF_PROG_TYPE_SK_MSG`가 `SOCKHASH` 맵을 룩업했을 때 일치하는 소켓 엔트리가 존재하지 않습니다(`NULL` 반환).
2. 이때 프로그램은 `SK_PASS`를 반환하여 커널 표준 TCP/IP 네트워킹 스택(또는 Cilium eBPF TC/XDP 라우팅)으로 안전하게 제어를 넘깁니다.
3. 따라서 로컬 가속의 이점을 극대화하면서도 외부/원격 통신의 호환성과 무중단성을 100% 보장합니다.

---

## 5. 실무 아키텍처 요약 및 성능 지표 비교

| 비교 항목 | 레거시 커널 스택 (`LEGACY_TCP_STACK_VETH`) | eBPF 소켓 바이패스 (`EBPF_SOCKOPS_SK_MSG_BYPASS`) |
| :--- | :--- | :--- |
| **패킷 데이터 경로** | App Socket → TCP → IP → Netfilter → veth → Bridge → veth → Netfilter → IP → TCP → Envoy Socket | App Socket `sendmsg()` → eBPF `sk_msg` 리다이렉션 → Envoy `sk_receive_queue` |
| **TCP/IP 스택 순회** | 2회 완전 순회 (송신 1회 + 수신 1회) | **0회 (완전 바이패스)** |
| **iptables 규칙 평가** | 룰 개수에 비례 ($O(N)$ 지연) | **0건 (평가 안 함)** |
| **conntrack 엔트리 생성** | 연결마다 1개 생성 (테이블 점유) | **0건 (conntrack 완전 미사용)** |
| **대규모 연결 폭증 시** | `nf_conntrack` 테이블 오버플로우로 인한 패킷 드롭 발생 | **테이블 고갈 위험 영구 소멸 (패킷 드롭 0%)** |
| **평균 처리 지연시간** | 약 $30 \sim 55\,\mu\text{s}$ | **약 $4.2\,\mu\text{s}$ (약 8배 향상)** |
| **원격 노드 통신 호환성** | 지원 | SOCKHASH 미스 시 표준 네트워크 경로 자동 폴백 지원 |
