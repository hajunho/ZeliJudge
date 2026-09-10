# Problem #437: 리눅스 커널 가상화 및 메모리 관리: mm/page_reporting.c & virtio_balloon 유휴 페이지 보고(Free Page Reporting) 및 포이즌(Page Poisoning) 충돌 방어 엔진

## 🌟 개요 (Executive Summary)
클라우드 하이퍼바이저 환경(KVM / QEMU)에서 가상 머신(게스트 OS)에 대규모 물리 메모리를 사전 할당(Overcommit)할 때, 게스트 내부에서 사용되지 않고 버디 할당자(Buddy Allocator) 프리 리스트에 반환된 메모리는 호스트 입장에서 여전히 실물 RAM을 점유하는 심각한 비효율을 초래합니다.
과거의 전통적인 `virtio_balloon` 팽창(Inflation) 방식은 게스트 내부 데몬이 사용자 영역 메모리를 직접 할당(`balloon_page_alloc()`)받아 하이퍼바이저에 넘겨주는 구조였기 때문에:
1. 메모리 회수 지연 시간이 길고 CPU 인터럽트 오버헤드가 막대했습니다.
2. 게스트 내부 프로세스가 갑작스러운 메모리 버스트를 요구할 때 즉각적인 수축(Deflation)이 불가능하여 OOM(Out of Memory) 패닉이 빈번했습니다.

리눅스 커널 5.7+에서는 이를 근본적으로 해결하기 위해 **비동기 유휴 페이지 자동 보고 프레임워크인 Free Page Reporting (`mm/page_reporting.c`, `drivers/virtio/virtio_balloon.c`, `CONFIG_PAGE_REPORTING`)**을 도입하였습니다:
- **버디 할당자 연동 (Buddy Hooking)**: 게스트 OS 내에서 메모리가 해제될 때, 설정된 임계 차수(`PAGE_REPORTING_MIN_ORDER`, 기본값 Order-9 = 512페이지 = 2MB 대형 페이지 단위) 이상의 유휴 메모리 블록을 감지하여 비동기 보고 큐(Backlog)에 등록합니다. 2MB 미만의 소형 파편(Order 0~8)은 무시하여 보고 오버헤드를 최소화합니다.
- **Virtqueue 기반 비동기 일괄 전송 (Batch Processing)**: 백로그에 축적된 연속 PFN 범위를 스캐터-게더(Scatter-Gather) 목록으로 패킹하여 최대 배치 용량(`batch_capacity`) 단위로 가상 큐(`reporting_vq`)에 적재한 뒤 하이퍼바이저에 비동기 통지(Kick)합니다.
- **호스트 `madvise(MADV_DONTNEED)` 무손실 물리 메모리 즉시 회수**: 호스트 하이퍼바이저는 통지받은 게스트 물리 주소(GPA)에 대응하는 호스트 가상 주소(HVA)에 대해 `madvise(..., MADV_DONTNEED)`를 호출하여 실물 물리 페이지 프레임을 즉시 호스트 커널 여유 풀로 반환합니다.
- **페이지 포이즈닝(Page Poisoning) 무결성 보존 및 기능 협상**:
  - 게스트 커널이 디버깅이나 보안을 위해 해제된 메모리를 특정 패턴(예: `0xaa`)으로 채우는 `CONFIG_PAGE_POISONING`을 사용할 경우, 호스트가 `madvise(MADV_DONTNEED)`를 수행하면 이후 게스트가 해당 주소에 접근(Refault)할 때 호스트는 0으로 채워진 제로 페이지(Zero Page)를 매핑해 줍니다.
  - 이로 인해 게스트는 기대했던 포이즌 패턴(`0xaa`) 대신 `0x00`을 읽게 되어 커널 패닉이 발생합니다.
  - 리눅스 virtio 표준은 `VIRTIO_BALLOON_F_PAGE_POISON` 플래그 협상을 통해 호스트가 포이즌 재생성을 지원하지 못하는 경우(`host_supports_poison=False`) 해당 블록의 하이퍼바이저 회수를 스킵하고 위반 횟수(`poison_violations`)를 기록하여 무결성 붕괴를 원천 방어합니다.
- **무지연 재할당 (Zero-penalty Immediate Reallocation)**: 게스트 버디 할당자가 보고 완료된 풀에서 메모리를 다시 할당받을 때 별도의 수축 요청 없이 즉시 사용할 수 있으며, 쓰기 작업 시 호스트 EPT/NPT 페이지 폴트가 발생하여 새로운 물리 RAM이 즉각 공급됩니다.

