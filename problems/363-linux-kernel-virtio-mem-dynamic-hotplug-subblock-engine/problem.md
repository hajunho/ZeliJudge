# Linux Kernel virtio-mem 동적 물리 메모리 서브블록(Sub-Block) 핫플러그 및 풍선 없는(Balloonless) 오프라인 엔진

## 문제 설명

리눅스 커널 가상화 서브시스템(`drivers/virtio/virtio_mem.c`, `include/uapi/linux/virtio_mem.h`)의 **`virtio-mem`**은 기존의 가상 머신 메모리 벌루닝(`virtio-balloon`)과 ACPI 기반 거대 물리 메모리 핫플러그(DIMM Hotplug)가 가진 치명적인 단점들을 완벽히 해결하기 위해 개발된 차세대 동적 메모리 관리 기제입니다.

전통적인 방식들의 고질적 한계:
1. **전통적 벌루닝 (`virtio-balloon`)의 한계**:
   - 게스트 OS 내부의 버디 할당자(Buddy Allocator)에서 4KB 페이지를 무차별적으로 훔쳐와 호스트로 반환하므로, 게스트 내부 메모리가 극심하게 파편화되어 2MB HugePage가 깨지고, 게스트에 급격한 부하가 걸리면 커널 OOM 킬러가 오작동함.
2. **ACPI DIMM 기반 핫플러그의 한계**:
   - 기가바이트(1GB~2GB) 단위로만 메모리를 꽂거나 뽑을 수 있어 크기 조절이 투박함.
   - 특히 메모리를 줄이려고 할 때(Hotunplug), 해당 1GB 블록 안에 단 하나의 커널 고정 페이지(Pinned/Unmovable page, e.g. SLAB 캐시, DMA 버퍼)만 있어도 전체 블록의 언플러그가 영구히 실패함.

`virtio-mem`은 게스트 물리 주소 공간(GPA)에 사전 예약된 연속 메모리 윈도우(`window_size_mb`, e.g. 512MB~16GB)를 두고, 이를 128MB 단위의 **메모리 블록(Memory Block)**과 2MB~4MB 단위의 **서브블록(Sub-Block)**으로 세분화하여 관리합니다:

```
      [ virtio-mem Preallocated Contiguous Window & Sub-Block Model ]

   Guest Physical Address (GPA) Window (e.g. 512 MB Window)
  ┌─────────────────────────────────┬─────────────────────────────────┐
  │ Memory Block 0 (128 MB)         │ Memory Block 1 (128 MB)         │
  │ [sb0][sb1][sb2]...[sb62][sb63]  │ [sb64][sb65]...                 │
  └─────────────────────────────────┴─────────────────────────────────┘
    ▲
    │ Sub-Block states:
    ├─ UNPLUGGED : Host RAM not mapped (Zero host footprint)
    ├─ PLUGGED   : Online in Linux buddy allocator (Backed by Host RAM)
    └─ PINNED    : Kernel unmovable allocation present (Cannot unplug!)
```

하이퍼바이저가 게스트 메모리 목표 크기(`requested_size_mb`)를 동적으로 설정하면:
- **메모리 확장 (Plug)**: 낮은 주소의 미할당 서브블록(`UNPLUGGED`)부터 차례로 호스트 RAM을 매핑하고 커널 버디 할당자에 온라인(`online_pages()`)시킵니다.
- **메모리 축소 (Unplug)**: 높은 주소의 서브블록(`PLUGGED`)부터 역순으로 페이지를 격리(`MIGRATE_ISOLATE`) 및 회수한 후 오프라인 처리하고 호스트 RAM 매핑을 해제합니다.
- 만약 특정 서브블록이 커널에 의해 고정(`PINNED`)되어 있다면, 해당 서브블록을 안전하게 우회하여 다른 플러그된 서브블록을 회수합니다.

본 과제에서는 Linux 커널 `drivers/virtio/virtio_mem.c`의 GPA 윈도우 서브블록 상태 머신, 양방향 핫플러그/언플러그, 커널 비이동성 페이지 고정(Pinning) 감지 및 언플러그 교착(Stall) 텔레메트리를 시뮬레이션하는 **Linux Kernel virtio-mem Sub-Block Engine**을 구현합니다.

---

