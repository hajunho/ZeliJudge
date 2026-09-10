# 리눅스 커널 Netfilter conntrack 헬퍼 및 NAT ALG 엔진 (Linux Kernel Netfilter conntrack Helper & NAT ALG Engine)

## 문제 설명

전통적인 네트워크 방화벽과 NAT(네트워크 주소 변환) 라우터는 전송 계층의 5-튜플(`src_ip`, `dst_ip`, `src_port`, `dst_port`, `proto`)만을 검사하여 상태를 추적(`nf_conntrack`)하고 주소를 변환합니다. 그러나 **FTP (Active/Passive), SIP (VoIP), H.323, IRC DCC**와 같은 다중 채널 복합 프로토콜은 데이터 전송을 위한 동적 포트 번호와 사설 IP 주소를 **애플리케이션 계층 페이로드 내부**에 텍스트 형태로 직접 포함하여 전송합니다.

이로 인해 두 가지 치명적인 문제가 발생합니다:
1. **방화벽 핀홀(Pinhole) 문제**: 클라이언트와 서버가 제어 채널을 통해 동적으로 협상한 데이터 포트는 사전에 열려 있지 않으므로, 상태 기반 방화벽이 외부에서 들어오는 데이터 연결을 차단해 버립니다.
2. **사설 IP 누출 및 패킷 크기 변경(TCP Sequence Desynchronization)**: NAT 게이트웨이가 페이로드 내부의 사설 IP(`10.0.0.2`)를 공인 IP(`203.0.113.195`)로 변환(Mangle)하면 페이로드 길이가 늘어나거나 줄어듭니다. 이로 인해 TCP 시퀀스 번호($seq$)와 확인 응답 번호($ack$)가 어긋나 TCP 연결이 즉각 파탄에 이릅니다.

리눅스 커널은 **Netfilter conntrack 헬퍼(`net/netfilter/nf_conntrack_helper.c`, `nf_conntrack_ftp.c`)**와 **NAT 헬퍼(`net/netfilter/nf_nat_helper.c`)** 서브시스템을 통해 이 문제를 해결합니다:
- **애플리케이션 계층 게이트웨이(ALG)**: 제어 패킷의 페이로드를 실시간 심층 검사(DPI)하여 동적 포트 협상 명령(`PORT`, `227 Entering Passive Mode`, `c=IN IP4`, `m=audio`)을 파싱합니다.
- **동적 기대치(Expectation, `struct nf_conntrack_expect`)**: 향후 유입될 데이터 연결을 위한 임시 방화벽 핀홀을 특정 피어 및 포트에 한해 제한된 시간 동안 개방하고, 해당 패킷이 도착하면 `RELATED` 상태로 안전하게 허용합니다.
- **TCP 시퀀스 번호 맹글링 및 오프셋 보정(`nf_nat_mangle_tcp_packet`)**: 페이로드 치환으로 발생한 길이 차이($\Delta$)를 누적 추적하여, 이후 전송되는 모든 송신 패킷의 $seq$와 수신 패킷의 $ack$를 커널에서 투명하게 자동 보정합니다.

당신은 리눅스 커널 네트워크 및 보안 서브시스템 엔지니어로서, **FTP / SIP 제어 채널 심층 분석, NAT 페이로드 맹글링, TCP $seq$/$ack$ 오프셋 보정기, 기대치(Expectation) 라이프사이클 및 `RELATED` 연결 상태 머신 엔진**을 구현해야 합니다.

