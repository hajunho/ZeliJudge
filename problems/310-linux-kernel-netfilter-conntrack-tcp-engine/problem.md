# 리눅스 커널 넷필터 커넥션 트래킹 및 TCP 상태 엔진 (Linux Kernel Netfilter conntrack & TCP State Engine)

## 문제 설명

대규모 트래픽이 집중되는 이커머스 세일 기간 중, 수만 대의 컨테이너를 운영하는 쿠버네티스 클러스터와 고성능 Nginx API 게이트웨이 노드들의 `dmesg`에 다음과 같은 치명적인 커널 경고가 쏟아지며 서비스 전체가 마비되었습니다:

```
[  412.891024] nf_conntrack: table full, dropping packet
[  412.891089] nf_conntrack: table full, dropping packet
[  412.891150] net_ratelimit: 4520 callbacks suppressed
```

리눅스 커널의 **넷필터 커넥션 트래킹(Netfilter Connection Tracking, `nf_conntrack`)**은 상태 기반 방화벽(`iptables`, `nftables`), 네트워크 주소 변환(NAT), 쿠버네티스 서비스 프록시(`kube-proxy`)의 핵심 기반 서브시스템입니다. 유입되는 모든 패킷에 대해 출발지/목적지 IP, 포트 번호, 프로토콜로 구성된 **5-튜플(5-tuple)**을 추출하고, 왕복 트래픽을 추적하기 위해 **오리지널(Original)** 튜플과 대칭되는 **응답(Reply)** 튜플을 동시에 관리합니다.

또한 TCP 프로토콜 추적기(`net/netfilter/nf_conntrack_proto_tcp.c`)는 패킷의 TCP 플래그(SYN, ACK, FIN, RST)를 분석하여 세션의 상태(`SYN_SENT` $	o$ `SYN_RECV` $	o$ `ESTABLISHED` $	o$ `FIN_WAIT`/`CLOSE_WAIT` $	o$ `TIME_WAIT`/`CLOSE`)를 엄격하게 추적하고 타임아웃 만료 시간을 동적으로 갱신합니다. 정상적으로 3-way 핸드셰이크를 마친 세션에는 `IPS_ASSURED` 플래그가 부여되어 임의로 삭제되지 않도록 보호됩니다.

그러나 `nf_conntrack_max`로 지정된 테이블 한도에 도달하면, 커널은 신규 연결을 수용하기 위해 미확정(`unassured`) 세션이나 종료 단계(`TIME_WAIT`, `CLOSE`)에 있는 세션을 강제 수거하는 **`early_drop()`** 알고리즘을 가동합니다. 만약 수거 가능한 세션이 없다면 신규 SYN 패킷은 즉시 폐기(`DROPPED`)되어 서비스 거부 상태에 빠지게 됩니다.

본 문제는 리눅스 커널 넷필터 커넥션 트래킹 코어(`net/netfilter/nf_conntrack_core.c`)의 상태 머신, 양방향 튜플 인덱싱, 상태 플래그 관리, `early_drop()` 축출 정책 및 SNAT 응답 튜플 변환을 충실하게 모사하는 커널급 상태 추적 엔진을 구현하는 것입니다.

```
                      유입 패킷 (IP/TCP 패킷)
                                |
                                v
               [ 타임아웃 만료 세션 정리 (GC) ]
                                |
                                v
              [ 5-튜플 해시 룩업 (Tuple Lookup) ]
                 /                              \
         (기존 세션 일치)                  (일치 세션 없음)
               |                                  |
    +----------+----------+               +-------+-------+
    | 방향 판별           |               | 비정상 패킷?  |
    | (ORIGINAL vs REPLY) |               | (ACK/RST/FIN) |
    +----------+----------+               +-------+-------+
               |                               /      \
               v                        (INVALID)     (SYN 단독)
       TCP 상태 전이 & 타이머 갱신                     |
    - SYN_SENT -> SYN_RECV                       v
    - SYN_RECV -> ESTABLISHED (IPS_ASSURED)   테이블 용량 확인
    - FIN_WAIT / CLOSE_WAIT                   (len >= max_entries)
    - TIME_WAIT / CLOSE                          /           \
               |                            (여유 있음)   (테이블 포화)
               v                                 |             |
        [ ACCEPTED ]                             |     [ early_drop() 가동 ]
                                                 |     - TIME_WAIT/CLOSE 우선
                                                 |     - 미확정(Non-assured) 수거
                                                 |             |
                                                 |      +------+------+
                                                 |      |             |
                                                 |   (성공)        (실패)
                                                 v      v             v
                                            신규 세션 등록     [ DROPPED ]
                                            (ct_state: NEW)    (table full)
```

