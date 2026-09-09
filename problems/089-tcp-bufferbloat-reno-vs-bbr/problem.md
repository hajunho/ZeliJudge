# Problem #089: 와이파이로 다운로드만 걸면 왜 핑이 1000ms로 치솟아요?!: 네트워크 버퍼블로트(Bufferbloat)와 TCP 혼잡 제어 (Reno vs Google BBR)

## 1. 문제 설명
집에서 대용량 스팀 게임이나 동영상 파일을 다운로드하기 시작하자마자, 잘 되던 온라인 게임(LoL, 배틀그라운드)의 핑이 15ms에서 800ms로 치솟고 디스코드 음성이 끊기는 고통을 겪어본 적이 있을 것입니다.

100Mbps 인터넷 회선에서 다운로드는 90Mbps로 정상 작동하고 있는데 왜 다른 패킷의 지연시간만 폭증할까요?  
범인은 바로 공유기와 통신사 라우터의 거대한 버퍼와 구시대적 손실 기반 TCP 혼잡 제어 알고리즘이 결합해 일으키는 **버퍼블로트(Bufferbloat)** 입니다!

기존의 **TCP Reno**는 네트워크 파이프가 가득 찼는데도 패킷이 드롭될 때까지 무작정 윈도우(`CWND`)를 키워 라우터 버퍼에 패킷을 가득 채웁니다. 그 결과 대화형 패킷(게임 핑)이 수백 개의 다운로드 패킷 뒤에 갇혀 지연시간이 폭발합니다.  
반면 **Google BBR**은 패킷 손실이 아니라 병목 대역폭($BtlBw$)과 물리 전파 지연($RTprop$)을 측정하여, 버퍼에 패킷을 1개도 줄세우지 않는 **$\text{BDP} = BtlBw \times RTprop$** 수준으로 전송량을 엄격히 통제(Pacing)합니다.

당신은 Reno와 BBR 두 혼잡 제어 엔진을 병렬로 구동하여, 라우터 버퍼 팽창과 지연시간 변화를 정밀하게 추적하는 **버퍼블로트 분석 시뮬레이터**를 구현해야 합니다.

---

## 2. 시스템 동작 규칙

### (1) 네트워크 모델 파라미터
- `BANDWIDTH`: 병목 링크의 1 RTT 라운드당 패킷 전송 용량 ($C$, 기본 5)
- `BUFFER_CAPACITY`: 라우터 버퍼의 최대 큐 용량 ($B$, 기본 20)
- `BASE_RTT`: 물리 전파 왕복 지연 ($R$, 기본 2)
- `INITIAL_SSTHRESH`: Reno의 초기 Slow Start 임계치 (기본 16)
- 대역폭-지연 곱: $\text{BDP} = \text{BANDWIDTH} \times \text{BASE\_RTT}$

---

### (2) 혼잡 제어 알고리즘 동작

#### 1. TCP Reno (손실 기반 AIMD)
- 상태: `cwnd` (초기 1.0), `ssthresh` (기본 16).
- 매 라운드 전송 패킷 수: `inflight = int(cwnd)`.
- 라우터 버퍼 진입 큐: `raw_queue = max(0, inflight - BDP)`.
- **버퍼 오버플로우 판정**:
  - `raw_queue > BUFFER_CAPACITY` 인 경우:
    - 초과분만큼 패킷 손실: `drops = raw_queue - BUFFER_CAPACITY`.
    - 버퍼 큐는 가득 참: `queue = BUFFER_CAPACITY`.
    - 손실 감지 $\to$ Multiplicative Decrease 적용:
      `ssthresh = max(2, int(cwnd) // 2)`
      `next_cwnd = float(ssthresh)`
  - `raw_queue <= BUFFER_CAPACITY` 인 경우:
    - 손실 없음: `drops = 0`, `queue = raw_queue`.
    - 윈도우 확장:
      - `cwnd < ssthresh` (Slow Start): `next_cwnd = min(float(ssthresh), cwnd * 2.0)`
      - `cwnd >= ssthresh` (Congestion Avoidance): `next_cwnd = cwnd + 1.0`
- Reno 지연시간: $\text{reno\_lat} = \text{BASE\_RTT} + (\text{queue} / \text{BANDWIDTH})$.
- 라운드 종료 후 `cwnd = next_cwnd`로 갱신됩니다.

#### 2. Google BBR (모델 기반 BDP 제어)
- BBR은 Inflight를 항상 이상적인 $\text{BDP}$로 유지합니다:
  - `cwnd = BDP`
  - `queue = 0` (버퍼에 패킷이 쌓이지 않음)
  - `drops = 0` (패킷 유실 없음)
  - $\text{bbr\_lat} = \text{float(BASE\_RTT)}$ (대기 지연 0, 순수 물리 지연만 발생)

---

### (3) 액션 명세

1. `STEP`:
   - 1 RTT 라운드의 데이터 전송을 시뮬레이션합니다.
   - 출력:
     `ACT <idx> STEP RENO:[CWND:<c> QUEUE:<q> DROPS:<d> LATENCY:<l:.1f>] BBR:[CWND:<c> QUEUE:<q> DROPS:<d> LATENCY:<l:.1f>]`

