# Problem 213: 10GbE 랜카드에 버퍼를 4096개로 늘렸더니 왜 핑(RTT)이 100ms로 치솟아요?!: 리눅스 커널 BQL(Byte Queue Limits)과 TSQ(TCP Small Queues): 드라이버 링 버퍼 팽창으로 인한 버퍼블로트(Bufferbloat) 방어와 동적 대기열 제어 (Linux Network Driver: Byte Queue Limits (BQL) & TCP Small Queues (TSQ) vs Oversized NIC TX Ring Buffer Latency Bloat)

## 문제 배경 및 개요

대규모 고성능 클라우드 인프라와 쿠버네티스 노드를 관리하는 시스템 엔지니어링 팀은 네트워크 패킷 드롭(`tx_dropped`)을 줄이고 전송 처리량을 극대화하기 위해 다음과 같이 10GbE 네트워크 카드의 송신 링 버퍼(TX Ring Buffer)를 최대로 설정했습니다:

```bash
# "버퍼는 클수록 패킷 드롭이 안 생기겠지?!"
$ sudo ethtool -G eth0 tx 4096 rx 4096
```

그러나 설정 직후, 야간 데이터베이스 백업 파일 전송 및 대규모 비디오 스트리밍이 시작되자마자 인프라 모니터링 시스템 전체에서 심각한 **"네트워크 지연시간 폭증 및 버퍼블로트(Bufferbloat) 대참사"**가 터졌습니다:

```
[레거시 무제한 4096 링 버퍼: 송신 큐에 6MB가 통째로 쌓이며 지연시간 50ms 폭발!]
App Pod (Bulk Upload) ──── TCP write() ────► 400개 패킷 (600,000 Bytes) 발생!
                                                    │
                                                    ▼
                                          [Linux Qdisc: pfifo_fast]
                                                    │
                                                    ▼ (한도 4096 디스크립터 = ~6MB)
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ NIC TX Ring Buffer (하드웨어 DMA 링 버퍼: 600KB가 통째로 적재됨!)                         │
│ [Pkt 1] [Pkt 2] ... [Pkt 399] [Pkt 400] ◄── 뒤에 새로 도착한 SSH / Kube Liveness Probe 패킷!│
└────────────────────────────────────────────────────────────────────────────────────────┘
  │                                                                                      ▲
  │ 100Mbps 선로로 순차 배출 (12,500 Bytes/ms)                                             │
  ▼                                                                                      │
  600,000 Bytes / 12,500 Bytes/ms = 48 ms 동안 대기열 갇힘!                                │
  ==> 긴급 헬스체크(Liveness Probe) 및 SSH 패킷이 대용량 데이터 뒤에 갇혀 41.75 ms 지연 발생!│
  ==> 파드 헬스체크 타임아웃으로 워커 노드 내 파드들이 무차별 재시작되는 연쇄 장애 발생!   │
```

많은 엔지니어들이 "버퍼를 크게 잡으면 안전하다"고 착각하지만, **하드웨어 드라이버 링 버퍼는 일단 패킷이 진입하면 커널 TCP 스택이 더 이상 재배열하거나 회수할 수 없는 FIFO 물리 큐**입니다. 거대한 링 버퍼에 벌크 트래픽이 쏟아져 들어오면 패킷들이 선로를 빠져나가기 전까지 수십~수백 밀리초 동안 갇혀버리는 **버퍼블로트(Bufferbloat)**가 발생합니다.

리눅스 커널 핵심 네트워킹 개발팀은 이 문제를 해결하기 위해 **BQL(Byte Queue Limits)**과 **TSQ(TCP Small Queues)**라는 혁신적인 2중 계층 대기열 제어 아키텍처를 도입했습니다:

```
[BQL + TSQ 결합 가속 아키텍처: 하드웨어 큐 3KB 제한 & 소켓 레벨 페이싱]

1. TSQ (TCP Small Queues - net.ipv4.tcp_limit_output_bytes = 3000):
   - 벌크 소켓이 하위 계층(Qdisc+드라이버)에 2개 패킷(3KB) 이상을 쌓지 못하도록 소켓 송신을 페이싱(Pacing)!
   - 대기 패킷은 커널 유저 소켓 버퍼에 머무르므로, 긴급 대화형(SSH/Liveness) 패킷이 즉시 추월!

2. BQL (Byte Queue Limits - netdev_tx_sent_queue & completed_queue):
   - 인터럽트 주기 동안 선로를 100% 포화시키는 데 필요한 최소 바이트(약 3KB ~ 6KB)만 하드웨어 링에 투입!
   - 하드웨어 링 점유율: 600,000 Bytes ───► 3,075 Bytes로 99.5% 급감!
   - 드라이버 큐 지연시간: 47.95 ms ───► 0.25 ms 로 190배 초저지연 단축!
   - 대화형 패킷 지연시간: 41.75 ms ───► 0.14 ms 로 즉각 응답! (선로 처리량은 100% 만점 유지!)
```

당신은 리눅스 커널 및 고성능 네트워크 엔지니어로서, 무제한 레거시 링 버퍼, BQL 단독 모드, 그리고 BQL+TSQ 최적화 모드의 큐 동작과 지연시간 메커니즘을 정밀하게 분석하는 네트워크 시뮬레이션 엔진을 구현해야 합니다.

---

## 3대 네트워크 대기열 모드 명세