본 문제에서는 리눅스 커널 `mm/page_reporting.c` 및 `drivers/virtio/virtio_balloon.c`의 버디 차수 필터링, 비동기 배치 virtqueue 통지, 호스트 메모리 회수, 포이즌 보호 및 재할당 엔진을 시뮬레이션합니다.

---

## 🏗️ 아키텍처 및 시스템 흐름도 (System Architecture)

```
       [ Guest Kernel: Buddy Allocator ]
                      │
            page_reporting_register()
                      │
        Free memory block (pfn, order)
                      │
               order >= min_order (e.g. 9 = 2MB)?
              ┌───────┴───────┐
             Yes              No
              │               │
              ▼               ▼
      [ Push to Backlog ]  [ Ignored: Below Min Order ]
              │
              ▼
   [ PROCESS_REPORTING Triggered ]
              │
   Pop batch (up to batch_capacity entries)
              │
   Check Page Poisoning:
   Is guest poison != 0x00 AND host_supports_poison == False?
              ┌───────┴───────┐
             Yes              No
              │               │
              ▼               ▼
     [ Skip Host Reclaim ]   [ Host madvise(MADV_DONTNEED) ]
     poison_violations++     total_reported_pages += nr_pages
     host_reclaimed = False  reclaimed_bytes += nr * page_size
              │               │
              └───────┬───────┘
                      ▼
        [ virtqueue_kicks++ ]
        [ Append to reported_ranges ]
                      │
                      ▼
      [ Subsequent Guest BUDDY_ALLOC ]
       Reuse reported range immediately
       (Host triggers EPT fault on demand)
```

---

## ⚙️ I/O 데이터 규격 (Input/Output Specifications)

### 1. 입력 JSON 구조
```json
{
  "config": {
    "page_size": 4096,
    "min_order": 9,
    "batch_capacity": 16,
    "poison_check": true,
    "guest_poison_val": 0,
    "host_supports_poison": true
  },
  "trace": [
    {"op": "BUDDY_FREE", "pfn": 65536, "order": 9},
    {"op": "BUDDY_FREE", "pfn": 131072, "order": 4},
    {"op": "PROCESS_REPORTING"},
    {"op": "BUDDY_ALLOC", "handle_id": "ALLOC_1", "order": 9},
    {"op": "GET_STATS"}
  ]
}
```

### 2. 필드 정의
- `config`:
  - `page_size` (int, default=4096): 가상 머신 기본 페이지 크기 (바이트).
  - `min_order` (int, default=9): 보고 대상 최소 버디 차수 (기본 9 = $2^9 = 512$ 페이지 = 2MB).
  - `batch_capacity` (int, default=16): 1회 `PROCESS_REPORTING` 호출 시 virtqueue로 일괄 전송할 수 있는 최대 엔트리 수.
  - `poison_check` (bool, default=true): 게스트 포이즌 검사 활성화 여부.
  - `guest_poison_val` (int, default=0): 게스트의 기본 포이즌 바이트 값 (`0x00` 또는 `0xaa` 등).
  - `host_supports_poison` (bool, default=true): 호스트의 `VIRTIO_BALLOON_F_PAGE_POISON` 지원 여부.
- `trace` 명령어:
  1. `BUDDY_FREE`:
     - `pfn` (int): 해제된 페이지 프레임 번호 (Page Frame Number).
     - `order` (int): 버디 할당자 차수 ($nr\_pages = 2^{\text{order}}$).
     - `poison` (int, optional): 해당 블록의 포이즌 값. 생략 시 `guest_poison_val` 적용.
  2. `PROCESS_REPORTING`:
     - 축적된 백로그에서 최대 `batch_capacity`개 엔트리를 꺼내 virtqueue를 통해 호스트에 전달 및 회수 처리.
  3. `BUDDY_ALLOC`:
     - `handle_id` (str): 할당 핸들 식별자.
     - `order` (int): 요청 차수 ($nr\_pages = 2^{\text{order}}$).
     - 보고 완료된 풀(`reported_ranges`)에서 조건에 맞는 블록을 우선 할당하며, 없을 경우 신규 주소 할당.
  4. `GET_STATS`:
     - 현재 엔진 누적 통계 조회.

### 3. 출력 JSON 구조
```json
{
  "events": [
    {
      "op": "BUDDY_FREE",
      "pfn": 65536,
      "order": 9,
      "nr_pages": 512,
      "status": "QUEUED_FOR_REPORTING",
      "backlog_count": 1
    },
    ...
  ],
  "summary": {
    "total_reported_pages": 512,
    "host_reclaimed_bytes": 2097152,
    "poison_violations": 0,
    "virtqueue_kicks": 1,
    "final_backlog_entries": 0,
    "final_reported_ranges": 0
  }
}
```
