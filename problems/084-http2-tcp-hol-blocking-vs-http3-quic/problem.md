# 084 - HTTP/2로 바꿨더니 왜 모바일에서 더 느려져요?!: TCP Head-of-Line (HOL) 블로킹과 HTTP/3 QUIC (HTTP/1.1 vs HTTP/2 vs HTTP/3 QUIC)

## 1. 현실 비유 & 배경 스토리

서울에서 부산으로 향하는 고속도로가 있습니다. 🚗🛣️

```text
[HTTP/1.1 고속도로 (6개 독립 차선)]
차선 1: [차량 A (HTML)] ──> 타이어 펑크! (지연)
차선 2: [차량 B (CSS)]  ──────────────> 씽씽 달림 (정상 도착)
차선 3: [차량 C (JS)]   ──────────────> 씽씽 달림 (정상 도착)
차선 4: [차량 D (IMG1)] ──────────────> 씽씽 달림 (정상 도착)
차선 5: [차량 E (IMG2)] ──────────────> 씽씽 달림 (정상 도착)
차선 6: [차량 F (IMG3)] ──────────────> 씽씽 달림 (정상 도착)
=> 차량 A 1대만 늦고, 나머지 5대는 제시간에 도착!

[HTTP/2 고속도로 (단 1개의 좁은 단일 차선에 6대를 줄줄이 비엔나로 엮음)]
단일 차선: ──> [차량 F] ─> [차량 E] ─> [차량 D] ─> [차량 C] ─> [차량 B] ─> [차량 A (펑크!)]
=> 맨 앞 차량 A 1대가 멈추자, 아무 문제 없던 뒤쪽 차량 B, C, D, E, F까지 모조리 멈춰 섬!
   (TCP 계층의 Head-of-Line Blocking 참사)
```

2015년 제정된 **HTTP/2**는 브라우저가 수많은 TCP 연결을 맺고 끊는 오버헤드를 줄이기 위해,  
**"단 1개의 TCP 연결 위에 모든 요청/응답 스트림을 멀티플렉싱(Multiplexing)하여 한 줄로 전송"**하는 혁신을 도입했습니다.

패킷 손실이 거의 없는 쾌적한 유선 광랜 환경에서는 HTTP/2가 매우 빠릅니다.  
하지만 **지하철, 엘리베이터, 불안정한 카페 Wi-Fi, 모바일 LTE/5G**처럼 패킷 손실률이 1~2%만 발생하는 환경에 진입하면 기이한 일이 벌어집니다.  
**"HTTP/2가 구버전인 HTTP/1.1보다 훨씬 더 느려지는 역전 현상"**이 발생하는 것입니다!

그 이유는 바로 전송 계층인 **TCP의 엄격한 순서 보장(In-Order Delivery)** 때문입니다.  
단 1개의 TCP 패킷(예: `Stream 1`의 첫 번째 청크)이 유실되면, TCP 커널 수신 스택은 그 패킷이 재전송되어 도착할 때까지 **그 뒤에 정상 도착한 `Stream 2`의 CSS, `Stream 3`의 JS 패킷들을 브라우저(애플리케이션)로 올려보내지 않고 커널 수신 버퍼에 가두어버립니다(TCP Head-of-Line Blocking).**

구글과 IETF는 이 문제를 해결하기 위해, TCP를 버리고 **UDP 위에서 독립된 스트림 제어를 구현한 HTTP/3 QUIC**을 개발했습니다.  
QUIC은 단일 연결을 공유하지만 스트림별로 독립된 패킷 번호와 흐름 제어를 적용하므로, **특정 스트림의 패킷이 유실되어도 다른 스트림들은 0초 지연으로 즉시 브라우저에 전달**됩니다!

당신은 네트워크 프로토콜 시뮬레이터를 구축하여, 패킷 유실 환경에서 **HTTP/1.1**, **HTTP/2**, **HTTP/3 QUIC**의 스트림별 완료 시각과 블로킹 전파 현상을 계측해야 합니다!