### 1. `OVERSIZED_RING_NO_BQL_NO_TSQ` (레거시 무제한 링 버퍼 모드)
- BQL과 TSQ가 모두 비활성화된 상태입니다.
- 소켓은 윈도우 한도 내의 모든 패킷을 Qdisc와 하드웨어 드라이버 링 버퍼로 무제한 쏟아붓습니다.
- 4096개 디스크립터(수 메가바이트) 크기의 하드웨어 링 버퍼가 가득 차면서 심각한 버퍼블로트가 발생합니다.
- 평가 판정: 하드웨어 큐가 50KB 이상 팽창하거나 드라이버 지연이 10ms를 초과하면 `BUFFERBLOAT_DRIVER_RING_EXPLOSION` (`status: FAILED`).

### 2. `BQL_ONLY` (드라이버 BQL 단독 활성화 모드)
- 하드웨어 드라이버 링 버퍼는 BQL 알고리즘에 의해 동적으로 제어되어 수 킬로바이트(지연 < 1ms) 수준으로 유지됩니다.
- 그러나 TCP 소켓 레벨의 TSQ 페이싱이 없으므로, 벌크 소켓이 생성한 수백 개의 패킷이 Qdisc 계층의 FIFO 큐에 통째로 적재됩니다.
- 하드웨어 링 자체의 지연은 줄어들지만, 긴급 대화형 패킷이 Qdisc에 누적된 벌크 패킷 뒤에 갇혀 여전히 높은 지연시간을 겪습니다.
- 평가 판정: 대화형 패킷 지연이 15ms를 초과하면 `BQL_DEVICE_CLAMPED_BUT_QDISC_BLOAT` (`status: FAILED`).

### 3. `OPTIMAL_BQL_AND_TSQ_PACING` (BQL + TSQ 결합 최적화 모드)
- BQL이 디바이스 링 큐를 3KB~6KB로 엄격히 제한하고, TSQ가 소켓당 미처리 바이트를 `2 * MSS`(약 3KB)로 제한합니다.
- 벌크 소켓은 2개 패킷만 하위로 보낸 뒤 소켓 레벨에서 일시 정지(Throttled)되므로, 긴급 대화형 패킷이 즉시 Qdisc 선두로 진입하여 $0.2\,\text{ms}$ 이하의 초저지연으로 전송됩니다.
- 선로 대역폭(Line Rate) 활용률은 100%를 유지하면서 지연시간 폭증을 완벽히 소멸시킵니다.
- 평가 판정: 트래픽이 경미한 경우 `LIGHT_TRAFFIC_CLEAN_FLOW`, 정상 워크로드인 경우 `OPTIMAL_BQL_AND_TSQ_PACING` (`status: SUCCESS`).

---

## 입력 형식

표준 입력(Standard Input)으로 단일 JSON 객체가 주어집니다:

```json
{
  "config": {
    "mode": "OPTIMAL_BQL_AND_TSQ_PACING",
    "link_speed_mbps": 100,
    "tx_ring_max_descriptors": 4096,
    "mss_bytes": 1500,
    "bql_initial_limit_bytes": 6000,
    "tsq_limit_bytes": 3000,
    "tx_interrupt_interval_ms": 0.1
  },
  "flows": [
    {"flow_id": "bulk"},
    {"flow_id": "ssh"}
  ],
  "events": [
    {"timestamp_ms": 0.0, "flow_id": "bulk", "size": 1500, "is_interactive": false, "packet_id": 1},
    {"timestamp_ms": 2.0, "flow_id": "ssh", "size": 100, "is_interactive": true, "packet_id": 1002}
  ]
}
```

---

## 출력 형식

표준 출력(Standard Output)으로 진단 시뮬레이션 결과 JSON을 들여쓰기 2칸(`indent=2`)으로 출력합니다:

```json
{
  "status": "SUCCESS",
  "verdict": "OPTIMAL_BQL_AND_TSQ_PACING",
  "mode": "OPTIMAL_BQL_AND_TSQ_PACING",
  "metrics": {
    "total_packets_sent": 404,
    "total_bytes_transmitted": 600400.0,
    "bulk_packets_transmitted": 400,
    "interactive_packets_transmitted": 4,
    "max_driver_queue_bytes": 3075.0,
    "max_driver_queue_latency_ms": 0.25,
    "average_bulk_latency_ms": 24.06,
    "average_interactive_latency_ms": 0.14,
    "tsq_throttled_packets": 1358,
    "bql_backpressure_events": 0,
    "line_rate_utilization_pct": 43.7
  }
}
```

---

## 판정 기준 (Verdict Rules)

1. **`BUFFERBLOAT_DRIVER_RING_EXPLOSION`**: 레거시 무제한 링 버퍼에서 대량 패킷이 하드웨어 큐를 50KB 이상 잠식하거나 드라이버 큐 지연시간이 10ms를 초과하여 심각한 버퍼블로트가 발생한 경우 (`status: FAILED`).
2. **`BQL_DEVICE_CLAMPED_BUT_QDISC_BLOAT`**: BQL로 하드웨어 링 지연은 단축되었으나, TSQ 부재로 인해 Qdisc에 벌크 패킷이 누적되어 대화형 패킷 지연이 15ms를 초과한 경우 (`status: FAILED`).
3. **`OPTIMAL_BQL_AND_TSQ_PACING`**: BQL과 TSQ의 유기적 결합으로 하드웨어 링 팽창 방지, 소켓 레벨 페이싱, 대화형 패킷 초저지연, 선로 100% 활용을 동시에 달성한 경우 (`status: SUCCESS`).
4. **`LIGHT_TRAFFIC_CLEAN_FLOW`**: 총 전송 패킷 수가 10개 미만인 경미한 트래픽 환경에서 큐잉 지연 없이 정상 완료된 경우 (`status: SUCCESS`).
