# 리눅스 커널 VirtIO 및 vhost-net 스플릿 버트큐(Split Virtqueue) 링 버퍼 엔진 (Linux Kernel VirtIO & vhost-net Split Virtqueue Ring Buffer Engine)

## 문제 설명

클라우드 가상화 환경(KVM, QEMU, AWS Nitro, 쿠버네티스 OVS-DPDK)에서 구동되는 고성능 마이크로서비스 VM들이 100Gbps 대역폭의 패킷 처리 및 초당 수십만 건의 I/O를 수행하던 중, 게스트 OS와 호스트 OS 간의 과도한 컨텍스트 스위칭(**VM-Exit**)과 하이퍼바이저 인터럽트 폭풍(Interrupt Storm)으로 호스트 CPU 코어 사용률이 100%를 치솟고 패킷 드롭이 발생하는 대형 인프라 장애가 발생했습니다.

이러한 가상화 오버헤드를 근본적으로 해결하기 위해 표준화된 프레임워크가 바로 **VirtIO(Virtual I/O)** 및 리눅스 커널의 **`vhost-net` (`drivers/virtio/virtio_ring.c`, `drivers/vhost/net.c`)** 엔진입니다. VirtIO의 핵심 데이터 교환 구조는 게스트 드라이버와 호스트 하이퍼바이저가 공유 메모리 상에서 락(Lock) 없이 고속으로 통신하는 **스플릿 버트큐(Split Virtqueue)**입니다.

스플릿 버트큐는 다음 3개의 상호작용 링 버퍼로 구성됩니다:

1. **디스크립터 테이블 (Descriptor Table, `vring_desc[queue_size]`)**:
   - 게스트 물리 주소(`addr`), 버퍼 길이(`len`), 체인 플래그(`flags`), 다음 디스크립터 인덱스(`next`)를 담는 고정 배열입니다.
   - 패킷 헤더와 바디가 쪼개져 있는 경우, `VRING_DESC_F_NEXT` 플래그를 통해 단일 패킷을 여러 디스크립터의 체인(Scatter-Gather)으로 연결합니다.
2. **사용 가능 링 (Available Ring, `vring_avail`)**:
   - 게스트가 호스트에게 "이 버퍼들을 읽어달라"고 제출하는 링입니다.
   - 게스트는 체인의 헤드 인덱스를 기록하고 단조 증가하는 `avail.idx` 포인터를 1 증가시킵니다.
3. **사용 완료 링 (Used Ring, `vring_used`)**:
   - 호스트(vhost-net)가 I/O 처리를 마친 후 게스트에게 반환하는 링입니다.
   - 호스트는 처리된 헤드 인덱스와 처리 바이트 수를 기록하고 단조 증가하는 `used.idx` 포인터를 전진시킵니다.

특히 고성능 가상화의 핵심은 **알림 억제(Notification Suppression)**입니다:
- **호스트 통지 억제 (`VRING_USED_F_NO_NOTIFY`)**: 호스트가 처리량이 충분할 때 사용 완료 링의 플래그를 설정하여, 게스트가 새 버퍼를 제출하더라도 불필요한 하이퍼바이저 킥(`ioeventfd` / VM-Exit)을 날리지 않도록 억제합니다.
- **게스트 인터럽트 억제 (`VRING_AVAIL_F_NO_INTERRUPT`)**: 게스트가 폴링 모드로 동작 중일 때 사용 가능 링의 플래그를 설정하여, 호스트가 완료 처리를 하더라도 vCPU 인터럽트(`irqfd` / `call-eventfd`)를 발생시키지 않도록 차단합니다.

본 문제는 OASIS VirtIO 1.1 표준 및 리눅스 커널 vhost-net의 스플릿 버트큐 링 버퍼 메커니즘, 스캐터-게더 체이닝, 알림 억제 플래그 및 디스크립터 회수/고갈 방어 알고리즘을 충실하게 모사하는 커널급 가상화 엔진을 구현하는 것입니다.

```
  [ 게스트 OS (VirtIO Driver) ]                     [ 호스트 커널 (vhost-net) ]
              |                                                 |
   +----------v----------+                           +----------v----------+
   | 1. 디스크립터 체이닝|                           | 3. 배치 폴링 & I/O  |
   | (헤더 + 페이로드)   |                           | (체인 순회 바이트)  |
   +----------+----------+                           +----------+----------+
              |                                                 |
              v                                                 v
   [ Available Ring 기록 ]                           [ Used Ring 완료 기록 ]
   (avail.ring[idx] = head)                          (used.ring[idx] = {id, len})
   (avail.idx++)                                     (used.idx++)
              |                                                 |
   +----------v----------+                           +----------v----------+
   | 2. 호스트 킥 판정   |                           | 4. 인터럽트 발생    |
   | (NO_NOTIFY 검사)    |                           | (NO_INTERRUPT 검사) |
   +---------------------+                           +---------------------+
              |                                                 |
              +============ [ 공유 메모리 Virtqueue ] =========+
                            - Descriptor Table[N]
                            - Available Ring
                            - Used Ring
```

---

## 알고리즘 및 상태 전이 명세

### 1. 버트큐 초기화
- 큐 크기: `queue_size` (기본값: 16)
- **디스크립터 테이블**: 크기 $N$의 배열. 초기에 각 디스크립터 $i$의 `next = i + 1`, 마지막 디스크립터의 `next = -1`로 빈 디스크립터 단일 연결 리스트(`free_head = 0`)를 구성합니다.
- **Available Ring**: `flags = 0`, `idx = 0`, `ring = [0] * N`
- **Used Ring**: `flags = 0`, `idx = 0`, `ring = [{"id": 0, "len": 0}] * N`
- 호스트 소비 인덱스: `last_avail_idx = 0`, 게스트 회수 인덱스: `last_used_idx = 0`

