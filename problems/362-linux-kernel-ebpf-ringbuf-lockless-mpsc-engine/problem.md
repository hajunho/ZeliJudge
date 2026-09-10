# Linux Kernel eBPF Ring Buffer (BPF_MAP_TYPE_RINGBUF) 다중 생산자 락리스(Lockless MPSC) 이벤트 스트리밍 엔진

## 문제 설명

리눅스 커널 5.8에 도입된 **`BPF_MAP_TYPE_RINGBUF` (`kernel/bpf/ringbuf.c`, `include/uapi/linux/bpf.h`)**는 수년간 사용되어 온 전통적인 `BPF_MAP_TYPE_PERF_EVENT_ARRAY`의 근본적 설계 한계를 극복하기 위해 안드리 나크리이코(Andrii Nakryiko) 등에 의해 개발된 차세대 커널-유저스페이스 고성능 이벤트 스트리밍 서브시스템입니다.

기존 Perf 버퍼는 CPU 코어마다 독립된 버퍼(Per-CPU Buffer)를 할당했습니다. 이로 인해 다음과 같은 심각한 비효율이 발생했습니다:
1. **메모리 불균형 및 이벤트 유실**: 특정 CPU에 이벤트가 집중되면 해당 CPU의 버퍼만 오버플로되어 이벤트가 드롭(Drop)되는 반면, 유휴 CPU의 버퍼 메모리는 낭비됨.
2. **글로벌 이벤트 순서 보장 불가**: 여러 CPU에서 발생하는 이벤트들의 전역적 발생 순서(Global Timestamp / Causality)를 소비자가 정렬하기 위해 추가적인 오버헤드가 발생.
3. **불필요한 메모리 복사**: eBPF 프로그램이 커널 메모리에 구조체를 채운 후 Perf 버퍼로 복사하는 이중 복사(Double Copy) 오버헤드.

`BPF_MAP_TYPE_RINGBUF`는 모든 CPU 코어가 공유하는 **단일 MPSC(Multi-Producer Single-Consumer) 링 버퍼**를 사용하며, 2단계 예약/커밋(Reserve & Commit) 프로토콜을 통해 완전한 **제로-카피(Zero-Copy)**를 실현합니다:

```
        [ eBPF Lockless Ring Buffer (MPSC) Architecture ]

    Multi-Producer (Kernel CPUs)                  Single-Consumer (User App)
  ┌──────────────────────────────┐              ┌──────────────────────────┐
  │ CPU 0: bpf_ringbuf_reserve() │ ──┐          │  bpf_ringbuf_consume()   │
  │ CPU 1: bpf_ringbuf_commit()  │ ──┼──┐       │  (epoll / busy-poll)     │
  │ CPU 2: bpf_ringbuf_discard() │ ──┘  │       └──────────────────────────┘
  └──────────────────────────────┘      │                     ▲
                                        ▼                     │ Reads committed
  ┌───────────────────────────────────────────────────────────┴────────────┐
  │  Shared Ring Buffer (Power of 2, 8-byte aligned)                       │
  │  [Record 1: Committed] [Record 2: Busy] [Record 3: Discarded] [Free...]│
  │  ▲                                    ▲                      ▲         │
  │  │ consumer_pos                       │ in-flight            │ prod_pos│
  └────────────────────────────────────────────────────────────────────────┘
```

본 과제에서는 Linux 커널 `kernel/bpf/ringbuf.c`의 다중 생산자 원자적 헤더 예약, 8바이트 정렬 패딩, 2단계 커밋/폐기(`COMMIT`/`DISCARD`), 미완료(Busy) 생산자에 의한 헤드-오브-라인 지연 방어 및 단일 소비자 드레인(`CONSUME`) 파이프라인을 시뮬레이션하는 **Linux Kernel eBPF Lockless MPSC Ring Buffer Engine**을 구현합니다.

---

## 핵심 엔진 아키텍처 및 규칙

