# #154 HTTP/2로 바꿨더니 지하철에서 왜 이미지가 전부 멈춰버려요?!: TCP 계층 Head-of-Line(HoL) 블로킹 참사와 HTTP/3 QUIC 독립 스트림 및 연결 마이그레이션 (TCP Head-of-Line Blocking in HTTP/2 vs HTTP/3 QUIC)

## 1. 실무 장애 시나리오: "HTTP/2로 올렸는데 왜 지하철에서 앱이 먹통이 돼요?!"

글로벌 이커머스 쇼핑 앱 '젤리익스프레스'의 프론트엔드/인프라 팀 엔지니어 준호는 서비스 로딩 속도를 혁신하기 위해 구형 **HTTP/1.1**에서 최신 **HTTP/2**로 전면 업그레이드를 단행했습니다.

사무실 초고속 사내 Wi-Fi와 유선망 환경에서 사내 테스트를 진행했을 때 결과는 환상적이었습니다:
* 단일 TCP 연결 상에서 16개 이상의 이미지와 JS 번들이 바이너리 프레임으로 다중화(Multiplexing)되어 초고속으로 수신됨.
* 6개의 TCP 커넥션을 맺느라 발생하던 3-Way Handshake와 Slow-Start 오버헤드가 완전히 제거됨.
* 웹 및 앱 로딩 속도가 2배 이상 빨라져 경영진과 팀원 모두 환호했습니다.

그러나 프로덕션 배포 직후, 출퇴근 시간(08:30 ~ 09:30)만 되면 앱 스토어에 1점짜리 분노의 리뷰가 폭주하기 시작했습니다:
> *"지하철 2호선 타고 가는데 상품 목록 사진들이 전부 회색 박스로 멈춘 채 10초 동안 아무것도 안 뜹니다!"*  
> *"사무실 나가서 엘리베이터 타거나 Wi-Fi 끊길 때마다 화면이 하얗게 굳어버려요!"*

준호는 실시간 무선망 APM(Application Performance Monitoring) 지표를 열어보고 경악했습니다:
* 패킷 손실률이 0%인 청정 네트워크에서는 HTTP/2가 압도적으로 빨랐음.
* 하지만 **패킷 손실률이 2% ~ 5% 발생하는 지하철/모바일 환경에서는 HTTP/2의 페이지 완주 시간이 HTTP/1.1보다 3~4배 더 느려지는 기괴한 역전 현상**이 발생하고 있었음!

긴급 소집된 네트워크 수석 아키텍트 민우 님이 화이트보드에 패킷 전송 타임라인을 그리며 원인을 짚어주었습니다:

> "준호 님! HTTP/2는 애플리케이션 계층(L7)에서는 프레임 다중화로 HoL 블로킹을 해결했지만, **전송 계층(L4)에서는 여전히 '단일 TCP 커넥션'**을 쓰고 있습니다!  
> TCP의 근본 철칙은 **'완벽한 순서 보장(In-Order Delivery)'**입니다.  
> 즉, Stream 1(HTML)의 조각이 담긴 패킷 1개가 무선망 노이즈로 유실되면, 뒤따라 멀쩡하게 도착한 Stream 2(CSS), Stream 3(JS), Stream 4(Hero 이미지)의 패킷들은 **OS 커널의 TCP 수신 버퍼(Out-of-Order Queue)에 갇혀 브라우저로 1바이트도 올라가지 못합니다!**  
> 송신자가 1 RTT 뒤에 빠진 패킷을 재전송(Fast Retransmit)해서 채워줄 때까지, **아무 잘못도 없는 수십 개의 스트림 전체가 일제히 정지(TCP-level Head-of-Line Blocking)하는 대참사**가 터지는 것입니다!  
> 반면 구형 HTTP/1.1은 6개의 독립된 TCP 파이프를 쓰기 때문에, 1개 파이프에서 패킷이 빠져도 나머지 5개 파이프의 이미지는 정상적으로 렌더링되었던 거죠!  
> 게다가 모바일 기기가 Wi-Fi에서 LTE로 전환될 때 TCP 4-튜플(IP/Port)이 깨져 연결이 통째로 끊기고 다시 핸드셰이크를 맺어야 합니다!  
> 이 모든 문제를 근본적으로 해결하려면, **UDP 기반 독립 스트림과 64비트 Connection ID 기반 무중단 연결 마이그레이션(Connection Migration)을 지원하는 HTTP/3 (QUIC)**를 도입해야 합니다!"

