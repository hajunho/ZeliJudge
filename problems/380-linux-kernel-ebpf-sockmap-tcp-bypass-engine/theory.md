# Linux 커널 네트워킹과 eBPF sockmap: sk_msg 제로카피 TCP 바이패스 아키텍처

## 1. 개요 및 마이크로서비스 네트워크의 구조적 병목

클라우드 네이티브 컴퓨팅과 쿠버네티스(Kubernetes) 환경에서 애플리케이션 아키텍처는 거대한 모놀리스(Monolith)에서 수십~수백 개의 잘게 쪼개진 마이크로서비스(Microservices)로 분화되었습니다. 또한 트래픽 제어, mTLS 암호화, 가시성 확보를 위해 서비스 메시(Service Mesh: Istio, Linkerd, Consul)를 도입하면서 각 애플리케이션 파드(Pod)마다 사이드카 프록시(Envoy Proxy)가 나란히 배치되는 구조가 표준화되었습니다.

이러한 아키텍처에서 발생하는 심각한 문제는 **네트워크 트래픽의 극단적인 동-서(East-West) 방향 집중**과 **로컬 루프백 통신의 폭증**입니다:
- 하나의 사용자 요청을 처리하기 위해 동일한 물리 노드(Host Node) 내부에서 애플리케이션 컨테이너와 Envoy 프록시 간, 혹은 같은 워커 노드에 스케줄링된 파드 $A$와 파드 $B$ 간에 수차례의 로컬 TCP 연결이 맺어집니다.
- 전통적인 리눅스 커널 네트워킹에서 로컬 TCP 통신은 물리적 케이블(NIC)만 타지 않을 뿐, 커널 내부의 모든 복잡한 소프트웨어 계층(TCP 세그먼테이션, 버퍼링, L3 라우팅, conntrack, iptables, veth 페어, softirq 등)을 그대로 관통합니다.
- 연구에 따르면 Envoy 사이드카를 거치는 것만으로 레이턴시가 $2\sim 3\text{배}$ 증가하고 전체 클러스터 CPU의 최대 20~30%가 순수 커널 TCP/IP 패킷 처리에 낭비됩니다.

---

## 2. eBPF sockmap 서브시스템의 탄생과 설계 철학

Linux 커널 4.14에서 Daniel Borkmann과 John Fastabend 등에 의해 도입된 **`BPF_MAP_TYPE_SOCKMAP` / `SOCKHASH`**와 **`BPF_PROG_TYPE_SK_MSG`**는 이 구조적 병목을 해결하기 위해 고안되었습니다:

> **"두 소켓이 모두 동일한 물리 노드의 동일한 커널 인스턴스에 존재한다면, 왜 굳이 IP 패킷을 만들고, 라우팅 테이블을 뒤지고, 방화벽(conntrack)을 검색하고, 루프백 디바이스 큐에 넣어야 하는가? 송신 소켓의 버퍼를 수신 소켓의 큐로 직접 꽂아버리면(Splice) 되지 않는가?"**

eBPF sockmap은 유저 공간 소켓과 커널 TCP/IP 스택 사이의 인터페이스를 가로채어, 전통적인 L3/L4 스택을 **완전히 건너뛰는(Short-Circuit / Zero-Copy Bypass)** 고속 데이터 패스를 제공합니다.

---

## 3. 핵심 아키텍처 컴포넌트

### 3.1 BPF_MAP_TYPE_SOCKMAP 및 SOCKHASH
- 커널 내부의 활성 TCP 소켓 포인터(`struct sock *`)를 저장하는 특수 BPF 맵입니다.
- `SOCKMAP`: 1차원 정수 인덱스 기반 배열형 맵.
- `SOCKHASH`: 소켓의 4-Tuple(로컬 IP, 로컬 포트, 원격 IP, 원격 포트) 해시 키를 사용하는 연관 해시 맵.
- 소켓이 맵에 등록되면 커널은 해당 소켓의 통신 연산 함수 테이블(`proto_ops`)을 가로채어 BPF 전용 콜백(`bpf_tcp_msg_ops`)으로 교체합니다.

