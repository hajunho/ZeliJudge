# Problem 172: Epoll Reactor 소켓 송신 버퍼와 워터마크 역압(Backpressure) 제어 시뮬레이터

## 문제 설명

대규모 트래픽을 처리하는 고성능 비동기 리버스 프록시 및 스트리밍 게이트웨이를 운영하던 중, 저속 클라이언트(Slow Consumer)에게 대용량 데이터를 전송할 때 논블로킹 소켓의 `EAGAIN` 에러를 무시하고 유저 메모리에 무제한 큐잉하다가 프로세스가 OOM(Out of Memory)으로 사망하는 장애가 발생했습니다.

당신은 네트워크 프레임워크의 코어 엔지니어로서, **커널 소켓 송신 버퍼(`SO_SNDBUF`)**, **논블로킹 소켓 `EAGAIN`**, 그리고 **고/저 워터마크(High/Low Watermark) 기반의 역압(Backpressure) 제어 메커니즘**을 정밀하게 시뮬레이션하여 메모리 폭발을 완벽하게 방지해야 합니다.

---

## 시뮬레이터 시스템 명세 및 동작 규칙

### 1. 시스템 설정 (`system`)
- `sndbuf_capacity_bytes` (기본값: 65,536 = 64KB): 커널 소켓 송신 버퍼(`SO_SNDBUF`)의 물리적 최대 용량.
- `high_watermark_bytes` (기본값: 131,072 = 128KB): 유저 대기 버퍼가 이 값을 초과하면 업스트림 읽기를 일시 정지(`upstream_paused = True`)하는 상한 임계치.
- `low_watermark_bytes` (기본값: 65,536 = 64KB): 일시 정지된 상태에서 유저 버퍼가 이 값 미만으로 떨어지면 업스트림 읽기를 재개(`upstream_paused = False`)하는 하한 임계치.
- `max_memory_limit_bytes` (기본값: 524,288 = 512KB): 유저 대기 버퍼가 이 값을 초과하면 프로세스가 OOM으로 사망(`OOM_CRASH`)하는 물리 한계.
- `flow_control_mode`: 
  - `"NAIVE_UNBOUNDED"`: 역압 제어 없이 유저 버퍼에 무제한 적재 (OOM 취약).
  - `"WATERMARK_BACKPRESSURE"`: 고/저 워터마크 기반으로 업스트림 인입을 능동 제어.

### 2. 매 틱(Tick) 처리 사이클
각 틱마다 워크로드(`upstream_bytes`, `client_drain_rate_bytes`)가 주어지며, 다음 순서로 엄격하게 평가됩니다:

1. **클라이언트 ACK 수신 및 커널 버퍼 배출 (Client Drain)**:
   - 커널 소켓 버퍼(`sndbuf_occupied`)에서 클라이언트 수신 속도(`client_drain_rate_bytes`)만큼 데이터가 배출되어 클라이언트에 전달됩니다:
     $$	ext{drained} = \min(	ext{sndbuf\_occupied}, 	ext{client\_drain\_rate\_bytes})$$
     $$	ext{sndbuf\_occupied} \leftarrow 	ext{sndbuf\_occupied} - 	ext{drained}$$
2. **업스트림 데이터 인입 및 역압 평가 (Upstream Ingress & Backpressure)**:
   - `flow_control_mode == "NAIVE_UNBOUNDED"`인 경우:
     - 제약 없이 `upstream_bytes` 전체를 수용하여 유저 버퍼(`pending_user_buffer`)에 가산합니다.
     - 만약 유저 버퍼가 `max_memory_limit_bytes`를 초과하면 즉시 `OOM_CRASH` 상태로 전이되고 시뮬레이션이 중단됩니다.
   - `flow_control_mode == "WATERMARK_BACKPRESSURE"`인 경우:
     - 현재 `upstream_paused == True`라면 업스트림 데이터를 일체 수용하지 않습니다 ($	ext{accepted} = 0$, `backpressure_ticks` 증가).
     - `upstream_paused == False`라면 `upstream_bytes`를 수용하여 유저 버퍼에 가산합니다.
     - 만약 유저 버퍼가 `high_watermark_bytes`를 **초과(>)**하면 즉시 `upstream_paused = True`로 설정하고 `pause_events`를 1 증가시킵니다.
