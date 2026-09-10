# 리눅스 커널 락리스 메모리 배리어 및 획득-해제(Acquire-Release) 시맨틱 엔진

## 1. 개요 및 배경

현대 고성능 멀티코어 프로세서(x86-64, ARM64, RISC-V)는 메모리 지연 시간(Memory Latency)을 은폐하고 파이프라인 처리량을 극대화하기 위해 하드웨어 수준에서 명령어 비순차적 실행(Out-of-Order Execution)과 쓰기 버퍼(Store Buffer)를 적극 활용합니다.
이로 인해 컴파일러뿐만 아니라 CPU 하드웨어 자체가 프로그램 순서(Program Order)와 다른 순서로 메모리 읽기(Load)와 쓰기(Store)를 실행합니다.

- **x86-64 (TSO - Total Store Order)**: 쓰기 작업 간 순서(Store-Store)나 읽기 작업 간 순서(Load-Load)는 하드웨어가 보장하지만, 쓰기 버퍼로 인해 이전 쓰기가 공유 캐시에 반영되기 전에 후속 읽기가 먼저 실행되는 **Store-Load 재정렬(Store-Load Reordering)**이 발생합니다 (데커 알고리즘의 실패 원인).
- **ARM64 / RISC-V (약한 메모리 모델 - Weak Memory Ordering)**: Load-Load, Store-Store, Load-Store, Store-Load 모든 조합이 하드웨어에 의해 임의로 재정렬될 수 있습니다.

리눅스 커널은 락 없이 공유 메모리 데이터를 안전하게 전달하고 동기화하기 위해 **LKMM(Linux Kernel Memory Model)**과 명시적인 메모리 배리어 프리미티브를 제공합니다:
1. **`smp_store_release(&flag, 1)`**:
   - 해제(Release) 쓰기 이전에 발생한 모든 선행 메모리 쓰기(`data = 42` 등)가 다른 CPU에 먼저 가시화(Globally Visible)된 후에만 릴리즈 플래그 쓰기가 노출되도록 보장합니다 (Store Buffer 강제 플러시).
2. **`smp_load_acquire(&flag)`**:
   - 획득(Acquire) 읽기 이후에 발생하는 모든 후속 메모리 읽기/쓰기가 이 획득 연산보다 먼저 투기적으로(Speculatively) 실행되지 않도록 파이프라인 재정렬을 방어합니다.
3. **`smp_mb()` (Full Memory Barrier)**:
   - 모든 선행 Load/Store와 모든 후속 Load/Store 사이에 완전한 직렬화(Full Serialization)를 강제합니다.

본 과제에서는 LKMM의 쓰기 버퍼(Store Buffer), 스토어 포워딩(Store-to-Load Forwarding), 투기적 프리페치 무효화, 그리고 `smp_store_release`와 `smp_load_acquire` 쌍의 동기화 불변식을 시뮬레이션하는 엔진을 구현합니다.

---

## 2. 아키텍처 다이어그램

```
+-----------------------------------------------------------------------------------+
|                        CPU 0 (Producer)                                           |
|   1. WRITE data = 42 (Plain Store) ---------> [ CPU 0 Store Buffer: {data: 42} ]  |
|   2. smp_store_release(&flag, 1)                                                  |
|      * FLUSH Store Buffer to Shared Memory!                                       |
|      * WRITE flag = 1 (Committed)                                                 |
+-----------------------------------------------------------------------------------+
                                         |
                                         v (Hardware Coherent Memory Bus)
+-----------------------------------------------------------------------------------+
|                       Shared Coherent Cache / RAM                                 |
|                       { data: 42, flag: 1 }                                       |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                        CPU 1 (Consumer)                                           |
|   3. smp_load_acquire(&flag) == 1                                                 |
|      * Invalidates any stale speculative loads of 'data'!                         |
|   4. READ data == 42 (Guaranteed Fresh Value!)                                    |
+-----------------------------------------------------------------------------------+
```

---

## 3. 핵심 규칙 및 상태 전이 모델

