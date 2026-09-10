# Linux Kernel eBPF Lockless Ring Buffer 심층 이론 및 수리적 분석

## 1. Perf Buffer (PERF_EVENT_ARRAY)의 한계와 Ring Buffer의 탄생

Linux 4.4에서 도입된 BPF Perf Event Array는 각 CPU 코어마다 독립된 원형 버퍼를 할당하는 Per-CPU 구조였습니다.

### 1.1 Per-CPU Perf Buffer의 3대 구조적 결함
1. **메모리 단편화 및 불균형(Imbalance)**:
   - 64코어 서버에서 4MB 버퍼를 설정하면 총 256MB의 고정 메모리가 커널에 잠깁니다. 특정 워커 스레드가 집중된 코어(CPU 0)는 버퍼가 넘쳐 레코드가 드롭되는데, 다른 유휴 코어(CPU 1~63)의 수백 메가바이트는 완전히 낭비됩니다.
2. **이벤트 순서(Global Event Ordering) 보장 불가**:
   - 각 코어가 독립 버퍼에 쓰기 때문에, 사용자는 여러 CPU의 이벤트를 타임스탬프 기준으로 k-way 병합 정렬해야 하므로 심각한 지연이 발생합니다.
3. **더블 카피(Double Copy) 오버헤드**:
   - `bpf_perf_event_output()`을 호출하기 전 스택이나 BPF 맵에 데이터를 준비한 후 다시 Perf 버퍼로 복사해야 했습니다.

### 1.2 BPF_MAP_TYPE_RINGBUF의 해결책
리눅스 5.8에 추가된 BPF Ring Buffer는 모든 CPU가 단일 메모리 영역을 공유하는 **MPSC (Multi-Producer Single-Consumer) 락리스 링 버퍼**입니다.
- **단일 글로벌 링 버퍼**: 메모리 효율 극대화, 코어 간 워크로드 불균형 완벽 해소.
- **글로벌 FIFO 순서 보장**: 예약 시점에 전역 시퀀스가 확정되므로 유저 공간 정렬 불필요.
- **Zero-Copy 메모리 예약**: `bpf_ringbuf_reserve()`로 버퍼 내 실제 위치 포인터를 직접 받아 바로 데이터를 기록.

---

## 2. 락리스 2단계 예약-커밋 프로토콜 (Lockless Reserve-Commit Protocol)

### 2.1 8바이트 헤더 메타데이터
링 버퍼의 모든 레코드는 8바이트 메타데이터 헤더로 시작합니다:
```c
struct bpf_ringbuf_hdr {
    u32 len; /* 하위 30비트: 길이, 비트 31: BUSY, 비트 30: DISCARD */
    u32 pg_off; /* 디버그/오프셋 정보 */
};
```
- **Bit 31 (`BPF_RINGBUF_BUSY_BIT` = 0x80000000)**: 생산자가 현재 데이터를 쓰는 중.
- **Bit 30 (`BPF_RINGBUF_DISCARD_BIT` = 0x40000000)**: 필터링 등으로 인해 폐기된 레코드.

### 2.2 원자적 포인터 전진
생산자는 `__sync_fetch_and_add(&rb->producer_pos, total_len)` 원자적 연산으로 자신의 구간을 락 없이 획득합니다:
$$\text{total\_len} = (8 + \text{len} + 7) \land \sim 7$$
만약 `producer_pos - consumer_pos + total_len > ringbuf_size` 이면, 포인터를 갱신하지 않고 즉시 드롭합니다.

### 2.3 커밋 및 폐기
- **`bpf_ringbuf_commit()`**:
  - 메모리 배리어(`smp_wmb()`)를 수행한 후 헤더의 `BUSY` 비트를 원자적으로 클리어합니다.
  - 이제 소비자가 이 레코드를 읽을 수 있습니다.
- **`bpf_ringbuf_discard()`**:
  - `DISCARD` 비트를 1로 설정하고 `BUSY` 비트를 클리어합니다. 소비자는 유저 공간으로 복사하지 않고 포인터만 건너뜁니다.

---

## 3. 소비자 동기화 및 가상 메모리 더블 매핑 (Double Mapping Trick)

### 3.1 링 버퍼 끝에서의 연속성 (Double Virtual Memory Mapping)
링 버퍼의 가장 큰 기술적 난제는 데이터가 링의 끝(Wrap-around)에 걸칠 때 메모리가 두 조각으로 쪼개지는 현상입니다.
- Linux 커널은 링 버퍼 데이터 페이지들을 유저 가상 주소 공간에 **연속해서 두 번 매핑(mmap)**합니다:
  $$[0 \sim N) \quad \text{and} \quad [N \sim 2N)$$
- 따라서 인덱스가 $N$을 초과하더라도 유저 애플리케이션은 포인터 래핑 처리 없이 단일 연속 메모리 포인터로 읽을 수 있습니다.

### 3.2 헤드-오브-라인 블로킹 (Head-of-Line Blocking)
MPSC 링 버퍼에서 만약 CPU 0이 레코드 1을 예약한 뒤 느리게 기록 중(`BUSY`)인데, CPU 1이 레코드 2를 먼저 커밋했더라도, 소비자는 레코드 1 앞에서 반드시 대기합니다. 이는 이벤트의 엄격한 시간순 FIFO를 보장하기 위한 커널의 핵심 원칙입니다.
