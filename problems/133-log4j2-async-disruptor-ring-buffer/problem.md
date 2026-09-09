# 133. 로그 1줄 찍었을 뿐인데 왜 TPS가 10분의 1로 곤두박질치고 서버가 멈춰요?!: 동기식 로거(Sync Logger)의 디스크 I/O 블로킹과 비동기 LMAX 디스럽터 링 버퍼(Log4j2 Async Disruptor Ring Buffer) & 레벨별 폐기 정책

## 문제 설명

이커머스 결제 시스템의 주니어 백엔드 엔지니어 젤리(Zeli)는 연중 최대 할인 행사 도중, 결제 트랜잭션의 상세 흐름을 추적하기 위해 주문 생성 컨트롤러 메서드 진입점에 다음 로깅 코드 한 줄을 추가했습니다:

```java
@PostMapping("/api/orders")
public ResponseEntity<OrderResult> createOrder(@RequestBody OrderRequest request) {
    log.info("Order requested: user={}, amount={}", request.getUserId(), request.getAmount());
    return ResponseEntity.ok(orderService.process(request));
}
```

*"로컬 개발용 노트북에서는 로그 찍는 데 0.01ms도 안 걸렸으니, 운영 서버에서도 전혀 무리 없겠지?!"* 😎

하지만 이 코드가 프로덕션 환경에 배포되자마자 서버 모니터링 대시보드에 빨간 불이 켜지며 대참사가 터졌습니다! 🚨

```
[ALERT] Tomcat Worker Thread Pool (Max: 200) Exhausted!
[ALERT] Active Threads: 200 / 200 (100% In-Use)
[ALERT] API Response Time: 120ms ──► 14,800ms (120배 폭증!)
[ERROR] 504 Gateway Timeout: Upstream server failed to respond within 15s
```

수천 명의 고객이 결제 버튼을 누르는 순간 톰캣의 200개 워커 스레드가 **단 1개도 남김없이 전멸**해 버렸고, 전사 API가 멈추며 결제가 마비된 것입니다! 😱

---

### 원인: 동기식 로거(Synchronous Logger)의 Appender 락과 디스크 I/O 블로킹

전통적인 동기식 로깅(SLF4J + Logback/Log4j 기본 설정)은 다음과 같은 치명적인 병목 구조를 갖습니다:

```
[클라이언트 요청] ──► [톰캣 워커 스레드]
                           │
                           ▼
                   log.info("주문 처리");
                           │
                           ├──► [Appender 동기화 락(Lock) 획득 대기] 🔒 (200개 스레드 줄서기!)
                           │
                           └──► [OS 디스크 write() / fsync() 시스템 콜 호출] 💾
                                (디스크 쓰기 지연: 10ms ~ 30ms 블로킹!)
                           │
                           ▼
                    [워커 스레드 복귀]
```

1. **단일 파일 동기화 락 (Lock Contention)**:  
   로그 파일(`app.log`)은 단 하나의 물리 파일입니다. 여러 스레드가 동시에 쓰면 로그 문자열이 뒤섞이므로, Appender는 내부적으로 **`synchronized` 또는 `ReentrantLock`**을 걸고 단 하나의 스레드만 파일에 쓸 수 있도록 직렬화합니다.
2. **워커 스레드의 디스크 I/O 대기 (Disk I/O Latency)**:  
   고객 요청을 빠르게 처리해야 하는 톰캣 워커 스레드가 직접 OS 디스크 `write()` 시스템 콜을 호출하여 디스크 I/O가 끝날 때까지 멍하니 블로킹됩니다.
3. **스레드 풀 고갈 (Thread Pool Starvation)**:  
   클라우드 디스크(EBS, 가상화 SSD)에 순간적인 15ms의 I/O 지연이 발생하면, 10개의 요청만 겹쳐도 마지막 스레드는 **150ms 동안 락 뒤에서 꼼짝달싹 못 하고 감옥에 갇히게 됩니다.** 동시 요청이 200개가 넘는 순간 톰캣 스레드 풀이 완전히 말라죽어 전사 시스템이 멈춥니다!

---

### 구원: LMAX 디스럽터(Disruptor) 락 프리 링 버퍼와 비동기 로깅

Apache Log4j2는 초당 수백만 건의 고주파 금융 거래를 처리하는 **LMAX Disruptor의 락 프리(Lock-Free) 원형 링 버퍼**를 도입하여 이 문제를 혁신적으로 해결했습니다.

```
[워커 스레드 1] ──┐
[워커 스레드 2] ──┼──► [LMAX Disruptor Lock-Free Ring Buffer] (초고속 원형 버퍼)
[워커 스레드 3] ──┘    (비트마스크 seq & (size - 1), 워커는 0ms 만에 즉시 복귀!)
                                │
                                ▼ (배치 꺼내기)
                 [단 1개의 백그라운드 I/O 전용 스레드]
                                │
                                ▼ (일괄 디스크 플러시!)
                     [disk.write(Batch 8건)]
```