---

## 2. 시뮬레이션 상세 사양

웹 페이지는 $M$개의 스트림(자원, ID: $1, 2, \dots, M$)으로 구성되며, 각 스트림은 $P$개의 패킷(인덱스: $0, 1, \dots, P-1$)을 순서대로 전송받아야 완료됩니다.

### 1) 패킷 전송 타임라인 및 유실 모델
- 정상 상태에서 $p$번째 패킷($p \in \{0, \dots, P-1\}$)의 물리적 도착 시각은 **$p + 1$ 틱**입니다.
- 특정 패킷이 유실(`SET_PACKET_LOSS <stream_id> <packet_idx>`)된 경우:
  - 해당 패킷의 실제 물리적 도착 시각은 재전송 RTT만큼 지연됩니다:
    $$\text{arrival\_tick} = (p + 1) + \text{retransmit\_rtt}$$

### 2) 3대 프로토콜 수신 메커니즘

1. **HTTP/1.1 (Parallel TCP Connections)**:
   - 각 스트림 $s$는 독립된 전용 TCP 연결을 사용합니다.
   - 특정 연결에서 패킷이 유실되어도 다른 연결의 스트림에는 **전혀 영향을 주지 않습니다**.
   - 스트림 $s$의 완료 시각: 해당 스트림의 모든 패킷 도착 시각 중 최댓값.
   - 블로킹 판정: 패킷 유실로 인해 정상 완료 시각($P$ 틱)보다 지연된 스트림의 수.

2. **HTTP/2 (Single TCP Connection Multiplexing)**:
   - 모든 스트림의 패킷들이 단 1개의 TCP 연결 위에 라운드로빈 인터리빙으로 전송됩니다:
     $$\text{글로벌 시퀀스}: [(S_1, P_0), (S_2, P_0), \dots, (S_M, P_0), (S_1, P_1), \dots]$$
   - **TCP 엄격한 순서 보장 (In-Order Delivery)**:
     글로벌 시퀀스 상에서 앞선 패킷이 도착할 때까지 그 뒤의 어떤 패킷도 애플리케이션으로 전달(`deliver`)될 수 없습니다.
     $$\text{deliver\_tick}(i) = \max_{0 \le k \le i} (\text{arrival\_tick}(k))$$
   - 스트림 $s$의 완료 시각: 해당 스트림의 패킷들이 애플리케이션으로 최종 전달된 시각 중 최댓값.
   - 블로킹 판정: TCP HOL 블로킹으로 인해 정상 완료 시각($P$ 틱)보다 지연된 스트림의 수.

3. **HTTP/3 QUIC (Independent UDP Streams)**:
   - UDP 기반으로 동작하며, 각 스트림 $s$는 서로 완전히 독립된 흐름 제어를 가집니다.
   - 다른 스트림의 패킷 유실 여부와 무관하게, 스트림 $s$ 내부의 패킷 도착 순서만 만족하면 즉시 애플리케이션으로 전달됩니다.
   - 스트림 $s$의 완료 시각: 해당 스트림의 모든 패킷 도착 시각 중 최댓값.
   - 블로킹 판정: 자신의 패킷 유실로 인해 정상 완료 시각($P$ 틱)보다 지연된 스트림의 수.

---

## 3. 입력 명령 프로토콜

표준 입력(stdin)으로 다음 명령어들이 한 줄씩 주어집니다:

1. `INIT <num_streams> <packets_per_stream> <retransmit_rtt>`
   - 시뮬레이터를 초기화합니다.
   - `num_streams`: 스트림 수 $M$ ($1 \le M \le 50$).
   - `packets_per_stream`: 스트림당 패킷 수 $P$ ($1 \le P \le 20$).
   - `retransmit_rtt`: 재전송 지연 틱 수 ($1 \le \text{retransmit\_rtt} \le 50$).
   - 출력: `INITIALIZED STREAMS=<num_streams> PACKETS_PER_STREAM=<packets_per_stream> RETRANSMIT_RTT=<retransmit_rtt>`