3. **논블로킹 소켓 쓰기 (Non-blocking Socket Write & EAGAIN)**:
   - 커널 송신 버퍼의 잔여 공간을 계산합니다:
     $$	ext{space} = 	ext{sndbuf\_capacity\_bytes} - 	ext{sndbuf\_occupied}$$
   - 유저 버퍼에 대기 중인 데이터가 있고 잔여 공간이 있다면, 가능한 만큼 커널 소켓 버퍼로 이동합니다:
     $$	ext{written} = \min(	ext{pending\_user\_buffer}, 	ext{space})$$
     $$	ext{sndbuf\_occupied} \leftarrow 	ext{sndbuf\_occupied} + 	ext{written}$$
     $$	ext{pending\_user\_buffer} \leftarrow 	ext{pending\_user_buffer} - 	ext{written}$$
   - 만약 쓰기 후에도 여전히 `pending_user_buffer > 0`이라면, 소켓 버퍼가 가득 차서 더 이상 쓸 수 없는 상태이므로 `eagain_count`를 1 증가시키고 `epollout_active = True`로 설정합니다.
   - 유저 버퍼가 0이 되면 `epollout_active = False`가 됩니다.
4. **Low Watermark 검사 및 인입 재개 (Resume Check)**:
   - 역압 제어 모드이고 `upstream_paused == True`인 상태에서, 소켓 쓰기 결과 유저 버퍼가 `low_watermark_bytes` **미만(<)**으로 떨어졌다면:
     - `upstream_paused = False`로 복구하고 `resume_events`를 1 증가시킵니다.

### 3. 최종 판정 (Verdict)
- **`OOM_CRASH_UNBOUNDED_BUFFER`**: 버퍼 폭증으로 OOM 사망한 경우 (`status: FAILED`).
- **`BACKPRESSURE_FLOW_CONTROLLED`**: 역압 일시정지(`pause_events > 0`)가 발동되어 버퍼를 안전하게 제어한 경우.
- **`BUFFERED_EAGAIN_RECOVERED`**: 일시적인 `EAGAIN`이 발생했으나 워터마크 초과 없이 소켓 배출로 자연 회복된 경우.
- **`PERFECT_LINE_RATE_STREAMING`**: `EAGAIN`조차 단 한 번도 발생하지 않고 완벽하게 정속 전송된 경우.

---

## 입출력 예시

### 입력 (JSON)
```json
{
  "system": {
    "sndbuf_capacity_bytes": 65536,
    "high_watermark_bytes": 131072,
    "low_watermark_bytes": 65536,
    "max_memory_limit_bytes": 524288,
    "flow_control_mode": "WATERMARK_BACKPRESSURE"
  },
  "workload": [
    { "tick": 1, "upstream_bytes": 90000, "client_drain_rate_bytes": 15000 },
    { "tick": 2, "upstream_bytes": 90000, "client_drain_rate_bytes": 15000 }
  ]
}
```

### 출력 (JSON)
```json
{
  "status": "SUCCESS",
  "summary": {
    "sndbuf_capacity_bytes": 65536,
    "high_watermark_bytes": 131072,
    "low_watermark_bytes": 65536,
    "max_memory_limit_bytes": 524288,
    "flow_control_mode": "WATERMARK_BACKPRESSURE"
  },
  "metrics": {
    "total_upstream_offered_bytes": 180000,
    "total_upstream_accepted_bytes": 180000,
    "total_written_to_socket_bytes": 80536,
    "total_delivered_to_client_bytes": 15000,
    "peak_user_buffer_bytes": 99464,
    "peak_kernel_sndbuf_bytes": 65536,
    "eagain_count": 2,
    "backpressure_ticks": 0,
    "pause_events": 0,
    "resume_events": 0,
    "final_user_buffer_bytes": 99464,
    "final_kernel_sndbuf_bytes": 65536,
    "verdict": "BUFFERED_EAGAIN_RECOVERED"
  },
  "sample_timeline": [...]
}
```
