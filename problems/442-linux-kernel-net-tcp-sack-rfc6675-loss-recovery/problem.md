# Problem #442: 리눅스 커널 전송 계층: net/ipv4/tcp_input.c TCP SACK 스코어보드 기반 정밀 손실 복구(RFC 6675) 및 파이프(pipe) 제어 엔진

## 🌟 개요 (Executive Summary)
전통적인 TCP Reno/Tahoe 혼잡 제어 모델은 누적 수신 확인(Cumulative ACK)에만 의존하기 때문에, 단일 윈도우 내에서 2개 이상의 패킷이 유실되는 다중 손실(Multiple Losses / Burst Drop)이 발생할 경우 1 RTT당 단 1개의 패킷만 재전송할 수 있었습니다.
이로 인해 잔여 손실 패킷을 복구하지 못한 채 RTO(Retransmission Timeout)가 만료되어 연결 처리량이 0으로 추락하고 200ms 이상의 극심한 지연 스톨이 발생하는 구조적 한계가 존재했습니다.

IETF와 리눅스 커널 네트워킹 스택(`net/ipv4/tcp_input.c`, `net/ipv4/tcp_output.c`, `include/net/tcp.h`)은 이를 해결하기 위해 **RFC 2018 SACK 옵션**과 **RFC 6675 정밀 손실 복구 알고리즘(Conservative Loss Recovery Algorithm Based on SACK)**을 표준으로 구현하였습니다:
- **전송 스코어보드 (SACK Scoreboard)**:
  - 송신측 TCP는 전송된 모든 미확인 패킷을 인-플라이트 리스트로 관리하며, 각 패킷의 상태를 `UNSACKED`(미확인 전송 중), `SACKED`(수신측 버퍼 수신 완료), `LOST`(손실 확정)의 3대 상태 머신으로 추적합니다.
- **정밀 손실 판정 규칙 (`IsLost` Heuristic)**:
  - 패킷 $P$보다 높은 시퀀스 번호를 가진 패킷들 중 수신 확인된(SACKed) 패킷의 수가 중복 ACK 임계치(`dupthresh`, 기본값 3) 이상 도달하면, 패킷 $P$는 망 내에서 역전(Reordering)된 것이 아니라 확실히 유실된 것으로 판정(`state = "LOST"`)하고 즉시 빠른 복구(Fast Recovery)로 전환합니다.
- **네트워크 점유량 `pipe`의 수학적 정밀 계산**:
  - 기존의 막연한 비행 중 바이트 수 계산 대신, 실제 물리 네트워크 링크를 점유하고 있는 데이터양을 엄밀하게 산출합니다:
    $$\text{pipe} = \text{unacked\_bytes} - \text{sacked\_bytes} - \text{lost\_bytes} + \text{retrans\_bytes}$$
  - SACK으로 이미 목적지에 도착한 바이트와 손실로 판명되어 회선에서 사라진 바이트를 정확히 제외하여 실제 망 부하를 측정합니다.
- **빠른 재전송(Fast Retransmit) 및 복구 종단(`high_seq`) 보장**:
  - 빠른 복구 상태에서 $\text{pipe} < \text{cwnd}$ 예산이 허용되는 한, 손실된 패킷 중 가장 낮은 시퀀스 번호의 패킷을 즉시 재전송(`fast_retransmits++`)합니다.
  - 빠른 복구 진입 시점의 최고 전송 시퀀스(`high_seq = snd_nxt`) 이상의 누적 ACK이 수신되는 순간 복구가 완료(`RECOVERY_COMPLETED`)되며 혼잡 윈도우가 정상 복원됩니다.

본 문제에서는 리눅스 커널 `net/ipv4/tcp_input.c`의 RFC 6675 SACK 스코어보드, `IsLost` 손실 판정, `pipe` 회계, 빠른 재전송 및 복구 상태 머신을 시뮬레이션합니다.

---

## 🏗️ 아키텍처 및 시스템 흐름도 (System Architecture)