### 1. 링 버퍼 메모리 및 8바이트 헤더 구조
1. 링 버퍼 크기(`ringbuf_size`)는 2의 거듭제곱(예: 64, 256, 1024)입니다.
2. 모든 레코드는 8바이트 헤더(`header`)와 페이로드(`payload`)로 구성되며, 레코드의 총 길이는 8바이트 경계로 올림(Align)됩니다:
   $$\text{total\_len} = \text{round\_up}(8 + \text{len}, 8)$$
3. 8바이트 헤더 플래그:
   - `BPF_RINGBUF_BUSY_BIT` (Bit 31): 예약 직후 설정되며, 데이터 기록 중임을 표시.
   - `BPF_RINGBUF_DISCARD_BIT` (Bit 30): 폐기된 레코드임을 표시.

### 2. 생산자 연산 (Multi-Producer)
1. **`RESERVE`**:
   - 페이로드 길이(`len`)가 주어질 때 잔여 용량을 검사합니다:
     $$\text{producer\_pos} - \text{consumer\_pos} + \text{total\_len} \le \text{ringbuf\_size}$$
   - 용량이 부족하면 할당 없이 즉시 드롭(`DROPPED_BUFFER_FULL`) 처리하고 `records_dropped += 1`.
   - 공간이 충분하면 원자적으로 `pos = producer_pos`를 획득하고 `producer_pos += total_len`.
   - 레코드는 `BUSY` 상태로 생성됩니다.
2. **`COMMIT`**:
   - `BUSY` 비트를 해제하고 레코드 상태를 `COMMITTED`로 전이시킵니다.
   - `flags == 0` 이면 대기 중인 소비자를 깨우는 웨이크업(`wakeups_triggered += 1`)을 트리거합니다. (`flags & BPF_RB_NO_WAKEUP`인 경우 웨이크업 생략).
3. **`DISCARD`**:
   - `DISCARD` 비트를 설정하고 레코드 상태를 `DISCARDED`로 전이시킵니다.

### 3. 소비자 연산 (Single-Consumer)
1. **`CONSUME`**:
   - `consumer_pos`부터 시작하여 순차적으로 레코드를 읽습니다:
   - **`BUSY` 레코드 발견 시**:
     - 생산자가 아직 데이터를 다 쓰지 않았으므로 전역 순서 유지를 위해 소비를 즉시 중단(`blocked_by_busy = true`)합니다.
   - **`DISCARDED` 레코드 발견 시**:
     - 유저 공간으로 데이터를 복사하지 않고, `consumer_pos += total_len`으로 헤더와 페이로드를 건너뜁니다(`discarded_skipped += 1`).
   - **`COMMITTED` 레코드 발견 시**:
     - 유저 버퍼로 페이로드를 전달하고, `consumer_pos += total_len`으로 전진합니다.

---

## 입력 형식

표준 입력(`stdin`)으로 JSON 객체가 주어집니다:

```json
{
  "ringbuf_size": 256,
  "operations": [
    {"op": "RESERVE", "producer_id": "cpu_0", "len": 16, "data": "trace_event_1"},
    {"op": "COMMIT", "res_id": 1, "flags": 0},
    {"op": "CONSUME", "max_records": 10}
  ]
}
```

---

## 출력 형식

표준 출력(`stdout`)으로 JSON 객체를 공백 없이 출력합니다:

```json
{
  "ringbuf_size": 256,
  "producer_pos": 24,
  "consumer_pos": 24,
  "unconsumed_bytes": 0,
  "utilization_ratio": 0.0,
  "stats": {
    "records_reserved": 1,
    "records_committed": 1,
    "records_discarded": 0,
    "records_dropped": 0,
    "records_consumed": 1,
    "bytes_reserved": 24,
    "bytes_consumed": 24,
    "wakeups_triggered": 1
  },
  "op_log": [
    ...
  ]
}
```