준호는 민우 님의 조언에 따라 QUIC/HTTP/3 네트워크 전송 시뮬레이터를 구축하여, 패킷 손실과 핸드오버 상황에서 프로토콜별 완주 시간과 Head-of-Line 블로킹 지연 시간을 정밀 측정하고 검증하기로 결심했습니다.

---

## 2. 핵심 이론: L7 다중화 vs L4 TCP HoL 블로킹 & HTTP/3 QUIC 혁신

```
[HTTP/2 단일 TCP 파이프 - 패킷 유실 시 L4 HoL 블로킹 발생]
TCP Seq:      #0           #1           #2           #3
Payload:  [Stream 1]   [Stream 2]   [Stream 3]   [Stream 4]
               │            │            │            │
               ▼            ▼            ▼            ▼
           [드롭/유실!]   [정상 도착]   [정상 도착]   [정상 도착]
               │            │            │            │
               │            └────────────┼────────────┘
               │                         ▼
               │              [커널 수신 버퍼 큐에 감금!]
               │           "앞선 #0이 올 때까지 L7 전달 차단"
               ▼                         │
         (1 RTT 재전송 대기)              ▼
       TCP Retransmit 도착! ===> [전 스트림 일괄 지연 해제]

[HTTP/3 QUIC (UDP) - 독립 스트림으로 L4 HoL 완전 제거]
UDP Packet:   #0           #1           #2           #3
Payload:  [Stream 1]   [Stream 2]   [Stream 3]   [Stream 4]
               │            │            │            │
               ▼            ▼            ▼            ▼
           [드롭/유실!]   [정상 도착]   [정상 도착]   [정상 도착]
               │            │            │            │
               ▼            ▼            ▼            ▼
          (Stream 1만)   [즉시 수신]   [즉시 수신]   [즉시 수신]
         재전송 대기       (지연 0ms)    (지연 0ms)    (지연 0ms)
```

### (1) HTTP/1.1 (Multi-Connection)
* 최대 `http1_max_connections` (기본 6개) 독립 TCP 커넥션 운용.
* 각 커넥션은 초기 `tcp_handshake_ms` (1 RTT) 비용 필요.
* 특정 커넥션에서 패킷이 드롭되어도 타 커넥션 스트림은 영향받지 않음.
* 단, 동시 스트림이 커넥션 수를 초과하면 후속 스트림은 선행 스트림 완주 시까지 대기(L7 HoL).
* 핸드오버 발생 시 활성 TCP 커넥션이 모두 단절되어 재연결 오버헤드 부과.

### (2) HTTP/2 (Single TCP Multiplexing)
* 단 1개의 TCP 커넥션 상에서 바이너리 프레임으로 다중화(초기 핸드셰이크 1회).
* 무손실 청정망에서는 최적의 성능을 냄.
* **TCP HoL 블로킹**: 패킷 $i$가 유실되어 재전송(`send_time + rtt_ms + latency`)될 때, 뒤따라 도착한 정상 패킷들($i+1, i+2, \dots$)은 모두 커널 TCP 윈도우 버퍼에 갇혀 L7 전달이 지연됨.
  $$\text{delivery\_time}[i] = \max(\text{l4\_arrival}[i], \text{delivery\_time}[i-1])$$
* 핸드오버 발생 시 단일 TCP 소켓 4-튜플 파괴로 전면 재연결(`tcp_handshake_ms`) 발생.

### (3) HTTP/3 (QUIC over UDP)
* UDP 기반 독립 스트림: 스트림 $S$의 청크는 동일 스트림의 선행 청크에만 의존하며, **타 스트림의 패킷 손실에 전혀 영향을 받지 않음 (Inter-Stream HoL Blocking = 0ms)**.
* **무중단 연결 마이그레이션 (Connection Migration)**:
  - 4-튜플 바인딩 대신 헤더의 **64비트 Connection ID(CID)**로 세션을 식별.
  - Wi-Fi $\to$ 5G 핸드오버 발생 시 IP/Port가 바뀌어도 동일 CID로 세션을 0-RTT 유지하여 **재연결 오버헤드 0ms** 달성!

---

## 3. 문제 요구사항

입력으로 주어지는 프로토콜(`protocol`), 스트림 목록(`streams`), 네트워크 조건(`network`), 설정(`config`)을 바탕으로 전송 시뮬레이션을 수행하고, 스트림별 완료 시간 및 HoL 블로킹 지연 시간, 핸드오버 오버헤드를 정밀 계산하여 JSON 형식으로 출력하는 프로그램을 작성하세요.

