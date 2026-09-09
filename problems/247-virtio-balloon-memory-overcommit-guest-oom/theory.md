# 문제 247 이론: Linux Kernel 가상화 — KVM/QEMU virtio-balloon 메모리 오버커밋, OOM Killer 연쇄 반응 및 virtio-mem 아키텍처

---

## 1. 하이퍼바이저 메모리 가상화와 오버커밋 (Memory Overcommit)

클라우드 가상화 인프라에서 하이퍼바이저(KVM/QEMU)는 호스트 물리 메모리(Host Physical Address, HPA)를 게스트 가상머신에게 게스트 물리 메모리(Guest Physical Address, GPA) 형태로 노출합니다.

```
+-------------------------------------------------------------+
| Guest Virtual Address (GVA)                                 |
+-------------------------------------------------------------+
               │ CR3 / Guest Page Table
               ▼
+-------------------------------------------------------------+
| Guest Physical Address (GPA)                                |
+-------------------------------------------------------------+
               │ EPT (Extended Page Tables) / NPT (AMD)
               ▼
+-------------------------------------------------------------+
| Host Physical Address (HPA)                                 |
+-------------------------------------------------------------+
```

실제 운영 환경에서 모든 가상머신이 할당받은 메모리를 100% 상시 사용하는 경우는 드뭅니다. 따라서 클라우드 사업자는 서버 물리 메모리의 1.2배 ~ 2.0배에 달하는 vRAM을 프로비저닝하는 **메모리 오버커밋**을 수행합니다. 그러나 호스트 전체 메모리 압박이 심해질 경우, 특정 VM의 메모리를 동적으로 회수하여 다른 VM에 재분배하는 메커니즘이 필수적입니다.

---

## 2. virtio-balloon의 내부 동작 원리

`virtio-balloon`은 게스트 리눅스 커널 내부에서 구동되는 반가상화 디바이스 드라이버(`drivers/virtio/virtio_balloon.c`)입니다.

```
   [ QEMU Hypervisor ]                    [ Guest Linux Kernel ]
          │                                         │
          │ 1. Set Config: target = 4096            │
          ├────────────────────────────────────────►│
          │                                         │ 2. balloon_page_alloc()
          │                                         │    alloc_pages(4KB)
          │                                         │
          │ 3. Virtqueue: PFNs [0x120, 0x121...]   │
          │◄────────────────────────────────────────┤
          │                                         │
          │ 4. madvise(HPA, len, MADV_DONTNEED)    │
          │    Host RAM released!                   │
```

### (1) 팽창 (Inflation) 메커니즘
1. 하이퍼바이저가 PCI Configuration 공간의 `target` 필드를 증가시킵니다.
2. 게스트 드라이버는 인터럽트(VIRQ)를 수신하고 커널 워커 스레드를 깨워 `alloc_pages()`를 루프 돌며 메모리를 할당받습니다.
3. 할당받은 물리 페이지 프레임 번호(PFN) 목록을 Virtqueue(`inflateq`)에 담아 하이퍼바이저로 보냅니다.
4. QEMU 하이퍼바이저는 해당 GPA에 대응하는 자신의 익명 메모리 영역에 대해 `madvise(MADV_DONTNEED)` 시스템 콜을 호출하여 호스트 물리 RAM 매핑을 해제합니다. 이로써 호스트 OS는 해당 물리 페이지를 회수합니다.

### (2) 수축 (Deflation) 메커니즘
1. 하이퍼바이저가 `target` 필드를 줄이거나 게스트가 메모리를 요구하면 `deflateq`를 통해 PFN 목록이 교환됩니다.
2. 게스트 드라이버는 보유하고 있던 페이지들을 `__free_pages()`를 통해 리눅스 버디 할당자(Buddy Allocator)로 반환합니다.

---

## 3. 대형 장애 패턴 분석 (Production Failure Modes)

### (1) `deflate-on-oom` 미설정으로 인한 게스트 OOM Killer 참사
virtio-balloon이 팽창하여 수 기가바이트의 메모리를 점유하고 있는 상황에서, 게스트 내부 프로세스(PostgreSQL, Redis 등)가 대량의 메모리를 할당받으려 할 때 문제가 발생합니다.
- 리눅스 커널은 가용 메모리가 고갈되면 `out_of_memory()`를 호출합니다.
- 만약 QEMU 설정에서 `deflate-on-oom=on`(`VIRTIO_BALLOON_F_DEFLATE_ON_OOM`) 플래그가 비활성화되어 있다면, 게스트 커널은 **풍선 내부에 묶여 있는 메모리를 회수할 수 있는 메모리로 인식하지 못합니다.**
- 결국 게스트 커널은 가장 OOM 점수가 높은 주 데이터베이스 프로세스를 `SIGKILL`로 즉시 강제 종료합니다. 호스트에는 수십 GB의 메모리가 남아있음에도 서비스가 파멸하는 원인입니다.
- **해결책**:
  ```bash
  # QEMU 실행 옵션
  -device virtio-balloon-pci,id=balloon0,deflate-on-oom=on
  ```
  이 옵션이 활성화되면 게스트 커널의 `oom_notify_list`에 풍선 드라이버의 콜백(`balloon_oom_notify`)이 등록되어, OOM Killer가 프로세스를 죽이기 직전에 풍선 메모리를 즉시 버디 할당자로 반환합니다.

