# Linux Kernel VirtIO Packed Virtqueue (v1.2) & Event Suppression 가속 엔진

## 문제 설명

가상화 환경(KVM/QEMU) 및 클라우드 인프라에서 게스트 OS와 호스트 하이퍼바이저 간의 고성능 I/O 가상화를 담당하는 표준 규격인 **VirtIO**는 버전 1.1 및 1.2 규격(OASIS Virtual I/O Device Specification)을 통해 혁신적인 **Packed Virtqueue (vring_packed)** 구조를 도입했습니다.

기존의 **Split Virtqueue (VirtIO 1.0)**는 3개의 독립적인 메모리 영역(Descriptor Table, Available Ring, Used Ring)으로 분리되어 있었습니다. 이로 인해 단일 I/O 버퍼를 전송할 때마다 3곳의 메모리 영역에 접근해야 하여 극심한 CPU L1/L2 캐시 미스(Cache Miss)와 메모리 배리어(`smp_wmb()`) 오버헤드가 발생했으며, SmartNIC(NVIDIA BlueField, Intel IPU) 등 하드웨어 오프로드 장치에서 PCIe 버스 트랜잭션을 증폭시키는 치명적인 한계를 노출했습니다.

**Packed Virtqueue (`VIRTIO_F_RING_PACKED`)**는 3대 링 버퍼를 크기 $N$의 단일 연속 배열(`struct vring_packed_desc`)로 완전 통합했습니다:
1. **단일 연속 링 버퍼 (Unified Contiguous Ring)**:
   - 디스크립터 메타데이터, 드라이버 제출(Avail), 디바이스 완료(Used) 상태가 단 하나의 디스크립터 구조체 안에서 비트 연산으로 관리됩니다.
2. **랩 카운터(Wrap Counter) 2위상 반전 메커니즘**:
   - 인덱스가 링 크기 $N$을 넘어 회전할 때마다 랩 카운터(`wrap_counter`)를 1에서 0, 0에서 1로 반전합니다.
   - 드라이버는 `flags` 필드의 AVAIL 비트를 자신의 랩 카운터와 일치시키고, USED 비트를 랩 카운터의 반대값으로 설정하여 버퍼를 제출합니다.
   - 디바이스는 I/O 완료 시 해당 디스크립터의 AVAIL과 USED 비트를 자신의 `used_wrap_counter`로 동시에 덮어써서 완료를 원자적으로 알립니다.
3. **이벤트 억제(Event Suppression: `vring_packed_desc_event`)**:
   - 가상화 환경에서 드라이버의 Doorbell Kick(`VM-Exit`)과 하이퍼바이저의 vCPU 가상 인터럽트(`MSI-X IRQ`)는 심각한 레이턴시 스파이크를 초래합니다.
   - `ENABLE (0x0)`, `DISABLE (0x1)`, 그리고 특정 디스크립터 인덱스 및 랩에 도달했을 때만 알리는 `DESC (0x2)` 플래그를 지원하여 컨텍스트 스위칭을 극적으로 억제합니다.
4. **간접 디스크립터 테이블 (Indirect Descriptors: `VRING_DESC_F_INDIRECT`)**:
   - 대용량 Scatter-Gather 버퍼 체인을 메인 링 버퍼에서 단 1개의 디스크립터 슬롯만 소비하면서 외부 메모리 테이블로 오프로드합니다.

당신은 리눅스 커널 가상화 및 DPDK/SPDK 고성능 I/O 서브시스템 엔지니어로서, **리눅스 커널 6.x `drivers/virtio/virtio_ring.c` 및 `include/uapi/linux/virtio_ring.h`에 명시된 VirtIO 1.2 Packed Virtqueue 상태 머신 시뮬레이션 엔진**을 구현해야 합니다.

```
+-------------------------------------------------------------------------+
|        VirtIO 1.2 Packed Virtqueue (Unified Contiguous Ring)            |
+-------------------------------------------------------------------------+
| [Slot 0] | [Slot 1] | [Slot 2] | [Slot 3] | ... | [Slot N-2] | [Slot N-1] |
+-------------------------------------------------------------------------+
    ^                      ^                          ^
    |                      |                          |
Driver Avail Idx     Device Avail Idx           Device/Driver Used Idx
(Wrap: 1 -> 0)       (Polling Descs)            (Wrap: 1 -> 0)

[Descriptor State Machine Bitmask]
- Available State: (flags & AVAIL) == wrap && (flags & USED) != wrap
- Used State:      (flags & AVAIL) == wrap && (flags & USED) == wrap
- Chaining:        VRING_DESC_F_NEXT (0x0001)
- Write Buffer:    VRING_DESC_F_WRITE (0x0002)
- Indirect Table:  VRING_DESC_F_INDIRECT (0x0004)
```

