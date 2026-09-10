# 리눅스 커널 FQ-CoDel(RFC 8290) 및 능동 큐 관리(AQM) 이론 (FQ-CoDel & Active Queue Management)

## 1. 버퍼블로트(Bufferbloat)의 근본 원인과 한계

### 1.1 메모리 가격 하락과 "무식한 대용량 FIFO 버퍼"
1990년대 이후 메모리 반도체 단가가 급락하면서, 통신 장비 제조사들은 패킷 유실(Packet Loss)을 방지한다는 명목으로 라우터와 스위치, 케이블/DSL 모뎀에 수 메가바이트 규모의 대용량 FIFO 버퍼를 탑재했습니다.

그러나 TCP의 혼잡 제어(Congestion Control) 알고리즘(Reno, Cubic 등)은 **"패킷 손실"**을 혼잡 신호로 감지하여 전송률을 조절하도록 설계되어 있었습니다. 대용량 버퍼가 패킷을 버리지 않고 계속 축적하면서:
- 버퍼는 가득 찬 상태로 유지되어 패킷이 수백 ms 동안 버퍼에 갇히는 **지속적 정체 큐(Standing Queue)**가 형성됩니다.
- 패킷 손실은 발생하지 않으나, 대화형 트래픽(DNS 쿼리, 원격 SSH 터미널, 실시간 비디오/게임)의 지연시간이 폭증하여 인터넷 체감 품질이 마비되는 **버퍼블로트(Bufferbloat)**가 발생했습니다.

---

## 2. CoDel(Controlled Delay) 알고리즘의 패러다임 전환

### 2.1 큐 길이가 아닌 "체류 시간(Sojourn Time)"에 기반한 제어
과거의 AQM 알고리즘인 RED(Random Early Detection)는 평균 큐 길이(Queue Length in bytes)를 측정했습니다. 그러나:
- 일시적인 트래픽 버스트(Good Queue)와 지속적인 체증(Bad Queue)을 구별하지 못했습니다.
- 링크 대역폭에 따라 파라미터 튜닝이 극도로 난해하여 현업에서 거의 폐기되었습니다.

CoDel(Kathleen Nichols & Van Jacobson, 2012)은 파라미터 튜닝이 필요 없는(No Knobs) 알고리즘으로 설계되었습니다:
- **좋은 큐(Good Queue)**: 일시적인 패킷 버스트로 큐가 길어지더라도 빠른 속도로 드레인(Drain)되므로 개별 패킷의 소전 시간(Sojourn Time)은 짧습니다.
- **나쁜 큐(Bad Queue)**: 링크 용량을 초과하는 지속적 트래픽으로 인해 최소 소전 시간(`min_sojourn_time`)이 `target`(5ms) 아래로 떨어지지 않고 `interval`(100ms) 동안 지속됩니다.

### 2.2 역제곱근 규칙 ($1/\sqrt{n}$)
CoDel이 체증 상태(`dropping == True`)에 돌입했을 때, 드롭 간격은 다음과 같이 축소됩니다:
$$t_{	ext{next\_drop}} = t_{	ext{current}} + rac{	ext{interval}}{\sqrt{	ext{count}}}$$
- TCP의 전송률은 패킷 손실률 $p$의 제곱근에 반비례한다는 **마티스 공식(Mathis Formula: $B pprox rac{MSS}{RTT \sqrt{p}}$)**에 기반합니다.
- 드롭 주기를 $1/\sqrt{n}$으로 좁혀감으로써 TCP 송신 윈도우가 선형적이고 안정적으로 수렴하도록 유도합니다.

---

## 3. Fair Queueing (DRR)과 CoDel의 결합: RFC 8290

### 3.1 흐름 분리의 위력
아무리 뛰어난 AQM이라 하더라도 단일 FIFO 큐에서는 무차별적인 UDP 플러딩이나 무례한(Aggressive) 단일 TCP 커넥션이 다른 착한 플로우를 방해하는 것을 막을 수 없습니다.

FQ-CoDel은 패킷을 해시 기반으로 독립된 플로우 큐로 분리(Flow Isolation)한 뒤 각 큐에 CoDel을 독립적으로 실행합니다:
1. **Mice Flows (소량 대화형 플로우)**:
   - 전송량이 적어 큐가 자주 비므로 항상 `new_flows`의 최우선 순위를 받아 즉각 전송됩니다.
2. **Elephant Flows (대용량 벌크 플로우)**:
   - 퀀텀을 지속적으로 소진하므로 `old_flows`에서 공평하게 대역폭을 나누어 가지며, 해당 플로우 내부에서만 CoDel 드롭이 집중적으로 발생합니다.
3. **ECN 결합**:
   - RFC 8290은 ECN 협상이 완료된 패킷에 대해 패킷 손실 없이 IP 헤더의 ECN 비트(CE: Congestion Experienced)를 11로 마킹하여, 재전송 지연 없이 최적의 쓰루풋과 극저지연을 동시에 달성합니다.
