# 리눅스 커널 Virtio-Balloon 및 여유 페이지 보고(Free Page Reporting) 아키텍처 이론

## 1. 하이퍼바이저 오버커밋과 물리 메모리 맹점

클라우드 데이터센터 환경에서 호스트 서버는 다수의 게스트 가상머신(QEMU/KVM 인스턴스)을 구동합니다.
호스트 물리 메모리가 256GB일 때, 각 64GB RAM을 갖는 VM 8대(총 512GB 가상 RAM)를 오버커밋하여 배치할 수 있는 이유는 모든 VM이 동시에 100% 메모리를 사용하지 않는다는 통계적 다중화 원리 때문입니다.

그러나 게스트 내부에서 메모리가 해제될 때 하이퍼바이저는 다음과 같은 구조적 한계에 부딪힙니다:
1. **EPT(Extended Page Tables) 단방향성**: 게스트가 메모리를 처음 쓸 때(First Touch)는 EPT Violation이 발생하여 하이퍼바이저가 물리 프레임을 할당하지만, 게스트가 메모리를 반환할 때는 CPU 하드웨어 트랩(VM-Exit)이 전혀 발생하지 않습니다.
2. **호스트 메모리 누수 현상(Guest Footprint Retention)**: 게스트 OS가 수십 기가바이트의 메모리를 버디 할당자에 반환해도, 호스트는 이를 알지 못해 물리 메모리를 계속 쥐고 있어 다른 활성 VM에 메모리를 나눠주지 못하는 메모리 기아(Host Memory Starvation)가 발생합니다.

---

## 2. 전통적 Virtio-Balloon의 한계

초기 해결책이었던 `virtio_balloon` 드라이버(`drivers/virtio/virtio_balloon.c`)는 게스트 커널 내부에 "풍선"을 부풀리는 방식이었습니다:
- **팽창(Inflation)**: 하이퍼바이저가 게스트 드라이버에 `inflation`을 지시하면, 드라이버가 게스트 커널의 `alloc_pages()`를 루프 돌며 메모리를 점유하고, 이 물리 프레임 번호(PFN)를 하이퍼바이저에 넘겨 호스트가 `madvise(MADV_DONTNEED)`로 회수합니다.
- **수축(Deflation)**: 게스트에 메모리가 필요하면 벌룬에 묶여있던 페이지를 `free_pages()`로 게스트 커널에 돌려줍니다.

### 문제점:
1. **수동적/지연성(High Latency)**: 호스트의 메모리 압박이 감지된 뒤에야 QEMU 모니터를 통해 벌룬 크기를 조절하므로 반응이 매우 느립니다.
2. **게스트 OOM 위험**: 게스트 내부의 실제 워크로드 메모리 수요를 알지 못하는 상태에서 하이퍼바이저가 과도하게 벌룬을 팽창시키면, 게스트의 커널 메모리가 고갈되어 프로덕션 프로세스가 OOM-Killer에 의해 살해당합니다.

---

## 3. 혁신: Free Page Reporting (`mm/page_reporting.c`)

리눅스 커널 5.7에 추가된 **여유 페이지 보고(Free Page Reporting)**는 버디 할당자의 코어와 하이퍼바이저 Virtio 장치를 직접 연동하는 현대적 아키텍처입니다:

### 3.1 최소 보고 차수 (`PAGE_REPORTING_MIN_ORDER`)
- 작은 4KB 페이지(Order 0)나 8KB 페이지(Order 1)가 반환될 때마다 Virtqueue로 통보하면, 통신 오버헤드(Virtqueue Kick, VM-Exit)가 I/O 대역폭을 잠식합니다.
- 따라서 커널은 기본적으로 **Order 5나 6 (128KB ~ 2MB)** 이상의 거대한 연속 블록이 버디 할당자에 존재할 때만 배치로 보고합니다.

### 3.2 Scatter-Gather 리스트와 비동기 워커
- 버디 할당자에 고차수 블록이 반환되면 지연 워커(`schedule_delayed_work`)가 기동됩니다.
- 워커는 `free_area[order]`의 락을 잡고 미보고 블록들을 스캔하여 `scatterlist` 배열에 모은 뒤, Virtio 드라이버의 `virtqueue_add_outbuf()`를 호출합니다.
- QEMU 하이퍼바이저는 해당 게스트 물리 주소 범위를 받아 즉각 `madvise(MADV_DONTNEED)`를 수행하여 호스트 페이지를 커널에 반납합니다.

### 3.3 온디맨드 복구 (Transparent Faulting)
게스트가 나중에 보고된 페이지를 다시 할당받아 쓰기 작업을 수행하면:
1. 호스트 EPT에서 해당 엔트리는 Present가 아니므로 **EPT Misconfiguration / Violation**이 트리거됩니다.
2. KVM 하이퍼바이저의 페이지 폴트 핸들러가 가동되어 호스트의 빈 물리 프레임 하나를 0으로 초기화(Zero-fill)하여 EPT에 매핑합니다.
3. 게스트는 아무런 중단이나 에러 없이 정상적으로 메모리를 사용할 수 있습니다.

이 메커니즘을 통해 클라우드 제공업체는 게스트의 성능이나 안정성을 1%도 저해하지 않으면서 유휴 VM들로부터 수십%의 호스트 물리 RAM을 실시간으로 회수하여 집적도(Density)를 극대화할 수 있습니다.