```
+-------------------------------------------------------------------------+
|     Linux Kernel Netfilter conntrack Helper & NAT ALG Architecture      |
+-------------------------------------------------------------------------+
| [Client (Private: 10.0.0.2)]                                            |
|   Sends FTP "PORT 10,0,0,2,195,80" ---> [NAT Gateway: netfilter]       |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
| [Kernel Space: net/netfilter/]                                          |
|                                                                         |
|  +-------------------------------------------------------------------+  |
|  | 1. ALG Deep Packet Inspection (nf_conntrack_ftp.c)                |  |
|  |    - Parses IP:Port in Application Payload                        |  |
|  |    - Allocates Public NAT Data Port (e.g. 40001)                  |  |
|  +---------------------------------+---------------------------------+  |
|                                    |                                    |
|                                    v                                    |
|  +---------------------------------+---------------------------------+  |
|  | 2. NAT Payload Mangling (nf_nat_helper.c)                          |  |
|  |    - Rewrites: "PORT 203,0,113,195,156,65"                        |  |
|  |    - Calculates Delta: len(new) - len(old)                        |  |
|  |    - Updates Cumulative TCP Seq Offset (seq_offset_outbound)      |  |
|  +---------------------------------+---------------------------------+  |
|                                    |                                    |
|                                    v                                    |
|  +---------------------------------+---------------------------------+  |
|  | 3. Expectation Registration (nf_ct_expect_alloc)                  |  |
|  |    - Registers Expectation: [Server IP ---> NAT IP:40001]         |  |
|  |    - Sets Expiration Timer (timeout_ticks)                        |  |
|  +---------------------------------+---------------------------------+  |
|                                    |                                    |
|                                    v                                    |
|  +-------------------------------------------------------------------+  |
|  | 4. Incoming Data Connection Match (nf_conntrack_in)               |  |
|  |    - Checks Expectation Table: Matched!                           |  |
|  |    - Creates "RELATED" Connection to Master Session               |  |
|  |    - Removes Expectation & Permits Pinhole Ingress                |  |
|  +-------------------------------------------------------------------+  |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
| [External Server (198.51.100.1)]                                        |
+-------------------------------------------------------------------------+
```

---

## 엔진 규격 및 알고리즘

### 1. 세션 초기화 (`config`)
- `nat_public_ip`: NAT 라우터의 공인 IP (예: `"203.0.113.195"`)
- `nat_port_range`: 할당 가능한 공인 포트 범위 `[min_port, max_port]`
- `expect_timeout_ticks`: 기대치 기본 만료 시간 (틱 단위, 기본값: 30)

### 2. 제어 연결 생성 (`CREATE_MASTER`)
- `proto`: `"TCP"` 또는 `"UDP"`
- `src_ip`, `src_port`: 클라이언트 사설 주소
- `dst_ip`, `dst_port`: 목적지 서버 주소
- `helper_name`: 활성화할 헬퍼 (`"ftp"` 또는 `"sip"`)
- 생성 시 상태는 `"ESTABLISHED"`로 초기화되며, $seq\_offset = 0$으로 설정됩니다.

### 3. 패킷 처리 및 맹글링 (`PROCESS_PACKET`)
- 입력: `ct_id`, `direction` (`"OUTBOUND"` 또는 `"INBOUND"`), `seq`, `ack`, `payload`
1. **TCP 시퀀스/확인응답 보정**:
   - `OUTBOUND` (클라이언트 $	o$ 서버):
     $$adj\_seq = seq + seq\_offset\_outbound$$
     $$adj\_ack = ack - seq\_offset\_inbound$$
   - `INBOUND` (서버 $	o$ 클라이언트):
     $$adj\_seq = seq + seq\_offset\_inbound$$
     $$adj\_ack = ack - seq\_offset\_outbound$$
2. **FTP 능동 모드 (`PORT h1,h2,h3,h4,p1,p2`)**:
   - 클라이언트 사설 IP/포트를 NAT 공인 IP 및 신규 할당된 데이터 포트로 치환.
   - $\Delta = 	ext{len}(new) - 	ext{len}(old)$를 `seq_offset_outbound`에 누적.
   - 서버 $	o$ NAT 공인 IP:데이터 포트로 향하는 TCP 기대치 등록.
3. **FTP 수동 모드 (`227 Entering Passive Mode (...)`)**:
   - 서버가 수신 대기 중인 데이터 IP/포트를 파싱하여, 클라이언트 $	o$ 서버 데이터 IP/포트로 향하는 TCP 기대치 등록.