2. `PING <id>`:
   - 현재 라운드의 큐 상태에서 1개의 대화형 프로브(게임 핑) 패킷을 전송합니다.
   - Reno 하에서의 지연시간: $\text{reno\_lat} = \text{BASE\_RTT} + (\text{current\_queue} / \text{BANDWIDTH})$.
   - BBR 하에서의 지연시간: $\text{bbr\_lat} = \text{float(BASE\_RTT)}$.
   - 가속비: `ratio = reno_lat / bbr_lat`.
   - 출력:
     `ACT <idx> PING <id> RENO_LATENCY:<r_lat:.1f> BBR_LATENCY:<b_lat:.1f> (BBR_FASTER:<ratio:.2f>x)`

3. `SET_BANDWIDTH <val>`:
   - 병목 링크의 대역폭을 동적으로 변경합니다 (`BANDWIDTH = int(val)`).
   - 새로운 BDP 갱신: $\text{BDP} = \text{BANDWIDTH} \times \text{BASE\_RTT}$.
   - 출력:
     `ACT <idx> SET_BANDWIDTH NEW_BW:<val> NEW_BDP:<new_bdp>`

---

## 3. 입력 형식

```text
SYSTEM_CONFIG
BANDWIDTH <int>
BUFFER_CAPACITY <int>
BASE_RTT <int>
INITIAL_SSTHRESH <int>
ACTIONS
<ACTION_1>
<ACTION_2>
...
```

---

## 4. 출력 형식

각 액션마다 `ACT <act_idx> ...` 한 줄씩 출력합니다.  
모든 액션 실행 후 `SUMMARY`를 출력합니다:

```text
SUMMARY TOTAL_ACTIONS:<cnt>
SUMMARY RENO TOTAL_DROPS:<d> AVG_LATENCY:<avg:.2f> MAX_LATENCY:<max:.2f> BUFFERBLOAT:<TRUE|FALSE>
SUMMARY BBR TOTAL_DROPS:0 AVG_LATENCY:<avg:.2f> MAX_LATENCY:<max:.2f> BUFFERBLOAT:FALSE
SUMMARY AVG_LATENCY_REDUCTION:<pct:.1f>%
SUMMARY MAX_BUFFERBLOAT_INFLATION:<pct:.1f>%
```

- `AVG_LATENCY`: `STEP` 액션들의 지연시간 산술평균 (소수점 둘째 자리까지, STEP이 없으면 BASE_RTT).
- `MAX_LATENCY`: `STEP` 액션들 중 최대 지연시간 (소수점 둘째 자리까지, STEP이 없으면 BASE_RTT).
- `BUFFERBLOAT`: Reno의 `MAX_LATENCY >= BASE_RTT * 1.5` (50% 이상 팽창)이면 `TRUE`, 아니면 `FALSE`.
- `AVG_LATENCY_REDUCTION`: `(reno_avg - bbr_avg) / reno_avg * 100.0` (소수점 첫째 자리까지).
- `MAX_BUFFERBLOAT_INFLATION`: `(reno_max - BASE_RTT) / BASE_RTT * 100.0` (소수점 첫째 자리까지).

---

## 5. 입출력 예시

### 예시 입력 1
```text
SYSTEM_CONFIG
BANDWIDTH 5
BUFFER_CAPACITY 20
BASE_RTT 2
INITIAL_SSTHRESH 16
ACTIONS
STEP
STEP
STEP
STEP
STEP
PING game_packet_1
STEP
STEP
```

### 예시 출력 1
```text
ACT 1 STEP RENO:[CWND:1 QUEUE:0 DROPS:0 LATENCY:2.0] BBR:[CWND:10 QUEUE:0 DROPS:0 LATENCY:2.0]
ACT 2 STEP RENO:[CWND:2 QUEUE:0 DROPS:0 LATENCY:2.0] BBR:[CWND:10 QUEUE:0 DROPS:0 LATENCY:2.0]
ACT 3 STEP RENO:[CWND:4 QUEUE:0 DROPS:0 LATENCY:2.0] BBR:[CWND:10 QUEUE:0 DROPS:0 LATENCY:2.0]
ACT 4 STEP RENO:[CWND:8 QUEUE:0 DROPS:0 LATENCY:2.0] BBR:[CWND:10 QUEUE:0 DROPS:0 LATENCY:2.0]
ACT 5 STEP RENO:[CWND:16 QUEUE:6 DROPS:0 LATENCY:3.2] BBR:[CWND:10 QUEUE:0 DROPS:0 LATENCY:2.0]
ACT 6 PING game_packet_1 RENO_LATENCY:3.2 BBR_LATENCY:2.0 (BBR_FASTER:1.60x)
ACT 7 STEP RENO:[CWND:17 QUEUE:7 DROPS:0 LATENCY:3.4] BBR:[CWND:10 QUEUE:0 DROPS:0 LATENCY:2.0]
ACT 8 STEP RENO:[CWND:18 QUEUE:8 DROPS:0 LATENCY:3.6] BBR:[CWND:10 QUEUE:0 DROPS:0 LATENCY:2.0]
SUMMARY TOTAL_ACTIONS:8
SUMMARY RENO TOTAL_DROPS:0 AVG_LATENCY:2.60 MAX_LATENCY:3.60 BUFFERBLOAT:TRUE
SUMMARY BBR TOTAL_DROPS:0 AVG_LATENCY:2.00 MAX_LATENCY:2.00 BUFFERBLOAT:FALSE
SUMMARY AVG_LATENCY_REDUCTION:23.1%
SUMMARY MAX_BUFFERBLOAT_INFLATION:80.0%
```
