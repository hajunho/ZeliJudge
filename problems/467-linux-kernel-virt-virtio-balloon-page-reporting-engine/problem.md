# 리눅스 커널 Virtio-Balloon 여유 페이지 보고(Free Page Reporting) 및 호스트 메모리 회수 엔진

## 1. 개요 및 배경

클라우드 가상화 인프라(AWS, GCP, KVM/QEMU)에서는 호스트 물리 서버의 물리 메모리(RAM)를 초과하여 게스트 가상머신(VM)을 실행하는 **메모리 오버커밋(Memory Overcommit)**이 핵심적인 비용 절감 기술입니다.
그러나 전통적인 가상화 환경에서는 치명적인 "호스트 메모리 가시성 맹점"이 존재했습니다:
- 게스트 OS(리눅스 커널) 내부에서 프로세스가 대규모 메모리를 해제하거나 페이지 캐시를 비우면, 게스트의 버디 할당자(`free_area[]`)는 해당 페이지를 여유(Free) 메모리로 표시합니다.
- 하지만 **호스트 하이퍼바이저는 게스트 내부의 메모리 해제 사실을 전혀 알 수 없습니다!** 호스트 EPT(Extended Page Table)는 여전히 물리 RAM 프레임을 유지하며, 호스트 프로세스의 실제 물리 점유량(`host_rss`)은 줄어들지 않습니다.

과거에는 이를 극복하기 위해 **전통적 벌룬 드라이버(Virtio-Balloon Inflate/Deflate, `drivers/virtio/virtio_balloon.c`)**를 사용했습니다. 그러나 이는:
1. 하이퍼바이저가 게스트에게 특정 크기만큼 강제로 메모리를 할당하라고 요청하는 수동적(Reactive) 구조입니다.
2. 급격한 메모리 회수 시 게스트 내부에서 OOM Killer가 격발되어 핵심 비즈니스 프로세스가 강제 종료되는 심각한 장애를 유발했습니다.

리눅스 커널 5.7에 도입된 **여유 페이지 보고(Free Page Reporting, `mm/page_reporting.c`)**는 이 문제를 완전히 혁신했습니다:
- **선제적/비침습적 보고**: 게스트 버디 할당자에 일정 차수 이상의 연속된 여유 블록($\text{order} \ge \text{min\_reporting\_order}$)이 반환되면, 백그라운드 워커가 이를 감지하여 Virtio 버퍼를 통해 하이퍼바이저에 "이 주소 범위는 현재 사용되지 않음"을 통보합니다.
- **호스트 즉시 환원**: 하이퍼바이저는 통보받은 게스트 주소 범위에 대해 `madvise(MADV_DONTNEED)`를 실행하여 호스트 물리 RAM을 즉각 회수(`host_rss` 감소)합니다.
- **지연 복구(Demand Fault)**: 게스트가 차후 해당 페이지를 다시 할당하여 읽거나 쓸 경우, EPT Violation Fault가 발생하여 호스트가 0으로 채워진 새 물리 프레임을 온디맨드로 투명하게 재할당합니다.

본 과제에서는 리눅스 커널 버디 할당자의 차수별 분할/병합, Virtio-Balloon 여유 페이지 보고 트리거, 호스트 RSS 증감 추적, 그리고 전통적 벌룬 팽창/수축과의 공존 메커니즘을 시뮬레이션하는 엔진을 구현합니다.

---

## 2. 아키텍처 다이어그램

```
+-----------------------------------------------------------------------------------+
|                        Guest Virtual Machine (Linux Kernel)                       |
+-----------------------------------------------------------------------------------+
|  [ Guest Workload (alloc_pages / free_pages) ]                                     |
|                                         |                                         |
|                                         v (Page Free & Buddy Coalesce)            |
|  [ Buddy Allocator (free_area[0..MAX_ORDER-1]) ]                                  |
|   - Order 0..1: Fragmented Pages (< min_reporting_order, Ignored)                 |
|   - Order >= 2: Large Contiguous Blocks (Eligible for Reporting)                  |
|                                         |                                         |
|                                         v (TRIGGER_REPORTING Worker)              |
|  [ mm/page_reporting.c: Scatter-Gather List Generation ]                          |
|   - Mark Block: UNREPORTED --> REPORTED                                           |
|   - virtqueue_add_outbuf() / virtqueue_kick()                                    |
+-----------------------------------------------------------------------------------+
                                         |
                                         v (VIRTIO_BALLOON_F_PAGE_REPORTING)
+-----------------------------------------------------------------------------------+
|                         Host Hypervisor (QEMU / KVM)                              |
|   - Receives PFN range from virtqueue                                             |
|   - madvise(addr, len, MADV_DONTNEED)                                             |
|   - Host Physical RAM Released (host_rss_pages decreased!)                        |
|                                                                                   |
|   * On re-allocation & access by Guest:                                           |
|     EPT Violation Fault --> Host allocates zero-page on demand (host_rss grows)   |
+-----------------------------------------------------------------------------------+
```