4. **SIP / SDP (`c=IN IP4`, `m=audio`)**:
   - 사설 RTP IP/포트를 NAT 공인 IP 및 신규 할당된 UDP 포트로 치환.
   - UDP 오디오 스트림 수신을 위한 기대치 등록.

### 4. 데이터 연결 기대치 매칭 (`MATCH_DATA`)
- 유입된 패킷의 `proto`, `dst_ip`, `dst_port`가 활성 기대치 테이블에 존재하는지 확인:
  - **일치 시**: 기대치를 소진(제거)하고, 마스터 연결에 종속된 **`"RELATED"`** 상태의 신규 연결 생성 (`"ACCEPTED_RELATED"` 반환).
  - **불일치 시**: 방화벽 핀홀이 없으므로 패킷 즉시 폐기 (`"DROPPED_BY_FIREWALL"` 반환).

### 5. 타이머 틱 (`TICK`)
- 시간을 `ticks`만큼 전진시키고, `expires_tick <= current_tick`인 만료된 기대치를 자동 제거.

---

## 입력 형식

표준 입력(`sys.stdin`)으로 JSON 객체가 주어집니다:
```json
{
  "config": {
    "nat_public_ip": "203.0.113.195",
    "nat_port_range": [40000, 50000],
    "expect_timeout_ticks": 30
  },
  "operations": [
    {"op": "CREATE_MASTER", "proto": "TCP", "src_ip": "10.0.0.2", "src_port": 50000, "dst_ip": "198.51.100.1", "dst_port": 21, "helper_name": "ftp"},
    {"op": "PROCESS_PACKET", "ct_id": 1, "direction": "OUTBOUND", "seq": 1000, "ack": 2000, "payload": "PORT 10,0,0,2,195,80
"},
    {"op": "MATCH_DATA", "proto": "TCP", "src_ip": "198.51.100.1", "src_port": 20, "dst_ip": "203.0.113.195", "dst_port": 40001}
  ]
}
```

---

## 출력 형식

표준 출력(`sys.stdout`)으로 공백 없는 압축 JSON(`separators=(',', ':')`)을 출력합니다:
```json
{
  "execution_log": [
    {"op": "CREATE_MASTER", "result": {"ct_id": 1, "status": "CREATED"}},
    {
      "op": "PROCESS_PACKET",
      "result": {
        "adj_ack": 2000,
        "adj_seq": 1000,
        "direction": "OUTBOUND",
        "expectation_created_id": 1,
        "mangled": true,
        "orig_ack": 2000,
        "orig_seq": 1000,
        "payload": "PORT 203,0,113,195,156,65
",
        "status": "PROCESSED"
      }
    },
    {
      "op": "MATCH_DATA",
      "result": {
        "matched_expect_id": 1,
        "related_ct_id": 2,
        "status": "ACCEPTED_RELATED",
        "translated_dst": "10.0.0.2:50000"
      }
    }
  ],
  "final_summary": {
    "active_connections_count": 2,
    "active_expectations_count": 0,
    "connections": [
      {
        "ct_id": 1,
        "dst": "198.51.100.1:21",
        "seq_offset_inbound": 0,
        "seq_offset_outbound": 4,
        "src": "10.0.0.2:50000",
        "state": "ESTABLISHED"
      },
      {
        "ct_id": 2,
        "dst": "203.0.113.195:40001",
        "seq_offset_inbound": 0,
        "seq_offset_outbound": 0,
        "src": "198.51.100.1:20",
        "state": "RELATED"
      }
    ],
    "current_tick": 0,
    "expectations": [],
    "stats": {
      "bytes_payload_delta": 4,
      "expectations_created": 1,
      "expectations_expired": 0,
      "expectations_fulfilled": 1,
      "packets_mangled": 1,
      "packets_processed": 2,
      "related_connections_created": 1
    }
  }
}
```
