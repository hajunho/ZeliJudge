# 리눅스 커널 넷필터 커넥션 트래킹(conntrack) 및 상태 머신 아키텍처 백서 (Theoretical Background)

## 1. 개요: 넷필터 훅과 상태 추적의 필요성

리눅스 커널의 네트워크 스택에서 **넷필터(Netfilter)**는 패킷이 통과하는 핵심 경로마다 5개의 고정 훅(Hook) 포인트를 제공합니다:
1. `NF_INET_PRE_ROUTING`: 네트워크 인터페이스로 패킷이 수신된 직후, 라우팅 결정 이전
2. `NF_INET_LOCAL_IN`: 로컬 호스트(소켓)로 향하는 패킷
3. `NF_INET_FORWARD`: 다른 호스트로 포워딩되는 패킷
4. `NF_INET_LOCAL_OUT`: 로컬 호스트 프로세스가 전송한 패킷
5. `NF_INET_POST_ROUTING`: 라우팅 결정 후, 물리 인터페이스로 송출되기 직전

단순 무상태(Stateless) 패킷 필터링은 각 패킷을 독립적으로만 검사하므로, "이 패킷이 내가 요청한 HTTP 웹서버의 정상적인 응답인가, 아니면 외부 공격자가 무단으로 침투시킨 가짜 패킷인가?"를 판별할 수 없습니다.

이를 해결하기 위해 도입된 서브시스템이 **`nf_conntrack` (Connection Tracking)**입니다. `PREROUTING` 및 `LOCAL_OUT` 단계의 최우선 순위에서 유입/유출 패킷을 가로채 연결 상태(State)를 확립하고, iptables/nftables의 `-m state --state ESTABLISHED,RELATED -j ACCEPT` 규칙을 통해 신뢰할 수 있는 트래픽만을 초고속으로 통과시킵니다.

---

## 2. 5-튜플 해시와 양방향 튜플 인덱싱 (`struct nf_conn`)

커널 내부에서 하나의 논리적 연결은 `struct nf_conn` 객체로 표현됩니다 (`include/net/netfilter/nf_conntrack.h`):

```c
struct nf_conntrack_tuple {
    struct nf_conntrack_man src;
    struct {
        union nf_inet_addr u3;
        union {
            __be16 all;
            struct { __be16 port; } tcp;
            ...
        } u;
        u_int8_t protonum;
        u_int8_t dir;
    } dst;
};

struct nf_conntrack_tuple_hash {
    struct hlist_nulls_node hnnode;
    struct nf_conntrack_tuple tuple;
};

struct nf_conn {
    ...
    struct nf_conntrack_tuple_hash tuplehash[IP_CT_DIR_MAX]; // [0]=ORIGINAL, [1]=REPLY
    unsigned long status;                                   // IPS_CONFIRMED, IPS_ASSURED 등
    struct timer_list timeout;
    ...
};
```

1. **양방향 튜플 쌍 (`tuplehash`)**:
   - `IP_CT_DIR_ORIGINAL`: 클라이언트 $	o$ 서버로 향하는 최초 패킷의 5-튜플.
   - `IP_CT_DIR_REPLY`: 서버 $	o$ 클라이언트로 돌아오는 기대 응답의 5-튜플.
   - 두 튜플 모두 글로벌 커넥션 트래킹 해시 테이블(`nf_conntrack_hash`)에 독립적으로 삽입되어 있어, 어떤 방향에서 패킷이 도착하더라도 $O(1)$에 동일한 `struct nf_conn` 세션을 찾아낼 수 있습니다.
2. **NAT 주소 변환과의 결합**:
   - SNAT(Source NAT)가 수행되면, 커널은 `reply_tuple`의 목적지 IP/포트를 공인 IP/포트로 사전에 재작성합니다.
   - 따라서 외부 인터넷에서 변환된 주소로 회신이 오더라도 `reply_index` 해시 조회를 통해 단번에 내부 사설망 호스트의 연결로 역매핑됩니다.

---

## 3. TCP 프로토콜 상태 머신 (`nf_conntrack_proto_tcp.c`)

