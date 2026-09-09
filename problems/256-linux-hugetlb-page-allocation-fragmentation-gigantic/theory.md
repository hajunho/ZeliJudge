# 핵심 CS 및 리눅스 커널 이론: HugeTLB / hugetlbfs 가상 메모리 관리와 단편화 메커니즘

---

## 1. 가상 메모리 변환과 TLB 캐시 구조의 물리적 한계

### 1.1 페이지 테이블 워크(Page Table Walk)와 TLB 미스 페널티
현대 x86_64 아키텍처에서 프로세스가 가상 메모리 주소(Virtual Address)에 접근할 때, CPU 내부의 MMU(Memory Management Unit)는 하드웨어 4단계 페이지 테이블(CR3 레지스터 $\rightarrow$ PML4 $\rightarrow$ PDP $\rightarrow$ PD $\rightarrow$ PT $\rightarrow$ 물리 페이지)을 순회해야 합니다.

```
 가상 주소 (48-bit Canonical)
 +---------+---------+---------+---------+---------------+
 | PML4    | PDP     | PD      | PT      | Offset (12b)  |
 | (9-bit) | (9-bit) | (9-bit) | (9-bit) | (4096 Bytes)  |
 +---------+---------+---------+---------+---------------+
      |         |         |         |            |
      v         v         v         v            |
    PML4  -->  PDP  -->  PD   -->  PT   -------->+---> 물리 주소 (4KB Page)
```

이 4번의 메모리 역참조를 생략하기 위해 CPU는 **TLB (Translation Lookaside Buffer)**라는 고속 CAM(Content-Addressable Memory) 캐시를 유지합니다:
- **L1 Data TLB (dTLB)**: 보통 64개 항목 (4KB 기준 약 256KB 커버). 접근 시간: ~0.5ns (1 CPU 사이클).
- **L2 Unified TLB (sTLB)**: 보통 1,536 ~ 2,048개 항목 (4KB 기준 약 6~8MB 커버). 접근 시간: ~7ns.
- **TLB Miss 발생 시**: 메모리 버스를 통해 4단계 테이블을 워크해야 하므로 **30 ~ 150ns**의 막대한 지연이 발생합니다.

### 1.2 4KB vs 2MB vs 1GB 페이지의 수학적 TLB 커버리지

$$N_{\text{pages}} = \frac{\text{Buffer Pool Size}}{\text{Page Size}}$$

| 구분 | 페이지 크기 | 페이지 테이블 깊이 | 64GB 버퍼 필요 페이지 수 | L2 TLB (2048개) 커버리지 |
|---|---|---|---|---|
| **표준 페이지** | **4 KB** | 4단계 (PML4-PDP-PD-PT) | **16,777,216 개** | **8 MB (0.012%)** $\rightarrow$ 심각한 미스 |
| **HugeTLB** | **2 MB** | 3단계 (PML4-PDP-PD, Huge 플래그) | **32,768 개** | **4,096 MB (4 GB)** $\rightarrow$ 512배 확장 |
| **Gigantic Page**| **1 GB** | 2단계 (PML4-PDP, Huge 플래그) | **64 개** | **2,048 GB (2 TB)** $\rightarrow$ 100% Hit |

---

## 2. Linux Buddy Allocator와 Order-9 연속성 외부 단편화

### 2.1 버디 할당자(Buddy Allocator) 구조
리눅스 커널은 물리 메모리를 2의 거듭제곱 크기인 **Order ($2^{\text{order}} \times 4\text{KB}$)** 단위로 관리합니다:
- Order 0: $1 \times 4\text{KB} = 4\text{KB}$
- Order 1: $2 \times 4\text{KB} = 8\text{KB}$
- ...
- **Order 9**: $2^9 \times 4\text{KB} = 512 \times 4\text{KB} = 2,048\text{KB} = \mathbf{2\text{MB}}$ (2MB HugePage 요구 크기)
- **Order 18**: $2^{18} \times 4\text{KB} = 262,144 \times 4\text{KB} = \mathbf{1\text{GB}}$ (1GB Gigantic Page 요구 크기)