- **워커 스레드는 0ms 복귀**: 워커 스레드는 디스크 I/O를 직접 하지 않고, 링 버퍼에 이벤트 객체만 던져두고 **즉시 0ms 만에 복귀**하여 다음 고객 요청을 처리합니다.
- **배치 플러시 (Batch Flush)**: 전용 백그라운드 I/O 스레드가 링 버퍼에 쌓인 로그를 모아 한 번에 디스크에 일괄 기록하므로 디스크 I/O 시스템 콜 횟수가 획기적으로 감소합니다.

---

### 링 버퍼 포화 시 백프레셔(Backpressure) 3대 정책

대규모 버스트 트래픽으로 링 버퍼가 가득 찰 때의 대응 정책:

1. **`BLOCK`**:
   - 빈 슬롯이 생길 때까지 워커 스레드가 대기합니다. 로그 유실은 없지만 순간 버스트 시 동기식 로거처럼 워커 스레드 지연이 폭증할 위험이 있습니다.
2. **`DISCARD_LOW_PRIORITY` (Log4j2 권장 정책)**:
   - 버퍼 사용률이 임계점(`discard_threshold_pct`, 예: 50%, 75%)에 도달하면, `DEBUG`, `INFO` 등 사소한 로그는 즉시 폐기(`DISCARDED_RING_BUFFER_PRESSURE`)하고 워커 지연을 0ms로 유지합니다.
   - 서비스 생존과 장애 분석에 필수적인 `WARN`, `ERROR` 로그만 안전하게 버퍼에 진입시켜 디스크에 기록합니다.
3. **`SYNCHRONOUS_FALLBACK` (Caller-Runs)**:
   - 버퍼가 가득 차면 대기열에 넣지 않고 워커 스레드가 직접 디스크 동기 쓰기를 수행합니다.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "logger_type": "ASYNC_DISRUPTOR",   // "SYNC_LOGGER" 또는 "ASYNC_DISRUPTOR"
  "disk_io_latency_ms": 15,            // 디스크 쓰기(단일 또는 1개 배치) 소요 시간 (ms)
  "buffer_size": 16,                   // (ASYNC) 링 버퍼 크기 (2의 거듭제곱)
  "batch_flush_size": 8,               // (ASYNC) 백그라운드 스레드가 1회에 일괄 처리할 최대 로그 수
  "overflow_policy": "DISCARD_LOW_PRIORITY", // (ASYNC) "BLOCK", "DISCARD_LOW_PRIORITY", "SYNCHRONOUS_FALLBACK"
  "discard_threshold_pct": 75,         // (선택) 폐기 시작 버퍼 사용률 (%)
  "discard_below_level": "WARN",       // (선택) 이 레벨 미만(DEBUG, INFO)을 폐기
  "log_events": [
    {
      "event_id": "evt_01",
      "thread_id": "worker_1",
      "timestamp_ms": 0,
      "level": "INFO"                  // "DEBUG", "INFO", "WARN", "ERROR"
    }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 JSON 객체를 출력합니다:

```json
{
  "summary": {
    "logger_type": "ASYNC_DISRUPTOR",
    "overflow_policy": "DISCARD_LOW_PRIORITY",
    "total_log_events": 12,
    "written_logs": 8,
    "discarded_logs": 4,
    "max_worker_blocked_ms": 0,
    "avg_worker_latency_ms": 0.0,
    "peak_buffer_usage": 6,
    "batch_flushes": 2,
    "overall_verdict": "ASYNC_DISCARD_UNDER_BURST"
  },
  "discarded_details": [
    {
      "event_id": "evt_06",
      "thread_id": "worker_1",
      "level": "INFO",
      "reason": "DISCARDED_RING_BUFFER_PRESSURE"
    }
  ],
  "written_logs_sample": [
    {
      "event_id": "evt_01",
      "thread_id": "worker_1",
      "level": "INFO",
      "written_at_ms": 15,
      "blocked_ms": 0
    }
  ]
}
```

---

## 제약 사항 및 상태 판정 기준

- 로그 레벨 우선순위: `DEBUG (1) < INFO (2) < WARN (3) < ERROR (4)`
- `written_logs_sample`에는 디스크에 성공적으로 기록된 로그 중 최초 10개까지만 포함합니다.
- `overall_verdict` 판정 기준:
  - 동기식 로거(`SYNC_LOGGER`):
    - `max_worker_blocked_ms >= 50`: `"SYNC_LOGGING_THREAD_STARVATION"`
    - 그 외: `"SYNC_LOGGING_ACCEPTABLE"`
  - 비동기 로거(`ASYNC_DISRUPTOR`):
    - `discarded_logs > 0`: `"ASYNC_DISCARD_UNDER_BURST"`
    - `discarded_logs == 0`이고 `max_worker_blocked_ms >= 50`: `"ASYNC_RING_BUFFER_OVERFLOW_BLOCKED"`
    - `discarded_logs == 0`이고 `max_worker_blocked_ms < 50`: `"ASYNC_HIGH_THROUGHPUT_OPTIMAL"`