2. `SET_PACKET_LOSS <stream_id> <packet_idx>`
   - 특정 스트림의 특정 패킷($0 \le packet\_idx < P$)이 최초 전송 시 유실되도록 설정합니다.
   - 출력: `PACKET_LOSS_SCHEDULED STREAM=<stream_id> PACKET=<packet_idx>`

3. `SIMULATE`
   - 세 프로토콜을 시뮬레이션하고 결과를 다음 형식으로 출력합니다:
     ```
     === HTTP/1.1 (PARALLEL TCP) ===
     TOTAL_TICKS: <전체 스트림 수신 완료 시각>
     BLOCKED_STREAMS: <지연된 스트림 수>
     STREAM_FINISH_TIMES: [s1, s2, ...]
     === HTTP/2 (SINGLE TCP MULTIPLEXING) ===
     TOTAL_TICKS: <전체 스트림 수신 완료 시각>
     BLOCKED_STREAMS: <지연된 스트림 수>
     STREAM_FINISH_TIMES: [s1, s2, ...]
     === HTTP/3 QUIC (INDEPENDENT UDP STREAMS) ===
     TOTAL_TICKS: <전체 스트림 수신 완료 시각>
     BLOCKED_STREAMS: <지연된 스트림 수>
     STREAM_FINISH_TIMES: [s1, s2, ...]
     ```
     *(단, `STREAM_FINISH_TIMES`는 Python 리스트 문자열 `[3, 2, 2]` 형태로 출력)*

---

## 4. 제약 조건

- $1 \le \text{num\_streams} \le 50$
- $1 \le \text{packets\_per_stream} \le 20$
- $1 \le \text{retransmit\_rtt} \le 50$
- 총 명령어 수 $\le 1,000$

---

## 5. 입출력 예시

### 예시 입력
```
INIT 3 2 2
SET_PACKET_LOSS 1 0
SIMULATE
```

### 예시 출력
```
INITIALIZED STREAMS=3 PACKETS_PER_STREAM=2 RETRANSMIT_RTT=2
PACKET_LOSS_SCHEDULED STREAM=1 PACKET=0
=== HTTP/1.1 (PARALLEL TCP) ===
TOTAL_TICKS: 3
BLOCKED_STREAMS: 1
STREAM_FINISH_TIMES: [3, 2, 2]
=== HTTP/2 (SINGLE TCP MULTIPLEXING) ===
TOTAL_TICKS: 3
BLOCKED_STREAMS: 3
STREAM_FINISH_TIMES: [3, 3, 3]
=== HTTP/3 QUIC (INDEPENDENT UDP STREAMS) ===
TOTAL_TICKS: 3
BLOCKED_STREAMS: 1
STREAM_FINISH_TIMES: [3, 2, 2]
```

### 힌트 & 분석
- **HTTP/1.1 & HTTP/3 QUIC**:
  - `Stream 1`의 첫 번째 패킷이 유실되어 3틱에 완료되었습니다.
  - 하지만 `Stream 2`와 `Stream 3`은 아무런 유실이 없었으므로, 정상 시각인 **2틱에 완료**되었습니다 (`STREAM_FINISH_TIMES: [3, 2, 2]`, `BLOCKED_STREAMS: 1`).
- **HTTP/2**:
  - `Stream 1`의 패킷 0이 유실되자, TCP 순서 보장(In-Order Delivery) 규약 때문에 커널 수신 버퍼는 뒤따라온 `Stream 2`와 `Stream 3`의 정상 패킷들을 브라우저로 올려보내지 못하고 버퍼에 감금(HOL Blocked)했습니다.
  - 결국 아무 죄 없는 `Stream 2`와 `Stream 3`까지 3틱으로 지연되어 **3개 스트림 전원이 마비(`BLOCKED_STREAMS: 3`, `[3, 3, 3]`)**되었습니다!
