# VirtIO 1.2 Packed Virtqueue (vring_packed) & Event Suppression 심층 이론

## 1. 개요: Split Virtqueue의 한계와 Packed Virtqueue의 탄생

가상화 시스템(KVM/QEMU, Xen, Hyper-V)에서 게스트 OS(드라이버)와 호스트 하이퍼바이저(디바이스) 간의 패킷 및 블록 I/O 전송 성능은 전체 클라우드 인프라의 처리량을 결정짓는 핵심 병목입니다. 2008년 러스 러셀(Rusty Russell)에 의해 리눅스 커널에 도입된 **VirtIO 1.0 (Split Virtqueue)** 규격은 다음과 같은 3개의 분리된 메모리 링 구조를 사용했습니다:

1. **디스크립터 테이블 (Descriptor Table)**: 물리 메모리 주소(`addr`), 길이(`len`), 다음 인덱스(`next`), 플래그(`flags`)를 포함하는 고정 크기 배열.
2. **Available Ring**: 드라이버가 준비한 디스크립터 헤드 인덱스를 순차적으로 적는 링 버퍼.
3. **Used Ring**: 디바이스가 처리를 완료한 디스크립터 인덱스와 바이트 수를 기록하는 링 버퍼.

### Split Virtqueue의 치명적 병목점:
- **캐시 오염 및 메모리 접근 분산**: 단 하나의 I/O 패킷을 전송하더라도 드라이버는 Descriptor Table에 데이터를 쓰고, Available Ring에 인덱스를 쓴 뒤 `idx`를 증가시켜야 합니다. 디바이스 역시 Available Ring을 읽고, Descriptor Table을 읽은 뒤, Used Ring에 완료 결과를 기록합니다. 이 3개 구조체는 캐시 라인이 분리되어 있어 메모리 접근당 최소 3~6회의 캐시 미스(Cacheline Miss)가 발생합니다.
- **하드웨어 오프로드(SmartNIC) 비효율성**: DPU/IPU 및 SmartNIC가 PCIe 버스를 통해 호스트 DRAM에 접근할 때, 3개 영역을 횡단하며 읽고 쓰느라 PCIe TLP(Transaction Layer Packet) 오버헤드가 3배 이상 폭증합니다.

이에 따라 OASIS VirtIO 기술 위원회는 **VirtIO 1.1 규격(2019년)**에서 단일 연속 배열로 3대 링을 일체화한 **Packed Virtqueue (`VIRTIO_F_RING_PACKED`)**를 표준화했습니다.

---

## 2. Packed Virtqueue 아키텍처 및 랩 카운터 메커니즘

Packed Virtqueue는 $N$개의 원소를 갖는 단일 `struct vring_packed_desc` 배열로 구성됩니다:

```c
struct vring_packed_desc {
    __le64 addr;
    __le32 len;
    __le16 id;
    __le16 flags;
};
```

### 랩 카운터(Wrap Counter) 기반 동기화
전통적인 링 버퍼는 생산자와 소비자 간의 경합을 방지하기 위해 별도의 인덱스 변수(`avail->idx`, `used->idx`)를 공유 메모리에 두고 원자적 연산을 수행했습니다. 반면 Packed Virtqueue는 각 디스크립터 내부의 **`AVAIL` (Bit 7)과 `USED` (Bit 15)** 비트 2개만을 활용하여 **완전 락리스(Lockless)** 상태 전이를 달성합니다:

1. **상태 판별 규칙**:
   - 디스크립터는 생산자(드라이버)와 소비자(디바이스)가 각자의 로컬 랩 카운터(`wrap_counter`)를 유지합니다.
   - 드라이버는 링의 끝($N-1$)에 도달하여 0번 인덱스로 래핑할 때마다 `avail_wrap_counter ^= 1`을 수행합니다.
   - **Available 상태**: `(flags & AVAIL) == wrap && (flags & USED) != wrap`
   - **Used 상태**: `(flags & AVAIL) == wrap && (flags & USED) == wrap`