### 2. 명령 시계열 처리

#### 1) `GUEST_SUBMIT` (게스트 버퍼 제출)
- 입력: 버퍼 목록 `buffers = [{"addr": A, "len": L, "is_write": bool}, ...]`
- 필요한 디스크립터 수: $k = 	ext{len}(buffers)$
- `free_head`로부터 $k$개의 빈 디스크립터를 탐색:
  - 부족할 경우: 상태 `"DESCRIPTOR_EXHAUSTION"`을 기록하고 제출을 중단합니다.
  - 충분할 경우: 빈 디스크립터 $k$개를 할당하고 `free_head`를 갱신합니다.
- 디스크립터 체인 연결:
  - 각 버퍼 정보를 디스크립터에 복사합니다.
  - 마지막 디스크립터를 제외하고 `VRING_DESC_F_NEXT` (1) 플래그를 설정하고 `next`를 다음 디스크립터 인덱스로 지정합니다.
  - 마지막 디스크립터는 `next = -1`로 설정합니다.
  - `is_write == True`인 경우 `VRING_DESC_F_WRITE` (2) 플래그를 추가합니다.
- 사용 가능 링 등록:
  - `avail_ring[avail_idx % queue_size] = head_idx`
  - `avail_idx += 1`
- 호스트 킥 판정:
  - `(used_flags & VRING_USED_F_NO_NOTIFY) != 0`인 경우: 킥 억제 (`kick_sent = False`)
  - 그렇지 않은 경우: 호스트 통지 발생 (`kick_sent = True`, `kicks_sent += 1`)

#### 2) `HOST_PROCESS_BATCH` (호스트 일괄 처리)
- 입력: 최대 처리 배치 크기 `max_batch` (기본값: $N$)
- `last_avail_idx < avail_idx`이고 처리 개수가 `max_batch` 미만인 동안 반복:
  - `head = avail_ring[last_avail_idx % queue_size]`
  - `last_avail_idx += 1`
  - `head`로부터 `VRING_DESC_F_NEXT` 플래그를 따라 디스크립터 체인을 순회하며 총 바이트 수(`chain_bytes`)를 합산합니다.
  - 사용 완료 링에 기록:
    - `used_ring[used_idx % queue_size] = {"id": head, "len": chain_bytes}`
    - `used_idx += 1`
- 게스트 인터럽트 판정:
  - 처리된 패킷이 1개 이상이고, `(avail_flags & VRING_AVAIL_F_NO_INTERRUPT) == 0`인 경우:
    - 인터럽트 발생 (`interrupt_raised = True`, `interrupts_raised += 1`)
  - 그렇지 않은 경우: 인터럽트 억제 (`interrupt_raised = False`)

#### 3) `GUEST_REAP` (게스트 완료 버퍼 회수)
- `last_used_idx < used_idx`인 동안 반복:
  - `head = used_ring[last_used_idx % queue_size]["id"]`
  - `last_used_idx += 1`
  - `head`로부터 디스크립터 체인을 순회하며, 각 디스크립터의 `next`를 `free_head`로 연결하고 `free_head`를 해당 디스크립터 인덱스로 갱신하여 빈 풀에 반환합니다.

#### 4) `SET_FLAGS` (통지 억제 플래그 설정)
- `avail_flags` 또는 `used_flags`를 갱신합니다.

---

## 입력 형식 (Input JSON Schema)

```json
{
  "config": {
    "queue_size": 8
  },
  "commands": [
    {
      "op": "GUEST_SUBMIT",
      "buffers": [
        {"addr": 4096, "len": 128},
        {"addr": 8192, "len": 1024}
      ]
    },
    {
      "op": "HOST_PROCESS_BATCH",
      "max_batch": 4
    },
    {
      "op": "GUEST_REAP"
    }
  ]
}
```

---

## 출력 형식 (Output JSON Schema)

```json
{
  "summary": {
    "queue_size": 8,
    "packets_processed": 1,
    "bytes_transferred": 1152,
    "kicks_sent": 1,
    "interrupts_raised": 1,
    "final_avail_idx": 1,
    "final_used_idx": 1
  },
  "command_history": [
    {
      "command_index": 1,
      "op": "GUEST_SUBMIT",
      "details": {
        "status": "SUBMITTED",
        "head_desc": 0,
        "chain_length": 2,
        "avail_idx": 1,
        "kick_sent": true
      }
    },
    {
      "command_index": 2,
      "op": "HOST_PROCESS_BATCH",
      "details": {
        "processed_count": 1,
        "batch_bytes": 1152,
        "used_idx": 1,
        "interrupt_raised": true
      }
    },
    {
      "command_index": 3,
      "op": "GUEST_REAP",
      "details": {
        "reaped_count": 1,
        "last_used_idx": 1,
        "free_head": 1
      }
    }
  ]
}
```

---

## 제약 조건

- $2 \le 	ext{queue\_size} \le 1,024$ (2의 거듭제곱 권장)
- $1 \le 	ext{commands} \le 200$
- 표준 입력(`sys.stdin`)으로부터 UTF-8 JSON 문자열을 수신하고, 결과를 `json.dumps(..., ensure_ascii=False)`로 표준 출력에 인쇄합니다.