---

## 3. 핵심 규칙 및 상태 전이 모델

### 3.1 버디 할당자 분할 및 병합 규칙
- 메모리는 $2^{\text{order}}$ 크기의 블록 단위로 관리됩니다.
- 블록 해제 시 버디 인덱스 $\text{buddy\_pfn} = \text{pfn} \oplus 2^{\text{order}}$를 검사하여 동일 차수 버디가 가용 상태이면 즉시 $\text{order} + 1$로 재귀적 병합(Coalesce)합니다.
- 새로 해제되거나 병합된 블록은 기본적으로 **`UNREPORTED`** 상태가 됩니다.

### 3.2 여유 페이지 보고 (`TRIGGER_REPORTING`)
- `min_reporting_order` 이상의 차수에 존재하는 블록 중 `reported == False`인 블록을 탐색합니다.
- 대상 블록의 `reported` 플래그를 `True`로 전환하고, 총 보고된 페이지 수만큼 호스트의 실제 물리 메모리 점유량(`host_rss_pages`)을 차감합니다:
  $$\text{host\_rss\_pages} \leftarrow \max(0, \text{host\_rss\_pages} - \sum 2^{\text{order}})$$

### 3.3 할당 시의 호스트 메모리 복구
- 게스트가 `ALLOC_PAGES`를 통해 블록을 할당받을 때, 해당 블록이 이전에 `REPORTED` 상태였다면 호스트가 물리 RAM을 회수한 상태입니다.
- 게스트가 이 메모리를 사용하기 시작하면 하이퍼바이저에서 페이지 폴트가 발생하여 호스트 물리 RAM이 다시 할당되므로, `host_rss_pages`가 할당된 크기($2^{\text{order}}$)만큼 증가합니다.

### 3.4 전통적 벌룬 팽창/수축 (`INFLATE_BALLOON`, `DEFLATE_BALLOON`)
- `INFLATE_BALLOON`: 버디 할당자로부터 페이지를 할당받아 벌룬 리스트에 격리시킴으로써 게스트 여유 메모리를 강제로 줄입니다.
- `DEFLATE_BALLOON`: 벌룬 리스트의 페이지를 꺼내 게스트 버디 할당자로 반환합니다.

---

## 4. 입출력 규격

### 입력 JSON 구조
```json
{
  "config": {
    "total_pages": 64,
    "max_order": 6,
    "min_reporting_order": 2
  },
  "operations": [
    {"type": "QUERY_STATE"},
    {"type": "TRIGGER_REPORTING"},
    {"type": "ALLOC_PAGES", "alloc_id": "job1", "order": 3},
    {"type": "FREE_PAGES", "alloc_id": "job1"},
    {"type": "TRIGGER_REPORTING"},
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
      "type": "QUERY_STATE",
      "total_pages": 64,
      "guest_allocated_pages": 0,
      "balloon_pages": 0,
      "guest_free_pages": 64,
      "reported_free_pages": 0,
      "unreported_free_pages": 64,
      "host_rss_pages": 64
    },
    {
      "op_index": 1,
      "type": "TRIGGER_REPORTING",
      "status": "SUCCESS",
      "reported_blocks_count": 2,
      "newly_reported_pages": 64,
      "host_rss_pages": 0,
      "reported_blocks": [
        {"pfn": 0, "order": 5, "pages": 32},
        {"pfn": 32, "order": 5, "pages": 32}
      ]
    }
  ],
  "summary": {
    "total_operations": 6,
    "final_host_rss_pages": 0,
    "final_guest_allocated_pages": 0,
    "final_balloon_pages": 0,
    "final_reported_free_pages": 64,
    "final_unreported_free_pages": 0,
    "total_reported_events": 2,
    "total_reported_pages": 72
  }
}
```