## 핵심 엔진 아키텍처 및 규칙

### 1. GPA 윈도우 및 서브블록 분할
1. 전체 윈도우 크기 `window_size_mb`, 블록 크기 `block_size_mb`, 서브블록 크기 `subblock_size_mb` (기본 2MB)가 주어집니다.
2. 서브블록 총 개수:
   $$N = \text{window\_size\_mb} / \text{subblock\_size\_mb}$$
3. 각 서브블록(인덱스 $0 \le i < N$)은 3가지 상태를 가집니다:
   - `UNPLUGGED`: 호스트 미매핑, 게스트 미사용.
   - `PLUGGED`: 호스트 RAM 매핑됨, 게스트 버디 할당자 사용 가능.
   - `PINNED`: 게스트 커널의 비이동성 페이지가 할당되어 언플러그 불가능한 상태.

### 2. 동적 크기 조절 알고리즘 (`SET_REQUESTED_SIZE`)
목표 크기 `target_mb`가 주어지면 `requested_size_mb`를 갱신하고 rebalance를 수행합니다:
1. 현재 플러그된 서브블록 수: `current_plugged_count = count(PLUGGED + PINNED)`.
2. 목표 서브블록 수: `target_count = target_mb / subblock_size_mb`.
3. $\Delta = \text{target\_count} - \text{current\_plugged\_count}$:
   - **$\Delta > 0$ (Plug 확장)**:
     - 인덱스 $0$부터 $N-1$까지 순차 스캔하여 `UNPLUGGED` 서브블록을 `PLUGGED`로 전환합니다.
     - 목표 수량(`delta`)에 도달하거나 윈도우 끝에 도달할 때까지 반복.
   - **$\Delta < 0$ (Unplug 축소)**:
     - 인덱스 $N-1$부터 $0$까지 **역순(최고 주소부터)** 스캔합니다.
     - `PLUGGED` 상태인 서브블록은 즉시 `UNPLUGGED`로 오프라인 회수합니다.
     - `PINNED` 상태인 서브블록은 언플러그할 수 없으므로 건너뛰며 `pinned_blocked += 1`, `unplug_failures_pinned += 1`.
     - 필요 수량(`abs(delta)`)에 도달하거나 $0$번에 도달할 때까지 반복.

### 3. 고정(Pin) 및 고정 해제(Unpin)
1. **`PIN_SUBBLOCK`**: 지정된 서브블록이 `PLUGGED` 상태이면 `PINNED`로 전환합니다.
2. **`UNPIN_SUBBLOCK`**: 지정된 서브블록이 `PINNED` 상태이면 `PLUGGED`로 복원합니다.

### 4. 교착(Stall) 판정
- 연산 종료 후, 실제로 남아있는 플러그 용량이 요청된 목표 용량을 초과하면(`current_plugged_mb > requested_size_mb`), 커널 페이지 고정에 의해 언플러그가 정체된 상태로 판정하여 `unplug_stalled_by_pinning = true`로 플래그합니다.

---

## 입력 형식

표준 입력(`stdin`)으로 JSON 객체가 주어집니다:

```json
{
  "window_size_mb": 256,
  "block_size_mb": 128,
  "subblock_size_mb": 2,
  "initial_plugged_mb": 64,
  "operations": [
    {"op": "PIN_SUBBLOCK", "subblock_idx": 31},
    {"op": "SET_REQUESTED_SIZE", "target_mb": 128},
    {"op": "SET_REQUESTED_SIZE", "target_mb": 32}
  ]
}
```

---

## 출력 형식

표준 출력(`stdout`)으로 JSON 객체를 공백 없이 출력합니다:

```json
{
  "window_size_mb": 256,
  "block_size_mb": 128,
  "subblock_size_mb": 2,
  "requested_size_mb": 32,
  "current_plugged_mb": 32,
  "pinned_mb": 2,
  "plugged_subblocks_count": 16,
  "pinned_subblocks_count": 1,
  "unplug_stalled_by_pinning": false,
  "stats": {
    "plug_requests": 1,
    "unplug_requests": 1,
    "subblocks_plugged": 64,
    "subblocks_unplugged": 48,
    "unplug_failures_pinned": 1
  },
  "op_log": [
    ...
  ]
}
```
