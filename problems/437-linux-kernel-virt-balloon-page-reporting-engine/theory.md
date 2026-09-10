# Theory #437: 리눅스 커널 가상화 메모리 최적화: mm/page_reporting.c & virtio-balloon 무손실 페이지 보고 및 포이즌 무결성 이론

## 1. 가상화 메모리 오버커밋의 근본 딜레마와 기존 벌룬(Ballooning)의 한계

클라우드 컴퓨팅 인프라(AWS Firecracker, Google Cloud KVM, OpenStack)의 경제성은 물리 RAM의 오버커밋(Overcommit) 비율에 의해 결정됩니다. 대규모 VM 풀에서 각 VM은 피크 타임에 맞춰 64GB~128GB의 vRAM을 프로비저닝받지만, 평균 유휴 시점에는 10%~20%의 메모리만 실제로 사용합니다.

전통적인 메모리 회수 기법은 다음과 같은 구조적 결함을 안고 있었습니다:

### (1) 기존 전통 벌룬(`virtio_balloon` Inflation/Deflation)
- 게스트 커널의 벌룬 드라이버가 사용자 영역 또는 커널 풀에서 페이지를 직접 할당받아 체인 리스트에 매단 뒤 호스트에 PFN 목록을 전달합니다.
- **극심한 반응 지연**: 호스트가 메모리를 회수하려면 게스트에게 풍선을 불라는 제어 메시지를 보내야 하고, 게스트가 메모리를 다 할당할 때까지 수백 ms~수 초가 소요됩니다.
- **게스트 OOM 유발**: 호스트가 벌룬을 과도하게 부풀리면, 게스트 내부 워크로드가 급증할 때 게스트가 메모리를 즉각 할당받지 못해 OOM 킬러가 작동하여 핵심 서비스가 사살됩니다.

### (2) KSM (Kernel Samepage Merging)
- 내용이 동일한 4KB 페이지를 스캔하여 단일 읽기 전용 카피로 병합(CoW)합니다.
- **막대한 CPU 오버헤드**: 수백 GB 메모리를 지속적으로 스캔하고 해시를 계산하느라 호스트 CPU 코어 1~2개가 100% 점유됩니다.
- **부채널 공격 취약점**: Meltdown/Spectre 및 캐시 타이밍 공격에 노출되어 최신 보안 환경에서는 비활성화되는 추세입니다.

---

## 2. Free Page Reporting (`mm/page_reporting.c`)의 혁신적 설계

리눅스 커널 5.7에서 Alexander Duyck에 의해 제안되어 머지된 **Free Page Reporting**은 하향식(Top-down) 할당 방식이 아닌, **상향식(Bottom-up) 버디 할당자 이벤트 가로채기(Hooking)** 구조를 가집니다.

```
+-------------------------------------------------------------+
|                        Guest Kernel                         |
|                                                             |
|   free_pages() -> free_one_page()                           |
|       │                                                     |
|       ▼                                                     |
|   [ Buddy Allocator Free Lists ]                            |
|       │                                                     |
|       ├─ Order 0~8 (< 2MB) ────────► 일반 프리 리스트 유지 |
|       │                                                     |
|       └─ Order 9+  (>= 2MB)                                 |
|              │                                              |
|              ▼                                              |
|   page_reporting_register() Hook                            |
|              │                                              |
|              ▼                                              |
|   [ Reporting Backlog Buffer ]                              |
|              │                                              |
|              ▼                                              |
|   page_reporting_cycle() Worker                             |
|              │                                              |
|              ▼ (batch_capacity scatterlist)                 |
|   virtqueue_add_outbuf()                                    |
|   virtqueue_kick(reporting_vq)                              |
+──────────────┼──────────────────────────────────────────────+
               │ virtio PCI MMIO / KVM hypercall
               ▼
+-------------------------------------------------------------+
|                        Host Hypervisor                      |
|                                                             |
|   virtio_balloon_handle_reporting()                         |
|       │                                                     |
|       ▼                                                     |
|   madvise(hva, len, MADV_DONTNEED)                          |
|       │                                                     |
|       ▼                                                     |
|   Host PTE Unmapped -> Host Physical RAM Instantly Freed!   |
+-------------------------------------------------------------+
```

### (1) Order-9 (2MB) 임계값의 수학적/하드웨어적 근거
왜 Order-0(4KB)이나 Order-4(64KB)가 아닌 **Order-9(2MB)**인가?
1. **TLB 및 HugePage 일치**: x86-64 아키텍처의 2단계 페이징 단위는 4KB(기본)와 2MB(HugePage, PMD 수준)입니다. 2MB 단위로 회수하면 호스트의 EPT(Extended Page Tables) 거대 페이지 매핑과 정확히 정렬되어 TLB 플러시 오버헤드가 극소화됩니다.
2. **Virtqueue 통신 오버헤드 완화**: 4KB 단위로 호스트에 통지할 경우 초당 수십만 번의 하이퍼바이저 VM-Exit(KVM_EXIT_IO / EPT 위반)이 발생하여 호스트 CPU가 포화됩니다. 2MB로 묶을 경우 통지 빈도가 $1/512$로 감소하여 CPU 사용률이 99% 이상 절감됩니다.

---

## 3. VIRTIO_BALLOON_F_PAGE_POISON과 메모리 무결성 메커니즘

### (1) 페이지 포이즈닝(Page Poisoning)의 작동 원리
보안 강화 리눅스 배포판이나 디버깅 커널(`CONFIG_PAGE_POISONING=y`)에서는 버디 할당자에 메모리가 반환될 때 해당 메모리 영역 전체를 `0xaa` 같은 특정 패턴으로 덮어씁니다.
목적:
1. **Use-After-Free 방지**: 이미 해제된 포인터를 역참조하는 익스플로잇이나 버그 발생 시 즉각 크래시 유발.
2. **정보 유출 차단**: 이전 프로세스의 암호화 키나 개인정보가 메모리에 잔류하는 것을 방지.

### (2) `MADV_DONTNEED`와 제로 페이지 충돌
호스트에서 `madvise(..., MADV_DONTNEED)`가 호출되면 호스트 커널은 해당 HVA 범위의 물리 페이지를 즉각 회수하고 페이지 테이블 엔트리를 비웁니다.
이후 게스트 커널이 해당 페이지를 재할당받아 읽기 작업을 수행하면:
1. EPT 폴트 발생.
2. 호스트 커널은 요청 주소에 새로운 제로 페이지(`empty_zero_page`, 즉 바이트 값이 전부 `0x00`)를 매핑해 줍니다.
3. 게스트의 포이즌 검사 루틴은 `0xaa`를 기대했으나 `0x00`이 반환되므로 **"Page poison verification failed! Kernel BUG at mm/page_poison.c"** 패닉을 일으키며 시스템 전체가 다운됩니다.

### (3) 가상화 기능 협상(Feature Negotiation)을 통한 안전장치
virtio 사양은 이를 방어하기 위해 기능 비트 `VIRTIO_BALLOON_F_PAGE_POISON` (Bit 8)을 규정합니다:
- 게스트가 포이즌을 활성화한 경우, 호스트 드라이버가 이 기능을 지원해야만 합니다.
- 호스트가 포이즌 재생성을 지원하지 않는 환경(`host_supports_poison=False`)에서는 게스트가 포이즌된 페이지를 보고하더라도 호스트는 `MADV_DONTNEED` 호출을 건너뛰고 위반 카운터(`poison_violations`)를 증가시켜 데이터 무결성을 절대적으로 보호합니다.