---

## 알고리즘 및 상태 전이 명세

### 1. 5-튜플 정의 및 양방향 인덱싱
- **오리지널 튜플 (Original Tuple)**: 유입된 최초 패킷의 5개 필드
  $$	ext{orig\_tuple} = (	ext{src\_ip}, 	ext{dst\_ip}, 	ext{src\_port}, 	ext{dst\_port}, 	ext{protocol})$$
- **응답 튜플 (Reply Tuple)**: 복귀 패킷이 지녀야 할 대칭 튜플
  $$	ext{reply\_tuple} = (	ext{orig.dst\_ip}, 	ext{orig.src\_ip}, 	ext{orig.dst\_port}, 	ext{orig.src\_port}, 	ext{protocol})$$
- **SNAT 룰 적용 시**: 신규 연결 생성 시 일치하는 SNAT 룰(`match_src_ip`)이 존재하면, `reply_tuple`의 `dst_ip`와 `dst_port`를 각각 변환된 `to_source_ip`, `to_source_port`로 재작성합니다.

### 2. 세션 수명 주기 및 상태 비트 플래그 (Status Flags)
- `IPS_CONFIRMED`: 패킷이 넷필터 체인을 정상 통과하여 세션 테이블에 안착함.
- `IPS_SEEN_REPLY`: 대칭 방향인 `reply_tuple`과 일치하는 응답 패킷이 최초로 수신됨.
- `IPS_ASSURED`: 양방향 통신이 정상 확립되어 `ESTABLISHED` 상태에 도달함 (우선순위 축출 보호).

### 3. TCP 상태 머신 전이 규칙
기본 타임아웃(`timeouts`) 기본값:
- `SYN_SENT`: 120초
- `SYN_RECV`: 60초
- `ESTABLISHED`: 432000초
- `FIN_WAIT`: 120초
- `CLOSE_WAIT`: 60초
- `LAST_ACK`: 30초
- `TIME_WAIT`: 120초
- `CLOSE`: 10초

각 패킷 수신 시:
1. **만료 검사**: `conn.timeout_expires <= packet.timestamp`인 모든 세션을 테이블에서 즉시 제거합니다.
2. **방향 일치 판정**:
   - `orig_tuple`과 일치 $\implies$ `ORIGINAL` 방향
   - `reply_tuple`과 일치 $\implies$ `REPLY` 방향
3. **상태 전이**:
   - `ORIGINAL` 방향:
     - `SYN_RECV` 상태에서 `ACK` 수신 $\implies$ `ESTABLISHED`, `IPS_ASSURED` 플래그 추가
     - `ESTABLISHED` 상태에서 `FIN` 수신 $\implies$ `FIN_WAIT`
     - `ESTABLISHED` 상태에서 `RST` 수신 $\implies$ `CLOSE`
     - `CLOSE_WAIT` 상태에서 `FIN` 수신 $\implies$ `LAST_ACK`
     - `LAST_ACK` 상태에서 `ACK` 수신 $\implies$ `CLOSE`
   - `REPLY` 방향 (`IPS_SEEN_REPLY` 플래그 추가):
     - `SYN_SENT` 상태에서 `SYN` + `ACK` 수신 $\implies$ `SYN_RECV`
     - `SYN_SENT` 상태에서 `RST` 수신 $\implies$ `CLOSE`
     - `ESTABLISHED` 상태에서 `FIN` 수신 $\implies$ `CLOSE_WAIT`
     - `ESTABLISHED` 상태에서 `RST` 수신 $\implies$ `CLOSE`
     - `FIN_WAIT` 상태에서 `ACK` 또는 `FIN` 수신 $\implies$ `TIME_WAIT`
     - `LAST_ACK` 상태에서 `ACK` 수신 $\implies$ `CLOSE`
4. 상태 전이 후:
   $$	ext{timeout\_expires} = 	ext{packet.timestamp} + 	ext{timeouts}[new\_state]$$
   누적 패킷 수 및 바이트 수(페이로드)를 방향별로 가산합니다.
   판정: `ACCEPTED`, `ct_state = "ESTABLISHED"`.

