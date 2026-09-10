# 접속자 수가 10만을 넘자마자 왜 패킷이 대량 드롭되고 송수신 버퍼가 0으로 얼어붙어요?!: 리눅스 커널 TCP 메모리 서브시스템: tcp_mem 3단계 페이지 워터마크(min/pressure/max), tcp_rmem/wmem 소켓 버퍼 자동 튜닝과 메모리 압박(TCP Memory Pressure) 수신 윈도우 클램핑(Window Clamping) vs OFO 큐 가지치기(OFO Pruning)

## 문제 설명

대규모 트래픽을 처리하는 Envoy, Nginx API 게이트웨이나 실시간 게임 서버, 고성능 분산 캐시 클러스터에서는 동시 활성 TCP 연결(Concurrent Connections) 수가 10만~50만 개에 도달할 수 있습니다. 엔지니어들은 서버의 총 RAM 용량이 128GB이고 사용률이 40% 미만으로 널널함에도 불구하고, 피크 타임에 갑자기 커널 `dmesg`에 다음과 같은 치명적인 경고가 폭발하며 신규 접속이 거절되고 패킷이 대량 유실되는 기현상을 자주 목격합니다:

```text
TCP: out of memory -- consider tuning tcp_mem
TCP: drop open request from 10.0.1.50:54321
```

이 문제는 리눅스 커널의 **TCP 전용 메모리 컨트롤러(`net.ipv4.tcp_mem`)**가 시스템 전체 물리 메모리와 완전히 독립된 **3단계 페이지 워터마크(`[min, pressure, max]`, 단위: 4KB 페이지)**로 동작하기 때문에 발생합니다:

1. **`tcp_mem` 3단계 페이지 워터마크**:
   - `tcp_mem[0]` (**min**): 할당된 총 TCP 페이지 수(`tcp_memory_allocated`)가 이 임계값 이하일 때는 커널이 TCP 메모리 압박을 전혀 가하지 않습니다. 소켓별 버퍼가 BDP(대역폭-지연 곱)에 따라 자유롭게 자동 튜닝(`tcp_moderate_rcvbuf`)됩니다.
   - `tcp_mem[1]` (**pressure**): 총 TCP 페이지 수가 이 수위를 넘어서는 순간, 커널은 전역 플래그 `tcp_memory_pressure = 1`을 켭니다:
     - **비상 메모리 회수 모드(Emergency Squeeze)** 진입!
     - **OFO 큐 즉시 가지치기(`tcp_collapse_ofo_queue`)**: 순서가 어긋나 도착한(Out-of-Order) 패킷 큐를 즉각 강제 폐기하여 메모리를 회수합니다.
     - **수신 윈도우 클램핑(Window Clamping)**: 상대방에게 알리는 수신 윈도우 크기(`advertised_window`)를 강제로 축소하거나 극단적인 경우 0으로 얼려버림(`ZERO_WINDOW_ADVERTISED`)으로써 송신측의 패킷 유입을 중단시킵니다.
     - **히스테리시스(Hysteresis) 복구**: 압박 상태는 총 페이지 수가 단순히 `pressure` 아래로 내려갔다고 풀리지 않고, 가장 낮은 `min` 수위 밑으로 떨어져야만 `tcp_memory_pressure = 0`으로 정상 환원됩니다.
   - `tcp_mem[2]` (**max**): TCP 서브시스템의 절대적인 하드 리밋(Hard Ceiling)입니다.
     - 이 값을 초과하면 커널은 더 이상의 소켓 버퍼 할당(`sk_stream_alloc_skb`)을 전면 거부하며 `-ENOBUFS` 에러와 함께 인바운드 패킷을 즉시 드롭합니다 (`skb_drops`).
     - 신규 연결 수립(SYN/ACK) 역시 전면 거부됩니다 (`connection_refusals`).

2. **소켓별 버퍼 구성(`tcp_rmem` / `tcp_wmem`)**:
   - 각 소켓은 `[min, default, max]` 바이트 단위로 `tcp_rmem`(수신 버퍼)과 `tcp_wmem`(송신 버퍼)을 할당받습니다.
   - `tcp_moderate_rcvbuf`가 켜져 있으면 정상 상태에서 $\text{BDP} = (\text{Bandwidth} \times \text{RTT})$의 2배 크기로 수신 버퍼가 자동 확장됩니다. 그러나 전역 압박이 걸리면 확장이 즉시 동결됩니다.

본 문제에서는 시스템 설정과 소켓 트래픽/연결 이벤트가 주어졌을 때, 커널의 TCP 메모리 회계(Accounting), 메모리 압박 진입 및 히스테리시스 복구, OFO 큐 폐기, 윈도우 클램핑 및 하드 리밋 드롭 파이프라인을 정밀하게 시뮬레이션하는 엔진을 구현해야 합니다.

---

## 입력 형식

표준 입력(`sys.stdin`)을 통해 단일 JSON 객체가 전달됩니다:

```json
{
  "system_config": {
    "page_size_bytes": 4096,
    "tcp_mem_pages": [1000, 2000, 3000],
    "tcp_rmem_bytes": [4096, 87380, 524288],
    "tcp_wmem_bytes": [4096, 16384, 524288],
    "tcp_moderate_rcvbuf": true
  },
  "initial_sockets": [
    {
      "id": "sock_1",
      "rcv_buf_bytes": 87380,
      "snd_buf_bytes": 16384,
      "ofo_bytes": 0,
      "rtt_ms": 20,
      "bandwidth_mbps": 100
    }
  ],
  "events": [
    {
      "step": 1,
      "new_connections": [
        { "id": "sock_2", "rcv_buf_bytes": 200000, "snd_buf_bytes": 50000 }
      ],
      "socket_traffic": {
        "sock_1": { "inbound_bytes": 10000, "outbound_bytes": 5000, "ofo_bytes": 20000 }
      },
      "socket_closes": []
    }
  ]
}
```

---

## 출력 형식

표준 출력(`sys.stdout`)으로 compact한 단일 행 JSON 문자열을 출력합니다:

```json
{
  "summary": {
    "total_steps": 1,
    "peak_allocated_pages": 83,
    "total_ofo_dropped_bytes": 0,
    "total_skb_drops": 0,
    "total_connection_refusals": 0,
    "final_pressure_state": false
  },
  "step_history": [
    {
      "step": 1,
      "active_sockets": 2,
      "allocated_pages": 83,
      "tcp_memory_pressure": false,
      "status": "STATUS_NORMAL",
      "ofo_pruned_bytes": 0,
      "skb_drops": 0,
      "zero_window_sockets": 0
    }
  ]
}
```