TCP 연결 추적은 RFC 793의 유한 상태 머신(FSM)을 따릅니다:

```
 [CLIENT]                                   [SERVER]
    |                                          |
    | ----- SYN (NEW, SYN_SENT) -------------> |  (IPS_CONFIRMED)
    |                                          |
    | <---- SYN+ACK (ESTABLISHED, SYN_RECV) -- |  (IPS_SEEN_REPLY)
    |                                          |
    | ----- ACK (ESTABLISHED, ESTABLISHED) --> |  (IPS_ASSURED)
    |                                          |
    | ===== 데이터 양방향 전송 (ESTABLISHED) ==== |
    |                                          |
    | ----- FIN+ACK (FIN_WAIT) --------------> |
    | <---- ACK (CLOSE_WAIT) ----------------- |
    | <---- FIN+ACK (LAST_ACK) --------------- |
    | ----- ACK (TIME_WAIT -> CLOSE) --------> |
```

- **`IPS_ASSURED` 플래그의 중요성**:
  - 3-way 핸드셰이크의 마지막 클라이언트 `ACK`가 도달하기 전까지 세션은 미확정(`unassured`) 상태입니다.
  - SYN Flood 공격이나 비정상 단방향 스캔 패킷은 `IPS_ASSURED`를 획득하지 못하므로, 테이블이 부족해질 때 우선적으로 강제 축출 대상이 됩니다.

---

## 4. 커넥션 트래킹 테이블 고갈과 `early_drop()` 메커니즘

서버가 초당 수만 건의 연결을 처리하거나 DDoS 공격에 노출되면 `len(table) >= nf_conntrack_max` 상황이 발생합니다.

리눅스 커널의 `early_drop()` 함수 (`net/netfilter/nf_conntrack_core.c`):
1. **우선순위 1 (`TIME_WAIT`, `CLOSE`)**:
   - 이미 종료 절차를 밟은 세션은 살아있는 연결에 지장을 주지 않으므로 최우선 제거됩니다.
2. **우선순위 2 (미확정 세션, `!IPS_ASSURED`)**:
   - 3-way 핸드셰이크를 완료하지 못한 `SYN_SENT` 상태의 세션들을 축출합니다. 이는 정상적인 기존 통신을 보호하면서 가짜 SYN 연결의 공간 점유를 방어합니다.
3. **완전 고갈 시의 패킷 폐기 (Hard Drop)**:
   - 만약 테이블 내부의 모든 슬롯이 활성 상태인 `IPS_ASSURED` 세션으로 꽉 차 있다면, 커널은 어떠한 세션도 임의로 끊을 수 없으므로 신규 유입 패킷을 즉시 폐기하고 `nf_conntrack: table full, dropping packet` 커널 메시지를 발생시킵니다.

---

## 5. 실무 커널 파라미터 튜닝 가이드

쿠버네티스 노드나 대용량 웹 프록시에서 conntrack 고갈을 방지하기 위한 표준 튜닝 공식:

1. **테이블 크기 및 버킷 산정**:
   $$	ext{nf\_conntrack\_max} = 	ext{nf\_conntrack\_buckets} 	imes 4$$
   예: 64GB RAM 서버 기준:
   ```bash
   sysctl -w net.netfilter.nf_conntrack_max=1048576
   echo 262144 > /sys/module/nf_conntrack/parameters/hashsize
   ```
2. **메모리 오버헤드 계산**:
   - `struct nf_conn` 객체 1개당 약 320바이트 점유
   - 100만 개 세션 $pprox 1,000,000 	imes 320 	ext{ B} pprox 320 	ext{ MB}$ (매우 경제적)
3. **타임아웃 단축을 통한 빠른 회수**:
   ```bash
   # 기본 5일(432000s)인 ESTABLISHED 타임아웃을 1시간(3600s)으로 축소
   sysctl -w net.netfilter.nf_conntrack_tcp_timeout_established=3600
   # TIME_WAIT 타임아웃을 30초로 단축
   sysctl -w net.netfilter.nf_conntrack_tcp_timeout_time_wait=30
   ```