### 4. 미확립 패킷 및 신규 연결 생성 / `early_drop()`
기존 연결이 없는 패킷:
- **SYN 플래그가 없거나(ACK, RST, FIN 단독) 또는 SYN+ACK인 경우**:
  - 정상적인 핸드셰이크 개시 패킷이 아님 $\implies$ 판정: `INVALID`, `ct_state = "INVALID"`.
- **순수 SYN 패킷인 경우 (`SYN` 포함, `ACK` 미포함)**:
  - 현재 활성 세션 수가 `nf_conntrack_max` 이상인 경우 **`early_drop()`** 실행:
    - 축출 후보 우선순위:
      1. 종료 단계 세션: `TIME_WAIT` 또는 `CLOSE`
      2. 미확정 세션: `IPS_ASSURED` 플래그가 없는 세션 (예: `SYN_SENT`, `SYN_RECV`)
      3. 위 조건 내에서는 `last_updated_time`이 가장 오래된 세션 우선
    - 적합한 세션이 발견되면 해당 세션을 테이블에서 강제 추방하고 `early_drop_evictions_count`를 1 증가시킵니다.
    - 만약 모든 세션이 `IPS_ASSURED` 상태의 활성 세션이라 수거할 수 없다면:
      - 판정: `DROPPED`, `ct_state = "INVALID"`, 사유: `"nf_conntrack: table full, dropping packet"`.
  - 여유 공간이 확보되면 새로운 세션 `ct-XXXX`를 할당하고 `SYN_SENT` 상태 및 `IPS_CONFIRMED` 플래그로 테이블에 삽입합니다.
    - 판정: `ACCEPTED`, `ct_state = "NEW"`.

---

## 입력 형식 (Input JSON Schema)

```json
{
  "config": {
    "nf_conntrack_max": 2,
    "timeouts": {
      "SYN_SENT": 120.0,
      "ESTABLISHED": 432000.0
    }
  },
  "nat_rules": [
    {
      "type": "SNAT",
      "match_src_ip": "192.168.1.50",
      "to_source_ip": "203.0.113.5",
      "to_source_port": 60001
    }
  ],
  "packets": [
    {
      "timestamp": 10.0,
      "src_ip": "192.168.1.50",
      "dst_ip": "93.184.216.34",
      "src_port": 49152,
      "dst_port": 80,
      "protocol": "TCP",
      "tcp_flags": ["SYN"],
      "payload_bytes": 0
    }
  ]
}
```

---

## 출력 형식 (Output JSON Schema)

```json
{
  "summary": {
    "total_packets_processed": 1,
    "accepted_packets": 1,
    "dropped_packets": 0,
    "invalid_packets": 0,
    "conntrack_table_peak_size": 1,
    "conntrack_table_final_size": 1,
    "early_drop_evictions_count": 0,
    "active_established_count": 0
  },
  "packet_verdicts": [
    {
      "packet_index": 1,
      "verdict": "ACCEPTED",
      "ct_state": "NEW",
      "tcp_state": "SYN_SENT",
      "reason": "New connection tracked"
    }
  ],
  "active_connections": [
    {
      "conn_id": "ct-0001",
      "orig_tuple": {
        "src_ip": "192.168.1.50",
        "dst_ip": "93.184.216.34",
        "src_port": 49152,
        "dst_port": 80,
        "protocol": "TCP"
      },
      "reply_tuple": {
        "src_ip": "93.184.216.34",
        "dst_ip": "203.0.113.5",
        "src_port": 80,
        "dst_port": 60001,
        "protocol": "TCP"
      },
      "tcp_state": "SYN_SENT",
      "status_flags": ["IPS_CONFIRMED"],
      "packets_orig": 1,
      "bytes_orig": 0,
      "packets_reply": 0,
      "bytes_reply": 0,
      "remaining_ttl": 120.0
    }
  ]
}
```

---

## 제약 조건

- $1 \le 	ext{packets} \le 1,000$
- $1 \le 	ext{nf\_conntrack\_max} \le 65,536$
- 포트 번호 범위: $1 \le 	ext{port} \le 65,535$
- 시간 단위: 초(second) 단위의 부동소수점 (`float`)
- 표준 입력(`sys.stdin`)으로부터 UTF-8 JSON 문자열을 수신하고, 결과를 `json.dumps(..., ensure_ascii=False)`로 표준 출력에 인쇄합니다.