### 상세 규칙
1. **스트림 청크 분할**:
   * 각 스트림의 크기(`size_bytes`)와 `packet_size`에 따라 청크 수 $\lceil \text{size\_bytes} / \text{packet\_size} \rceil$ 결정.
2. **패킷 송신 스케줄링**:
   * **HTTP/1.1**: 각 커넥션은 `tcp_handshake_ms` 시점에 가용 상태가 됨. 스트림은 가장 먼저 가용해지는 커넥션에 할당되어 순차적으로 청크를 송신함.
   * **HTTP/2**: 초기 `tcp_handshake_ms` 후, 모든 스트림의 청크를 라운드로빈(Interleaving: chunk 0 of all streams, chunk 1 of all streams...) 순서로 `packet_interval_ms` 간격으로 송신.
   * **HTTP/3**: 초기 `quic_handshake_ms` 후, HTTP/2와 동일하게 청크를 인터리빙하여 송신.
3. **패킷 유실 및 도착 시간**:
   * 정상 패킷 L4 도착 시간: $\text{send\_time} + (\text{rtt\_ms} / 2)$
   * 유실 패킷(`dropped_packets`) 재전송 L4 도착 시간: $\text{send\_time} + \text{rtt\_ms} + (\text{rtt\_ms} / 2)$
4. **L7 전달 및 HoL 블로킹 계산**:
   * **HTTP/2**: 전송 순서대로 패킷 $i$의 L7 전달 시간은 $\max(\text{l4\_arrival}[i], \text{delivery}[i-1])$이며, 패킷이 L4에 먼저 도착했으나 선행 패킷 대기로 지연된 시간($\text{delivery}[i] - \text{l4\_arrival}[i]$)을 해당 스트림의 `hol_blocked_ms`에 누적.
   * **HTTP/3**: 각 스트림별로만 순서를 보장하므로 $\text{delivery}[sid] = \max(\text{l4\_arrival}, \text{prev\_stream\_delivery}[sid])$. 타 스트림에 의한 HoL 블로킹은 항상 0.0ms.
5. **네트워크 핸드오버**:
   * 송신 또는 전송 중(`send_time <= ht < arrive_time`) 핸드오버 이벤트 발생 시:
     - HTTP/1.1 & HTTP/2: TCP 4-튜플 파괴로 재연결 발생 (`reconnected_count += 1`, `handover_reconnect_overhead_ms += tcp_handshake_ms`, 송신 재개 시각은 $ht + \text{tcp\_handshake\_ms}$).
     - HTTP/3: QUIC Connection Migration으로 세션 단절 없음 (오버헤드 0ms, 재연결 0회).

---

## 4. 입력 및 출력 형식

### 입력 형식 (Standard Input - JSON)
```json
{
  "protocol": "HTTP/2",
  "streams": [
    {"stream_id": 1, "size_bytes": 1000},
    {"stream_id": 2, "size_bytes": 1000},
    {"stream_id": 3, "size_bytes": 1000}
  ],
  "network": {
    "packet_size": 1000,
    "packet_interval_ms": 10.0,
    "rtt_ms": 50.0,
    "dropped_packets": [{"stream_id": 1, "chunk_idx": 0}],
    "handover_events": []
  },
  "config": {
    "http1_max_connections": 6,
    "tcp_handshake_ms": 50.0,
    "quic_handshake_ms": 50.0
  }
}
```

### 출력 형식 (Standard Output - JSON)
```json
{
  "protocol": "HTTP/2",
  "total_elapsed_time_ms": 125.0,
  "streams": [
    {
      "stream_id": 1,
      "size_bytes": 1000,
      "completed_at_ms": 125.0,
      "hol_blocked_ms": 0.0
    },
    {
      "stream_id": 2,
      "size_bytes": 1000,
      "completed_at_ms": 125.0,
      "hol_blocked_ms": 40.0
    },
    {
      "stream_id": 3,
      "size_bytes": 1000,
      "completed_at_ms": 125.0,
      "hol_blocked_ms": 30.0
    }
  ],
  "metrics": {
    "total_hol_blocking_delay_ms": 70.0,
    "handover_reconnect_overhead_ms": 0.0,
    "reconnected_count": 0,
    "total_retransmissions": 1
  },
  "diagnosis": "CRITICAL: TCP-level Head-of-Line blocking occurred! Single TCP connection stalled all streams for 70.0ms due to packet drops."
}
```