### 3.1 쓰기 파이프라인 (`WRITE`)
- `barrier == "NONE"`:
  - CPU 로컬 `store_buffer[cpu]`에 적재됨.
  - 해당 CPU의 자체 읽기에서는 스토어 포워딩을 통해 즉시 보이지만, 타 CPU에는 보이지 않음.
- `barrier == "RELEASE"` 또는 `"FULL_MB"`:
  - CPU 로컬 `store_buffer[cpu]`에 대기 중인 모든 이전 쓰기를 순서대로 공유 메모리로 즉시 플러시!
  - 본 쓰기 값 역시 공유 메모리에 즉각 반영 (`committed_to_shared: True`).

### 3.2 읽기 파이프라인 (`READ`)
1. `barrier in ("ACQUIRE", "FULL_MB")`:
   - 해당 CPU의 모든 투기적 프리페치 캐시(`speculative_reads`)를 즉각 무효화(Clear).
2. 값 조회 우선순위:
   - 1순위: 만약 `barrier == "NONE"`이고 대상 변수가 `speculative_reads`에 존재하면 투기적 스테일 값 반환 (`source: "SPECULATIVE_PREFETCH_STALE"`).
   - 2순위: CPU 자신의 `store_buffer[cpu]` 역순 탐색 (Store-to-Load Forwarding).
   - 3순위: 공유 메모리(`memory[var]`)에서 최신 동기화 값 반환 (`source: "SHARED_COHERENT_MEMORY"`).

### 3.3 투기적 로드 (`SPECULATIVE_PREFETCH_READ`)
- 약한 메모리 모델에서 하드웨어가 플래그 확인 전에 데이터 변수를 미리 투기적으로 읽어들이는 동작을 모사.
- `smp_load_acquire`를 사용하지 않으면 투기적으로 읽었던 과거의 0(Stale) 값이 그대로 읽히는 메모리 오더링 버그가 재현됨.

---

## 4. 입출력 규격

### 입력 JSON 구조
```json
{
  "config": {
    "initial_memory": {"data": 0, "flag": 0},
    "nr_cpus": 2
  },
  "operations": [
    {"type": "WRITE", "cpu": 0, "var": "data", "val": 42, "barrier": "NONE"},
    {"type": "WRITE", "cpu": 0, "var": "flag", "val": 1, "barrier": "RELEASE"},
    {"type": "READ", "cpu": 1, "var": "flag", "read_id": "r_flag", "barrier": "ACQUIRE"},
    {"type": "READ", "cpu": 1, "var": "data", "read_id": "r_data", "barrier": "NONE"},
    {"type": "QUERY_STATE"}
  ]
}
```

### 출력 JSON 구조
```json
{
  "operation_results": [
    {
      "op_index": 0,
      "type": "WRITE",
      "cpu": 0,
      "var": "data",
      "val": 42,
      "barrier": "NONE",
      "buffered": true,
      "store_buffer_depth": 1
    },
    {
      "op_index": 1,
      "type": "WRITE",
      "cpu": 0,
      "var": "flag",
      "val": 1,
      "barrier": "RELEASE",
      "flushed_stores": 1,
      "committed_to_shared": true
    },
    {
      "op_index": 2,
      "type": "READ",
      "cpu": 1,
      "var": "flag",
      "read_id": "r_flag",
      "val": 1,
      "source": "SHARED_COHERENT_MEMORY",
      "barrier": "ACQUIRE"
    },
    {
      "op_index": 3,
      "type": "READ",
      "cpu": 1,
      "var": "data",
      "read_id": "r_data",
      "val": 42,
      "source": "SHARED_COHERENT_MEMORY",
      "barrier": "NONE"
    }
  ],
  "summary": {
    "total_operations": 5,
    "final_shared_memory": {"data": 42, "flag": 1},
    "store_buffers_count": {"0": 0, "1": 0},
    "read_results": {"r_flag": 1, "r_data": 42},
    "stats": {
      "writes": 2,
      "reads": 2,
      "store_buffer_flushes": 0,
      "acquire_barriers": 1,
      "release_barriers": 1,
      "full_mb_barriers": 0
    }
  }
}
```