### 3.2 BPF_PROG_TYPE_SOCK_OPS (연결 수립 추적)
- cgroup v2 단위로 연결되어 소켓 라이프사이클 이벤트를 모니터링합니다:
  - `BPF_SOCK_OPS_ACTIVE_ESTABLISHED_CB`: 클라이언트 소켓의 `connect()` 완료 시점.
  - `BPF_SOCK_OPS_PASSIVE_ESTABLISHED_CB`: 서버 소켓의 `accept()` 완료 시점.
- 소켓의 양 끝단 IP가 동일 호스트의 로컬 파드 서브넷(예: `10.244.0.0/16` 또는 `127.0.0.1`)에 속하는지 확인한 후, 맵에 소켓을 자동 등록합니다:
  ```c
  bpf_sock_hash_update(skops, &sock_hash, &key, BPF_NOEXIST);
  ```

### 3.3 BPF_PROG_TYPE_SK_MSG (송신 버딕트 결정)
- 애플리케이션이 `sendmsg()`, `write()`, `send()` 시스템 콜을 호출할 때 커널 공간에서 가장 먼저 실행됩니다.
- 송신 버퍼(`struct sk_msg`)를 파싱하여 L7 프로토콜(HTTP, gRPC, Redis 등) 헤더를 검사할 수 있습니다:
  - `SK_DROP`: 악성 요청, 비인가 쿼리 탐지 시 소켓 레벨에서 즉시 폐기.
  - `SK_PASS`: 외부 원격 IP로 나가는 트래픽이거나 검사가 필요할 때 전통적 TCP/IP 스택으로 정상 전달.
  - `bpf_msg_redirect_hash(msg, &sock_hash, &key, BPF_F_INGRESS)`: 목적지 소켓의 수신 큐(`sk_receive_queue`)로 메모리 페이지를 직접 매핑하여 전달!

---

## 4. 제로카피 바이패스 메커니즘과 성능 이점

### 4.1 생략되는 커널 서브시스템 목록
eBPF sockmap 리다이렉션이 일어날 때 완전히 생략되는 단계들:
1. **TCP 세그먼테이션(Segmentation)**: 4KB 페이지를 MTU(1500B) 단위 패킷들로 분할하는 연산 제거.
2. **TCP 혼잡 제어(Congestion Control)**: 인위적인 CWND(Congestion Window) 제약 및 슬로우 스타트 제거.
3. **L3 IP 라우팅 검색**: `FIB(Forwarding Information Base)` 룩업 캐시 미스 제거.
4. **Netfilter / iptables / conntrack**: 패킷당 수백 나노초씩 소모되는 NAT 테이블 탐색 및 연결 추적 락(Lock) 경합 100% 제거.
5. **가상 이더넷(`veth`) 및 qdisc**: 패킷 큐잉, 드롭, 인터럽트 락 제거.
6. **SoftIRQ 스케줄링**: `ksoftirqd` 비동기 지연 제거.
7. **TCP ACK 패킷 생성 및 전송**: 불필요한 양방향 왕복 핸드셰이크 트래픽 제거.

### 4.2 코킹(Corking)을 통한 배치 최적화
gRPC 스트리밍이나 작은 센서 텔레메트리 데이터가 빈번히 발생할 때, 매 호출마다 리다이렉트 인터럽트를 발생시키면 오버헤드가 발생합니다.
`bpf_msg_cork_bytes(msg, bytes)`는 설정된 바이트 임계치에 도달할 때까지 송신을 지연시켰다가 한꺼번에 목적지 소켓으로 방출함으로써 컨텍스트 스위칭 횟수를 최대 80% 이상 절감합니다.

---

## 5. 실무 응용: Cilium Service Mesh와 차세대 클라우드 인프라

오픈소스 클라우드 네이티브 네트워킹 프로젝트인 **Cilium**은 버전 1.12부터 eBPF sockmap을 활용하여 전통적인 Istio/Envoy의 성능 한계를 극복했습니다:
- **Envoy 사이드카 가속**: Envoy 프록시와 로컬 앱 사이의 왕복 루프백 지연시간을 $30\mu\text{s} \rightarrow 4\mu\text{s}$ 수준으로 $80\%+$ 단축.
- **Sidecarless Service Mesh (Ambient Mesh)**: 노드당 단일 프록시 모델에서 노드 내 모든 파드 간 통신을 제로카피로 중계.
- **CPU 및 전력 절감**: 하이퍼스케일러 데이터센터에서 네트워크 패킷 처리에 소모되던 수만 코어의 CPU를 비즈니스 로직 연산으로 환원.