| 랩 위상 | 초기/미사용 상태 | 드라이버 제출(Avail) | 디바이스 완료(Used) |
|:---:|:---:|:---:|:---:|
| **Round 0 (Wrap = 1)** | AVAIL=0, USED=0 | **AVAIL=1, USED=0** | **AVAIL=1, USED=1** |
| **Round 1 (Wrap = 0)** | AVAIL=1, USED=1 | **AVAIL=0, USED=1** | **AVAIL=0, USED=0** |

이 2위상 반전 덕분에 링 전체를 초기화(`memset`)하거나 인덱스를 재설정할 필요 없이, 단일 비트 토글만으로 무한히 연속 순환할 수 있습니다.

---

## 3. 체이닝 및 메모리 배리어 순서 보장 (SMP Safety)

Scatter-Gather I/O에서 버퍼가 $C$개의 디스크립터로 분할될 때, `VRING_DESC_F_NEXT` 비트로 체인을 구성합니다:
- 디바이스가 링을 폴링하고 있을 때, 드라이버가 0번 헤드 디스크립터를 먼저 기록하면 디바이스는 아직 쓰이지 않은 1번, 2번 디스크립터를 읽어버리는 **경합 조건(Race Condition)**이 발생합니다.
- 따라서 드라이버는 반드시 **$1 \dots C-1$ 번째 테일 디스크립터를 먼저 링에 기록**하고, 메모리 쓰기 배리어(`smp_wmb()`)를 수행한 후, **0번째 헤드 디스크립터의 AVAIL 플래그를 가장 마지막에 기록**해야 합니다.

```
[Driver Write Ordering]
Step 1: Write Desc[1] (flags: NEXT | avail_wrap)
Step 2: Write Desc[2] (flags: LAST | avail_wrap)
Step 3: smp_wmb()  <-- 메모리 배리어 (파이프라인 플러시)
Step 4: Write Desc[0] (flags: NEXT | avail_wrap)  <-- 원자적 유효화!
```

---

## 4. 이벤트 억제 (Event Suppression: `vring_packed_desc_event`)

가상화에서 가장 무거운 연산은 VM-Exit(Guest -> Host)와 vCPU vInterrupt 주입(Host -> Guest)입니다.
Packed Virtqueue는 양방향 이벤트 억제를 위해 단 4바이트의 구조체를 사용합니다:

```c
struct vring_packed_desc_event {
    __le16 desc_event_off_wrap; /* bit 0..14: offset, bit 15: wrap */
    __le16 desc_event_flags;    /* 0: ENABLE, 1: DISABLE, 2: DESC */
};
```

1. `RING_EVENT_FLAGS_DISABLE (0x1)`:
   - 상대방에게 알림(Doorbell Kick 또는 MSI-X 인터럽트)을 일체 보내지 말 것을 지시합니다. 고속 폴링(DPDK PMD) 모드에서 필수적입니다.
2. `RING_EVENT_FLAGS_ENABLE (0x0)`:
   - 모든 배치 작업 완료 시 즉각 통지합니다.
3. `RING_EVENT_FLAGS_DESC (0x2)`:
   - 지정된 `(desc_event_off, desc_event_wrap)` 슬롯이 처리되는 시점에만 인터럽트를 발생시킵니다. 이를 통해 수백 개의 버퍼를 단 한 번의 인터럽트로 묶어 처리하는 **어댑티브 인터럽트 코얼레싱(Adaptive Interrupt Coalescing)**을 하드웨어 수준에서 구현할 수 있습니다.

---

## 5. 커널 소스 코드 매핑

- `drivers/virtio/virtio_ring.c`:
  - `virtqueue_add_packed()`: Packed 링에 버퍼 체인 추가 및 메모리 배리어 관리.
  - `virtqueue_get_buf_ctx_packed()`: 완료된 디스크립터 폴링 및 드라이버 회수.
  - `vring_need_event_packed()`: 이벤트 억제 구조체를 참조하여 Kick/IRQ 트리거 여부 산출.
- `include/uapi/linux/virtio_ring.h`:
  - `struct vring_packed_desc`, `struct vring_packed_desc_event`, 각종 플래그 매크로 정의.