### (2) 급격한 팽창과 Direct Reclaim 지연 폭증
호스트가 풍선 크기를 초당 수 기가바이트씩 급격히 늘리면:
- 게스트 백그라운드 페이지 회수 데몬(`kswapd`)의 회수 속도보다 할당 요구 속도가 훨씬 빨라집니다.
- 메모리 수위가 `watermark_low` 아래로 떨어지면서 모든 메모리 할당 스레드가 **Direct Reclaim (`try_to_free_pages`)** 루프로 진입합니다.
- 디렉토리 엔트리(dentry), 아이노드(inode) 캐시 락 경합 및 클린 페이지 동기식 해제로 인해 CPU kworker가 100%를 치고 응답 시간이 수 초간 정지(Freeze)됩니다.

### (3) 4KB 풍선 할당에 의한 Transparent HugePage (THP) 파괴
- 고성능 데이터베이스(Oracle, Postgres, Java)는 2MB 단위의 Transparent HugePage(THP)를 사용하여 TLB 미스를 대폭 줄입니다.
- 전통적인 virtio-balloon은 기본 4KB 단위(`VIRTIO_BALLOON_F_BALLOON_4K`)로 페이지를 뜯어갑니다.
- 버디 할당자에 여유 4KB 페이지가 없으면, 2MB 크기의 Compound HugePage들을 강제로 512개의 4KB 페이지로 쪼개는 **`split_huge_page()`**를 수행합니다.
- 결과적으로 거대한 연속 메모리가 파괴되고, TLB 캐시 미스율이 급증하여 데이터베이스의 쿼리 처리 성능이 30%~50% 이상 영구적으로 하락합니다.

### (4) 호스트-게스트 이중 스왑 (Double Swapping)
- 게스트 VM에 가상 스왑 파티션/스왑 파일이 설정되어 있고 `swappiness > 0`인 경우:
  1. 풍선이 커지면 게스트 커널은 메모리를 비우기 위해 익명 페이지들을 가상 디스크(스왑 파일)로 씁니다.
  2. 그런데 가상 디스크 파일 자체는 호스트의 파일 시스템 위에 존재합니다.
  3. 호스트 역시 물리 메모리가 모자라면 QEMU 가상머신의 메모리 페이지들을 호스트의 물리 스왑 파티션으로 밀어냅니다.
- 게스트가 스왑 아웃한 페이지를 호스트가 다시 스왑 아웃하는 이중 스왑(Double Paging)이 발생하여 스토리지 IOPS가 100% 포화되고 시스템이 완전한 무응답(Unresponsive) 상태에 빠집니다.

---

## 4. 차세대 해결책: virtio-mem과 Cgroup v2 메모리 보호

### (1) virtio-mem (Next-Gen Dynamic Memory Ballooning)
전통적인 virtio-balloon의 단점(4KB 분할, HugePage 파괴, NUMA 미인식)을 극복하기 위해 Linux 5.8+ 및 QEMU 5.1+에 도입된 혁신 기술입니다:
- 메모리를 페이지 단위가 아니라 2MB/4MB/128MB 단위의 **서브블록(Sub-block)** 단위로 핫플러그(Hotplug) 및 언플러그(Unplug)합니다.
- HugePage의 정렬(Alignment)을 완벽하게 보존하여 THP Shattering 문제를 원천 차단합니다.
- NUMA 노드 단위로 메모리를 정확히 바인딩할 수 있습니다.

### (2) Cgroup v2를 통한 게스트 내 핵심 프로세스 보호
```bash
# PostgreSQL 서비스의 cgroup에 최소 보장 메모리 설정
systemctl edit postgresql

[Service]
MemoryMin=8G
MemoryLow=12G
```
- `memory.min`: 커널이 어떠한 경우에도 회수할 수 없는 하드 보호선(Hard Guarantee)을 설정하여 풍선 팽창 압박에도 DB의 메모리를 절대 빼앗기지 않도록 방어합니다.
