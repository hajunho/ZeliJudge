# Theory #441: 리눅스 커널 추적 계층: kernel/trace/ring_buffer.c Ftrace 락리스 링 버퍼 및 멀티-컨텍스트 동시성 이론

## 1. 커널 계측의 절대적 제약: NMI와 재진입성(Reentrancy)의 역설

운영체제 커널의 디버깅과 프로파일링을 담당하는 추적기(Ftrace, eBPF Tracepoints, Perf)는 커널의 거의 모든 명령어 위치에 프로브를 삽입할 수 있어야 합니다.
이때 직면하는 가장 가혹한 문제는 **하드웨어 인터럽트 계층의 중첩 선점**입니다:

```
[ Normal Process (TASK context) ]
      │ (calls sys_read, hits tracepoint)
      ├── Holds spinlock A
      ▼
   [ HARDWARE INTERRUPT (HARDIRQ context) ]
         │ (Timer interrupt fires on same CPU)
         ├── Preempts TASK instantly!
         ▼
      [ NON-MASKABLE INTERRUPT (NMI context) ]
            │ (CPU Perf Hardware Counter Overflow)
            ├── Preempts HARDIRQ instantly!
            ▼
         (Cannot acquire ANY lock! Deadlock if tried!)
```

만약 링 버퍼에 데이터를 삽입하기 위해 일반 스핀락(`spin_lock`)이나 세마포어를 사용한다면:
1. TASK가 락을 잡은 순간 인터럽트가 발생합니다.
2. 인터럽트 핸들러 내부의 추적기가 동일한 락을 얻으려 대기합니다.
3. 인터럽트 핸들러가 반환되어야 TASK가 실행되어 락을 풀어줄 수 있으므로, 두 실행 흐름은 동일 CPU 상에서 **영구적인 자가 데드락(Self-Deadlock)**에 빠져 시스템이 그 자리에서 멈춥니다.
4. 특히 **NMI는 소프트웨어적으로 인터럽트 비활성화(`local_irq_save`)조차 불가능**하므로 어떠한 잠금 장치도 적용할 수 없습니다.

---

## 2. Steven Rostedt의 락리스 2단계 프로토콜 (Reserve & Commit)

Steven Rostedt가 고안한 Ftrace 링 버퍼(`kernel/trace/ring_buffer.c`)는 **단일 원자적 연산(`atomic_cmpxchg`) 기반의 2단계 상태 머신**을 통해 잠금 없는 동시성을 완벽하게 달성합니다:

```
+-------------------------------------------------------------+
|                     Per-CPU Buffer Page                     |
|                                                             |
|  [Header 16B] [ Event 1 ] [ Event 2 ] [ In-flight Event 3 ] |
|  ▲                    ▲               ▲                     |
|  │                    │               │                     |
|  Read                 Commit          Write                 |
|  (Reader consumed)    (Visible)       (Reserved slot)       |
+-------------------------------------------------------------+
```

### (1) 1단계: 원자적 예약 (`ring_buffer_lock_reserve`)
- CPU의 현재 쓰기 위치(`write`)를 읽고, 원자적 비교-교환(`cmpxchg(&page->write, old, old + length)`)을 수행합니다.
- 슬롯이 성공적으로 할당되면 즉각 해당 오프셋의 메모리 포인터를 반환합니다.
- 복수의 중첩 컨텍스트(Task, IRQ, NMI)가 동시에 진입하더라도, 원자적 연산에 의해 각 컨텍스트는 서로 겹치지 않는 배타적인 메모리 범위를 분할받게 됩니다.

### (2) 2단계: 원자적 커밋 (`ring_buffer_unlock_commit`)
- 슬롯에 이벤트 페이로드(타임스탬프, PID, 함수 주소 등)의 기록을 마친 뒤 `commit` 포인터를 원자적으로 전진시킵니다.
- **리더 보호**: 사용자 공간 리더(`trace_pipe`)는 오직 `commit` 포인터 이하의 완전히 기록된 데이터만 읽을 수 있으므로, 아직 쓰기 중인 불완전한 데이터를 읽는 레이스 컨디션이 원천 차단됩니다.

---

## 3. 원형 페이지 체인과 Overwrite vs Discard 모드의 수학적 모델

Ftrace의 링 버퍼는 단일 거대 평면 메모리가 아닌, 4KB 페이지들의 **이중 연결 원형 리스트(Circular Doubly Linked List)** 구조를 취합니다.

```
       ┌───────────────────────────────────────┐
       ▼                                       │
  [ Page 0 ] ──► [ Page 1 ] ──► [ Page 2 ] ──► [ Page 3 ]
       ▲                                            ▲
       │ (Reader Drain)                             │ (Writer Head)
   head_page                                    tail_page
```

### (1) Overwrite 모드 (Flight Recorder Mode)
- 비행기 블랙박스처럼 최신 시스템 장애 직전의 로그를 보존하는 것이 목적인 경우 사용됩니다.
- 테일 페이지가 가득 차서 다음 페이지로 이동할 때, 다음 페이지가 현재 헤드 페이지(`next == head`)라면 테일이 헤드를 한 칸 밀어냅니다:
  $$\text{head} \leftarrow (\text{head} + 1) \pmod N$$
- 밀려난 헤드 페이지의 미처리 이벤트들은 폐기되며 `overwritten_events` 카운터가 증가합니다.

### (2) Discard 모드 (Produce-or-Drop Mode)
- 부팅 시점의 초기화 시퀀스나 특정 벤치마크의 전체 데이터를 순차 보존해야 할 때 사용됩니다.
- 테일이 헤드를 만났을 때 덮어쓰지 않고, 새로운 이벤트 예약을 즉각 실패 처리합니다:
  $$\text{dropped\_events} \leftarrow \text{dropped\_events} + 1$$
- 이를 통해 기존에 수집된 정상 트레이스 데이터의 무결성을 100% 보존합니다.