---

## 엔진 규격 및 수리적 모델링

### 1. 상수 정의
- `VRING_DESC_F_NEXT` = `0x0001`
- `VRING_DESC_F_WRITE` = `0x0002`
- `VRING_DESC_F_INDIRECT` = `0x0004`
- `VRING_PACKED_DESC_F_AVAIL` = `0x0080` (Bit 7)
- `VRING_PACKED_DESC_F_USED` = `0x8000` (Bit 15)
- `RING_EVENT_FLAGS_ENABLE` = `0x0`
- `RING_EVENT_FLAGS_DISABLE` = `0x1`
- `RING_EVENT_FLAGS_DESC` = `0x2`

### 2. 초기화 (`INIT`)
- `size`: 링 버퍼 크기 $N$ (예: 4, 8, 16 등).
- 초기 상태:
  - `driver_avail_idx = 0`, `driver_avail_wrap = 1`
  - `driver_used_idx = 0`, `driver_used_wrap = 1`
  - `device_avail_idx = 0`, `device_avail_wrap = 1`
  - `device_used_idx = 0`, `device_used_wrap = 1`
  - `free_slots = size`
  - `driver_event = {"flags": 0, "off": 0, "wrap": 0}` (ENABLE)
  - `device_event = {"flags": 0, "off": 0, "wrap": 0}` (ENABLE)
  - 카운터 초기화: `kicks_sent = 0`, `kicks_suppressed = 0`, `irqs_sent = 0`, `irqs_suppressed = 0`, `total_submitted = 0`, `total_completed = 0`, `total_descriptors_reaped = 0`.

### 3. 버퍼 제출 (`SUBMIT`)
- 입력: `buffer_id` (정수), `descriptors` (리스트)
- 검증:
  - 체인 길이 $C = \text{len}(descriptors)$
  - 만약 $\text{free\_slots} < C$ 이면 제출 실패:
    `{"status": "QUEUE_FULL", "buffer_id": buffer_id, "required": C, "free_slots": free_slots}` 반환.
- 링 기록 절차:
  - $i = 0 \dots C-1$ 번째 디스크립터에 대해:
    - 마지막 디스크립터가 아니면 `VRING_DESC_F_NEXT` 설정.
    - `write == true`이면 `VRING_DESC_F_WRITE` 설정.
    - `indirect == true`이면 `VRING_DESC_F_INDIRECT` 설정.
    - 현재 슬롯의 랩 플래그:
      - `avail_flag = VRING_PACKED_DESC_F_AVAIL` (if `curr_wrap == 1` else `0`)
      - `used_flag = 0` (if `curr_wrap == 1` else `VRING_PACKED_DESC_F_USED`)
  - **메모리 배리어 순서 보장**: $1 \dots C-1$ 번째 슬롯을 먼저 기록한 후, 헤드 디스크립터(0번째 슬롯)의 `flags`를 마지막에 기록하여 디바이스 폴링과의 레이스 컨디션을 방지합니다.
  - 드라이버 상태 갱신:
    - `driver_avail_idx = (driver_avail_idx + C) % N`
    - 경계를 넘었을 때 `driver_avail_wrap ^= 1`
    - `free_slots -= C`, `total_submitted += 1`
    - 내부 드라이버 상태 테이블에 `buffer_id -> {"num": C, "start_idx": start_idx}` 기록.
- 킥(Kick) 알림 판정:
  - `device_event` 플래그가 `DISABLE`이면 킥 억제 (`kick_notified = false`, `kicks_suppressed += 1`).
  - `ENABLE`이면 킥 전송 (`kick_notified = true`, `kicks_sent += 1`).
  - `DESC`이면 현재 배치에 기록된 디스크립터 시퀀스 중 $(target\_off, target\_wrap)$이 포함되어 있으면 킥 전송, 아니면 억제.

