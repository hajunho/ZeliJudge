# Theory #442: 리눅스 커널 전송 계층: net/ipv4/tcp_input.c TCP SACK RFC 6675 손실 복구 및 파이프 제어 이론

## 1. 레거시 TCP Reno 손실 복구의 한계와 다중 손실 붕괴

1980년대 Van Jacobson의 TCP Reno 빠른 복구(Fast Recovery) 알고리즘은 단일 패킷 손실을 가정하고 설계되었습니다.
수신측이 3개의 중복 ACK(Duplicate ACKs)을 보낼 때 송신측은 1개의 패킷을 재전송하고 `cwnd`를 절반으로 줄입니다.

그러나 현대 고속 대역폭-지연 곱(BDP) 네트워크에서 라우터 버퍼가 오버플로우되면 단일 윈도우 내에서 수 개~수십 개의 패킷이 연속으로 유실되는 **버스트 손실(Burst Drop)**이 발생합니다.
- Reno 모델에서는 윈도우 내 2번째 손실 패킷을 복구하려면 1 RTT가 지난 뒤 다시 3개의 중복 ACK을 모아야 합니다.
- 만약 윈도우 내 남은 패킷 수가 부족하여 3개의 중복 ACK을 생성하지 못하면 송신측은 완벽한 정적 상태에 빠지며, 결국 **RTO(Retransmission Timeout, 수백 ms~수 초)**가 만료되어 `cwnd`가 1 MSS로 강등되는 파멸적인 전송 성능 붕괴가 발생합니다.

---

## 2. RFC 6675 SACK 스코어보드와 IsLost 판정 알고리즘

IETF RFC 6675는 선택적 수신 확인(SACK, RFC 2018)을 활용하여 송신측이 수신측 버퍼의 구멍(Hole)을 완벽하게 재구성하는 보수적 손실 복구(Conservative Loss Recovery)를 규정합니다.

```
Transmitted: [ P1 ] [ P2 ] [ P3 ] [ P4 ] [ P5 ] [ P6 ] [ P7 ] [ P8 ]
Arrived:     [ P1 ] (drop) [ P3 ] [ P4 ] [ P5 ] (drop) [ P7 ] [ P8 ]

SACK Info:   ACK = P2, SACK Block 1 = [P3..P6], SACK Block 2 = [P7..P9]
Scoreboard:
- P2: UNSACKED. Followed by SACKed P3, P4, P5 (3 packets >= dupthresh) -> DECLARED LOST!
- P6: UNSACKED. Followed by SACKed P7, P8 (2 packets < dupthresh) -> STILL UNSACKED (in-flight)
```

### (1) IsLost 판정 기준
송신측 스코어보드에서 미수신된 임의의 패킷 $P$에 대해:
1. $P$보다 시퀀스 번호가 높은 패킷 중 수신 완료된(SACKed) 패킷의 개수 $C_{\text{sacked}} \ge \text{dupthresh}$ (기본 3)인 경우, $P$는 네트워크에서 유실된 것으로 확정합니다.
2. 이는 TCP가 패킷의 일시적 순서 역전(Packet Reordering)을 3개 패킷 분량까지는 관용하되, 그 이상 뒤처지면 99.9% 확률로 드롭된 것으로 간주하는 통계적 최적치입니다.

---

## 3. 파이프(pipe) 제어와 혼잡 붕괴 방어의 수학적 모델

RFC 6675의 가장 위대한 공헌은 **`pipe` 변수**의 도입입니다.
과거 빠른 복구는 윈도우를 인위적으로 부풀리는(Window Inflation) 휴리스틱을 사용했으나, 이는 네트워크의 실제 혼잡 상태를 과소/과대평가하는 문제를 야기했습니다.

### (1) 파이프 계산 공식
$$\text{pipe} = \text{FlightSize} - \text{SACKedBytes} - \text{LostBytes} + \text{RetransBytes}$$

- **FlightSize (Unacked)**: 현재 누적 ACK을 받지 못한 모든 전송 데이터의 합.
- **SACKedBytes**: 수신측에 이미 도착하여 버퍼에 안전하게 저장된 데이터 (더 이상 네트워크 링크를 점유하지 않음).
- **LostBytes**: 스코어보드에 의해 유실로 판정되어 라우터 큐에서 폐기된 데이터 (물리 링크에서 소멸됨).
- **RetransBytes**: 빠른 재전송을 통해 망으로 재주입된 데이터 (새롭게 링크를 점유함).

### (2) 엄격한 전송 제어 (Strict Congestion Invariant)
송신측은 빠른 복구 도중에도 항상 다음 불변식을 만족해야 합니다:

$$\text{pipe} < \text{cwnd}$$

수신측으로부터 SACK ACK이 도착할 때마다 `pipe`가 1 MSS만큼 감소하므로, 그 여유분만큼 손실된 패킷을 순차적으로 재전송(Fast Retransmit)하거나 신규 데이터를 송출할 수 있습니다.
이로써 송신측은 패킷 폭풍(Packet Burst)으로 스위치 버퍼를 다시 넘치게 만드는 일 없이, 링크 용량에 정확히 일치하는 클록킹(Packet Clocking)을 완벽하게 유지합니다.