### 2.2 외부 단편화(External Fragmentation)에 의한 동적 확장 실패
시스템이 수일~수개월간 실행되면서 파일 페이지 캐시 할당, 네트워크 소켓 SKB 버퍼 생성, 사용자 힙 메모리 할당과 해제가 반복되면, **총 가용 메모리는 수십 기가바이트가 남아있더라도 연속된 2MB(Order-9) 블록이 산산이 쪼개지는 외부 단편화**가 발생합니다:

```
[물리 메모리 페이지 단편화 현황]
  [Page 0: 사용중] [Page 1: 유휴] [Page 2: 사용중] [Page 3: 유휴] ...
  -> 512개의 4KB 페이지가 물리적으로 100% 연속으로 비어있는 구간이 단 하나도 없음!
  -> 총 빈 메모리는 20GB이지만, 2MB HugePage 할당 요청은 즉시 거부됨!
```

이 상태에서 `echo N > /proc/sys/vm/nr_hugepages`를 실행하면 커널은 `alloc_contig_pages()` 또는 `kcompactd`를 동원해 메모리 압축(Compaction)을 시도하지만, 고정된 커널 언이동 페이지(Unmovable Pages)로 인해 실패하고 실제 할당량은 요청량에 훨씬 못 미치게 됩니다.

---

## 3. HugeTLB의 메모리 잠금(Pinning)과 호스트 OOM 기아 참사

### 3.1 HugeTLB 풀의 비회수성(Non-reclaimable) 특성
- 일반적인 파일 페이지 캐시는 메모리가 부족할 때 `kswapd`가 디스크로 플러시하고 즉시 회수할 수 있습니다.
- 익명(Anonymous) 힙 메모리는 스왑 파티션(`swap`)으로 방출될 수 있습니다.
- **반면 HugeTLB 풀(`hugetlb_pool`)로 예약된 메모리는 커널에 영구 고정(Pinned/Locked)됩니다.**
- 데이터베이스 프로세스가 HugePage를 1개도 사용하지 않고 유휴 상태(`HugePages_Free == HugePages_Total`)로 두더라도, **OS의 다른 일반 프로세스나 커널 버퍼는 HugeTLB 영역을 절대 침범할 수 없습니다.**

### 3.2 OOM-Killer 유발 시나리오
$$\text{Normal RAM Free} = \text{Total RAM} - (\text{HugePages\_Total} \times \text{PageSize}) - \text{Normal RAM Used}$$
- 64GB 서버에서 60GB를 HugeTLB로 잡아두면, 일반 OS에 남은 메모리는 4GB에 불과합니다.
- 배치 작업이나 백업 스크립트, 모니터링 데몬이 3.5GB의 일반 메모리를 소비하는 순간, 남은 일반 RAM이 고갈되어 리눅스 커널은 **HugeTLB에 40GB가 텅텅 비어있음에도 불구하고 프로세스를 강제 사살(OOM Killer invocation)**하게 됩니다.

---

## 4. 실무 권장 베스트 프랙티스 (Production Guidelines)

1. **부팅 시 정적 예약 (Boot-time Reservation)**:
   - 런타임 단편화 실패를 원천 방지하기 위해 `/etc/default/grub`에 커널 파라미터를 등록합니다:
     ```bash
     GRUB_CMDLINE_LINUX="default_hugepagesz=2M hugepagesz=2M hugepages=16384"
     ```
   - 1GB Gigantic Page는 부팅 파라미터 등록이 유일한 실질적 해법입니다:
     ```bash
     GRUB_CMDLINE_LINUX="default_hugepagesz=1G hugepagesz=1G hugepages=32"
     ```
2. **HugeTLB 정적 풀 크기 상한선 (70-75% 룰)**:
   - 물리 RAM의 최대 70~75%까지만 HugeTLB로 예약하고, 최소 25~30%는 OS 커널, Page Cache, 커넥션 프로세스 전용 일반 메모리로 남겨둡니다.
3. **PostgreSQL 설정 방침**:
   - 운영 환경 초기 구축 시에는 `huge_pages = on`으로 두어 HugePages가 제대로 매핑되는지 강제 검증합니다.
   - 단편화 위험이 있는 임시 환경이나 무중단 페일오버 노드에서는 `huge_pages = try`를 고려하여 서비스 기동 중단을 방지합니다.