### 4. 디바이스 처리 (`DEVICE_PROCESS`)
- 입력: `max_chains` (최대 처리 체인 수, 기본값 16)
- 처리 루프:
  - `device_avail_idx`의 디스크립터 확인:
    - `avail_bit = 1` if `flags & AVAIL` else `0`
    - `used_bit = 1` if `flags & USED` else `0`
    - `is_avail = (avail_bit == device_avail_wrap) && (used_bit != device_avail_wrap)`
    - 만약 가용하지 않으면 즉시 루프 탈출.
  - 체인 순회:
    - `VRING_DESC_F_NEXT` 플래그가 꺼질 때까지 연속 디스크립터를 수집.
    - 간접 디스크립터(`VRING_DESC_F_INDIRECT`)인 경우 `indirect_table`의 모든 서브 엔트리 `len`을 합산, 일반 디스크립터는 자신의 `len` 합산.
  - 디바이스 가용 포인터 전진:
    - `device_avail_idx` 갱신 및 랩 카운터 전이.
  - Used 디스크립터 기록:
    - `device_used_idx` 위치부터 체인 길이 $C$개의 슬롯에 대해:
      - `flags`의 AVAIL과 USED 비트를 현재 `device_used_wrap`과 동일하게 설정:
        `used_flags = (AVAIL | USED)` if `used_wrap == 1` else `0`.
      - 헤드 슬롯에 `id = buffer_id`, `len = total_bytes` 기록.
    - `device_used_idx = (device_used_idx + C) % N`
    - 경계 횡단 시 `device_used_wrap ^= 1`.
- IRQ 인터럽트 판정:
  - 처리된 버퍼가 1개 이상일 때, `driver_event` 설정에 따라 IRQ 전송 여부 결정 (`irqs_sent` 또는 `irqs_suppressed` 증가).

### 5. 드라이버 회수 (`DRIVER_REAP`)
- 입력: `max_reap` (최대 회수 버퍼 수)
- 회수 루프:
  - `driver_used_idx` 위치의 디스크립터 확인:
    - `(avail_bit == driver_used_wrap) && (used_bit == driver_used_wrap)` 인지 검증.
    - 맞으면 완료된 버퍼! 드라이버 테이블에서 해당 `buffer_id`의 체인 길이 $C$ 조회.
    - `driver_used_idx = (driver_used_idx + C) % N` (경계 횡단 시 `driver_used_wrap ^= 1`).
    - `free_slots += C`, `total_completed += 1`, `total_descriptors_reaped += C`.

### 6. 이벤트 억제 설정 (`CONFIG_EVENT`)
- 입력: `target` ("driver" 또는 "device"), `flags` ("ENABLE", "DISABLE", "DESC"), `off` (정수), `wrap` (0 또는 1)

### 7. 상태 조회 (`INSPECT`)
- 현재 링 및 엔진의 포인터, 랩 카운터, 잔여 슬롯, 통계 반환.

---

## 입력 형식

표준 입력(stdin)으로 JSON 배열 형태의 명령어 목록이 주어집니다.

```json
[
  {"op": "INIT", "size": 8},
  {"op": "SUBMIT", "buffer_id": 1, "descriptors": [{"addr": 4096, "len": 512, "write": false}]},
  {"op": "DEVICE_PROCESS", "max_chains": 1},
  {"op": "DRIVER_REAP", "max_reap": 1},
  {"op": "INSPECT"}
]
```

---

## 출력 형식

표준 출력(stdout)으로 각 명령어의 실행 결과를 담은 JSON 배열을 공백 없이 한 줄로 출력합니다.

```json
[{"op":"INIT","status":"OK","ring_size":8},{"op":"SUBMIT","result":{"status":"SUBMITTED","buffer_id":1,"chain_len":1,"start_idx":0,"next_avail_idx":1,"avail_wrap":1,"kick_notified":true,"free_slots":7}},{"op":"DEVICE_PROCESS","result":{"status":"DEVICE_BATCH_COMPLETE","chains_processed":1,"chains":[{"buffer_id":1,"chain_len":1,"bytes_transferred":512}],"next_used_idx":1,"used_wrap":1,"irq_notified":true}},{"op":"DRIVER_REAP","result":{"status":"REAPED","count":1,"reaped":[{"buffer_id":1,"chain_len":1,"bytes_transferred":512}],"next_driver_used_idx":1,"driver_used_wrap":1,"free_slots":8}},{"op":"INSPECT","result":{"ring_size":8,"free_slots":8,"driver_avail":{"idx":1,"wrap":1},"device_avail":{"idx":1,"wrap":1},"device_used":{"idx":1,"wrap":1},"driver_used":{"idx":1,"wrap":1},"stats":{"total_submitted":1,"total_completed":1,"total_descriptors_reaped":1,"kicks_sent":1,"kicks_suppressed":0,"irqs_sent":1,"irqs_suppressed":0}}}]
```

---

## 제약 사항

- 링 버퍼 크기 $N \in \{4, 8, 16, 32, 64, 128, 256, 512, 1024\}$
- 단일 버퍼 체인 디스크립터 수 $C \in [1, N]$
- 명령어 수 $M \le 10,000$
- 시간 제한: 5.0초 이내
- 메모리 제한: 512MB
