# 문제 457: Linux Kernel TCP TCP_NOTSENT_LOWAT 소켓 버퍼블로트 제거 및 JIT 페이싱 엔진

## 문제 설명

현대 초고속 네트워크(10GbE/100GbE) 및 멀티플렉싱 프로토콜(HTTP/2, HTTP/3, gRPC) 환경에서, TCP 소켓 송신 버퍼(`SO_SNDBUF`, `tcp_wmem`)는 BDP(대역폭-지연 곱)를 충족하기 위해 수 메가바이트(수 MB) 단위로 크게 설정됩니다.

그러나 전통적인 TCP 소켓 아키텍처는 심각한 **버퍼블로트(Bufferbloat) 및 헤드오브라인 블로킹(HOL Blocking)** 문제를 안고 있었습니다:
1. **소켓 송신 큐(`sk_write_queue`)의 팽창**:
   - `epoll`의 `POLLOUT` 이벤트는 단순히 전체 버퍼 여유 공간(`sk_stream_wspace(sk) > 0`)만을 기준으로 발생합니다.
   - 대용량 파일 전송(예: 4MB 비디오 청크)을 수행하는 애플리케이션은 버퍼가 허용하는 한 즉시 수 MB의 데이터를 소켓 큐에 밀어 넣습니다.
2. **애플리케이션 계층 스트림 우선순위 역전 (HOL Blocking)**:
   - 이때 최우선순위를 가지는 대화형 RPC 응답이나 HTML/CSS 제어 프레임이 발생하더라도, 이미 커널 소켓 큐에 쌓인 4MB의 저우선순위 데이터 뒤에 갇히게 됩니다.
   - 커널 큐에 진입한 패킷은 네트워크로 전송되기 전까지 애플리케이션이 취소하거나 재정렬할 수 없습니다.

```
+-----------------------------------------------------------------------------------------+
|                  TCP Traditional SO_SNDBUF vs TCP_NOTSENT_LOWAT                         |
+-----------------------------------------------------------------------------------------+

 [Traditional: SO_SNDBUF (e.g. 4MB)]
  +------------------------------------------------------------------------------------+
  | In-Flight: 100KB | Unsent Backlog: 3.9MB (Massive HOL Delay for new streams!)     |
  +------------------------------------------------------------------------------------+
  ^ epoll(POLLOUT) fires whenever space < 4MB -> Application dumps everything into queue!

 [Modern: TCP_NOTSENT_LOWAT (e.g. 16KB)]
  +-----------------------------------+
  | In-Flight: 100KB | Unsent: 16KB   |
  +-----------------------------------+
  ^ epoll(POLLOUT) blocked while unsent >= 16KB!
    -> When unsent < 16KB, epoll wakes application just-in-time (JIT)!
    -> High priority streams can be interleaved without queuing delay!
```

리눅스 커널은 Eric Dumazet의 설계로 **`TCP_NOTSENT_LOWAT`** 소켓 옵션(`net/ipv4/tcp_output.c`, `include/net/tcp.h`)을 도입하였습니다.
- `epoll(POLLOUT)` / `select` / `poll`의 쓰기 가능 조건:
  $$	ext{pollout\_ready} = (	ext{unsent\_bytes} < 	ext{tcp\_notsent\_lowat}) \land (	ext{total\_queued} < 	ext{sndbuf\_limit})$$
- 송신 큐에 아직 NIC/네트워크 드라이버로 송출되지 않은 순수 미송신 데이터(`unsent_bytes`)가 `tcp_notsent_lowat`(기본 16KB 등) 미만으로 내려갈 때만 `epoll_wait()`에 `EPOLLOUT` 이벤트를 발생시킵니다.
- 이를 통해 애플리케이션은 네트워크가 실제로 소비할 수 있는 최소한의 데이터만 적시에 생성(Just-In-Time)하여 소켓에 기록할 수 있으므로, 지연 시간을 극적으로 단축하고 HTTP/2 프레임 우선순위화를 완벽하게 보장합니다.

당신은 리눅스 커널의 `TCP_NOTSENT_LOWAT` 기반 소켓 송신 큐, 혼잡 윈도우(`cwnd`) 페이싱, ACK 처리 및 `EPOLLOUT` 이벤트 트리거 엔진을 시뮬레이션해야 합니다.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:
- `config`:
  - `sndbuf_limit`: int (기본값: 131072 바이트)
  - `default_notsent_lowat`: int (기본값: 16384 바이트)
  - `mss`: int (기본값: 1460 바이트)
  - `initial_cwnd`: int (기본값: 10 세그먼트)
- `operations`: 일련의 연산 배열.

지원되는 연산:
1. `{"op": "APP_WRITE", "stream_id": int, "prio": int, "data_len": int}`
   - 애플리케이션이 소켓 송신 큐에 데이터를 기록합니다.
   - `total_queued_bytes + data_len > sndbuf_limit`인 경우 `EAGAIN_SNDBUF_EXCEEDED` 반환 및 `stats.write_blocks += 1`.
   - 성공 시 큐에 삽입, `unsent_bytes` 및 `total_queued_bytes` 갱신 후 `WRITE_QUEUED` 반환.
2. `{"op": "TCP_PACE_TRANSMIT"}`
   - TCP 페이싱 전송 엔진을 구동합니다.
   - 전송 예산: $\min(	ext{cwnd} 	imes 	ext{mss} - 	ext{in\_flight\_bytes}, 	ext{unsent\_bytes})$.
   - 예산이 0 이하이면 `NOTHING_TO_SEND` (`CWND_LIMITED` 또는 `NO_UNSENT_DATA`) 반환.
   - 예산 범위 내에서 미송신 청크를 전송 상태(`sent = True`)로 변경 (필요 시 청크 분할), `unsent_bytes` 감소, `in_flight_bytes` 증가.
   - `unsent_bytes`가 임계치 미만으로 떨어져 쓰기 가능 상태로 전환되면 `EPOLLOUT` 이벤트 발생 (`stats.epollout_wakeups += 1`, `woken = True`).
3. `{"op": "TCP_RECEIVE_ACK", "ack_bytes": int}`
   - 상대방 호스트로부터 수신된 누적 ACK를 처리합니다.
   - 전송 완료된 가장 오래된 청크부터 바이트만큼 송신 큐에서 제거합니다.
   - `in_flight_bytes` 및 `total_queued_bytes`를 감소시키고 `stats.bytes_acked += ack_bytes`.
4. `{"op": "SETSOCKOPT_NOTSENT_LOWAT", "val": int}`
   - 소켓의 `tcp_notsent_lowat` 임계값을 변경하고 `pollout_ready` 상태를 재평가합니다.
5. `{"op": "SET_CWND", "cwnd": int}`
   - 혼잡 윈도우 크기를 갱신합니다.
6. `{"op": "QUERY_SOCKET_STATE"}`
   - 큐 바이트 상태, 쓰기 준비 여부(`pollout_ready`), 통계 카운터를 반환합니다.

---

## 출력 형식

표준 출력(stdout)으로 각 연산의 결과를 담은 JSON을 한 줄(compact)로 출력합니다:
```json
{"results": [...]}
```