```
        [ RECEIVE_ACK(ack_seq, sack_blocks) ]
                         │
        Advance Cumulative ACK: snd_una = ack_seq
        Remove packets where seq + len <= ack_seq
                         │
        Are we in Fast Recovery AND snd_una >= high_seq?
               ┌─────────┴─────────┐
              Yes                  No
               │                   │
               ▼                   ▼
       [ Exit Recovery ]    Apply SACK blocks to packets
       cwnd = ssthresh      Mark covered packets as SACKED
       RECOVERY_COMPLETED          │
                                   ▼
                   Evaluate IsLost for each UNSACKED packet P:
                   Count SACKed packets with seq > P.seq
                   If count >= dupthresh (3):
                       P.state = "LOST"
                       If not in Fast Recovery:
                           Enter Fast Recovery!
                           high_seq = snd_nxt
                           ssthresh = max(2*MSS, cwnd // 2)
                           cwnd = ssthresh
                                   │
                                   ▼
                   Calculate pipe:
                   pipe = unacked - sacked - lost + retrans
                                   │
                   Is in_fast_recovery AND pipe < cwnd?
                         ┌─────────┴─────────┐
                        Yes                  No
                         │                   │
                         ▼                   ▼
                 Find lowest LOST       Done (Wait for ACKs)
                 un-retransmitted packet
                 Retransmit packet!
                 fast_retransmits++
```

---

## ⚙️ I/O 데이터 규격 (Input/Output Specifications)

### 1. 입력 JSON 구조
```json
{
  "config": {
    "mss": 1000,
    "dupthresh": 3,
    "initial_cwnd": 10000,
    "initial_ssthresh": 20000
  },
  "trace": [
    {"op": "TRANSMIT_NEW", "len": 1000},
    {"op": "TRANSMIT_NEW", "len": 1000},
    {"op": "TRANSMIT_NEW", "len": 1000},
    {"op": "TRANSMIT_NEW", "len": 1000},
    {"op": "TRANSMIT_NEW", "len": 1000},
    {"op": "RECEIVE_ACK", "ack_seq": 10000, "sack_blocks": [[11000, 15000]]},
    {"op": "RECEIVE_ACK", "ack_seq": 15000},
    {"op": "GET_STATS"}
  ]
}
```

### 2. 필드 정의
- `config`:
  - `mss` (int, default=1000): 최대 세그먼트 크기 (바이트).
  - `dupthresh` (int, default=3): 중복/SACK 패킷 손실 판정 임계치.
  - `initial_cwnd` (int, default=10000): 초기 혼잡 윈도우 (바이트).
  - `initial_ssthresh` (int, default=20000): 초기 슬로우 스타트 임계치 (바이트).
- `trace` 명령어:
  1. `TRANSMIT_NEW`:
     - `len` (int): 송신할 패킷 바이트 수.
  2. `RECEIVE_ACK`:
     - `ack_seq` (int): 누적 수신 확인 번호.
     - `sack_blocks` (list of `[start, end]`): 선택적 수신 확인 블록 목록.
  3. `GET_STATS`:
     - 현재 스코어보드, pipe, cwnd, ssthresh 및 복구 통계 조회.

### 3. 출력 JSON 구조
```json
{
  "events": [
    {
      "op": "TRANSMIT_NEW",
      "seq": 10000,
      "len": 1000,
      "snd_nxt": 11000,
      "status": "TRANSMITTED"
    },
    ...
    {
      "op": "RECEIVE_ACK",
      "ack_seq": 10000,
      "in_fast_recovery": true,
      "pipe": 1000,
      "cwnd": 5000,
      "ssthresh": 5000,
      "retransmitted_seq": 10000,
      "status": "ENTERED_FAST_RECOVERY"
    }
  ],
  "summary": {
    "snd_una": 15000,
    "snd_nxt": 15000,
    "in_fast_recovery": false,
    "cwnd": 5000,
    "ssthresh": 5000,
    "fast_recovery_entries": 1,
    "packets_marked_lost": 1,
    "fast_retransmits": 1,
    "recovery_completions": 1
  }
}
```
