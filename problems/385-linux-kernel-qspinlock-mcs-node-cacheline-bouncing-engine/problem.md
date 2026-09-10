# Problem #385: Linux Kernel Queued Spinlock (qspinlock) MCS Node & Cacheline Bouncing Engine (`kernel/locking/qspinlock.c`, `kernel/locking/mcs_spinlock.h`)

## 문제 설명

대규모 멀티코어 NUMA 서버 환경에서 수십~수백 개의 CPU 코어가 단일 락(Spinlock)을 획득하기 위해 경쟁할 때, 전통적인 **티켓 스핀락(Ticket Spinlock)**은 심각한 **캐시라인 바운싱(Cacheline Bouncing)** 문제를 야기합니다.
티켓 스핀락에서는 락 소유자가 락을 해제할 때마다 단일 티켓 캐시라인을 무효화(Invalidate)하므로, 대기 중인 모든 $N$개의 CPU가 동시에 상호연결 버스(Interconnect Bus)로 몰려들어 캐시라인을 재로드(Reload)하는 $O(N^2)$ 캐시 일관성 스톰(Coherence Storm)이 발생합니다.

리눅스 커널은 이 확장성 병목을 완벽히 해결하기 위해 **큐 기반 스핀락(Queued Spinlock / qspinlock, `kernel/locking/qspinlock.c`)**을 기본 스핀락 구현체로 채택했습니다.

### qspinlock의 32비트(4바이트) 원자적 락 워드 구조

```
+----------------------------------------------------------------------------------------------------+
|                                    qspinlock 32-bit Lock Word                                      |
+------------------------------------+--------------------------------+------------------------------+
|       Bits 16..31: Tail            |        Bit 8: Pending          |      Bits 0..7: Locked       |
| (tail_cpu << 2) | nesting_idx      |  (1 = 2nd waiter waiting)      | (1 = lock held, 0 = free)    |
+------------------------------------+--------------------------------+------------------------------+
```

qspinlock은 4바이트 단일 정수 워드 내에서 3단계 계층적 락 획득 경로를 제공합니다:

1. **패스트 패스 (Fast Path - 단독 획득)**:
   - `locked == 0 && pending == 0 && tail == 0`일 때 단일 `cmpxchg` 원자 연산으로 `locked = 1`을 설정하고 즉시 획득합니다 (`FAST_PATH`).
2. **펜딩 패스 (Pending Path - 2번째 대기 코어)**:
   - 락이 이미 획득되어 있으나(`locked == 1`), 펜딩 대기자가 없고(`pending == 0`), MCS 큐 테일이 없을 때(`tail == 0`):
   - 2번째 CPU는 복잡한 MCS 큐 노드를 할당하지 않고 원자적으로 `pending = 1`을 세팅한 뒤 메인 락 워드의 `locked` 바이트만을 폴링합니다 (`PENDING_PATH`).
   - 락 소유자가 해제하면 즉시 펜딩 비트를 해제하고 락을 승계받습니다 (`HANDOFF_PENDING`).
3. **MCS 큐 패스 (MCS Queue Path - 3번째 이상 대기 코어)**:
   - 3번째 이상의 대기 CPU는 Per-CPU 배열(`qnodes[cpu][idx]`, 중첩 인터럽트 4단계: Task=0, Softirq=1, Hardirq=2, NMI=3)에서 고유의 MCS 노드를 가져옵니다.
   - 원자적 `xchg` 연산으로 락 워드의 `tail` 필드를 자신의 `(cpu << 2) | idx`로 교체하고, 이전 테일 노드의 `next` 포인터를 자신에게 연결합니다.
   - **핵심 혁신**: 대기 CPU는 메인 락 워드가 아니라 **자신의 로컬 CPU 캐시라인에 위치한 `node->locked` 플래그만을 스핀(Spin)**하므로 시스템 버스 트래픽이 0에 수렴합니다!
   - 이전 노드가 락을 넘겨주면 오직 직후 대기 노드의 캐시라인 하나만 수정되므로 캐시라인 바운싱 오버헤드가 정확히 $O(1)$로 제한됩니다.

당신은 리눅스 커널의 qspinlock 원자적 락 워드, 펜딩 비트 핸드오프, Per-CPU MCS 큐 연결 및 티켓 락 대비 캐시라인 바운싱 절감 메트릭을 정밀 시뮬레이션하는 엔진을 구현해야 합니다.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다:

```json
{
  "config": {
    "num_cpus": 8
  },
  "commands": [
    { "op": "ACQUIRE", "cpu": 1, "idx": 0, "req_id": "r1" },
    { "op": "ACQUIRE", "cpu": 2, "idx": 0, "req_id": "r2" },
    { "op": "ACQUIRE", "cpu": 3, "idx": 0, "req_id": "r3" },
    { "op": "RELEASE", "cpu": 1, "idx": 0, "req_id": "r1" },
    { "op": "RELEASE", "cpu": 2, "idx": 0, "req_id": "r2" }
  ]
}
```

- `config`:
  - `num_cpus`: 시스템 가상 CPU 코어 수 (기본값: 8)
- `commands`:
  - `ACQUIRE {cpu, idx, req_id}`: CPU `cpu`의 컨텍스트 레벨 `idx`(0: Task, 1: Softirq, 2: Hardirq, 3: NMI)에서 락 획득 시도. 재진입 시 `FAIL_REENTRANT_DEADLOCK`.
  - `RELEASE {cpu, idx, req_id}`: 락 해제 시도. 비소유자 해제 시 `FAIL_NOT_HOLDER`.

---

## 출력 형식

표준 출력(stdout)으로 공백 없이 컴팩트한 단일 JSON 객체를 출력합니다:

```json
{
  "lock_val_hex": "0x30001",
  "locked": 1,
  "pending": 0,
  "tail_cpu": 3,
  "tail_idx": 0,
  "current_holder": [3, 0, "r3"],
  "pending_waiter": null,
  "mcs_queue_len": 0,
  "cacheline_bounces": 3,
  "ticket_equivalent_bounces": 6,
  "total_acquisitions": 3,
  "events": [ ... ]
}
```

- `lock_val_hex`: 32비트 락 워드의 16진수 표현 (`locked | (pending << 8) | (tail << 16)`)
- `locked`: 현재 락 획득 여부 (0 또는 1)
- `pending`: 펜딩 대기자 여부 (0 또는 1)
- `tail_cpu`, `tail_idx`: MCS 큐의 테일 CPU 번호 및 컨텍스트 레벨
- `cacheline_bounces`: qspinlock에서 발생한 총 캐시라인 갱신 횟수 ($O(1)$)
- `ticket_equivalent_bounces`: 동등한 경쟁 조건에서 전통적 티켓 스핀락이 유발했을 캐시라인 무효화 총합 ($O(N)$ per handoff)
