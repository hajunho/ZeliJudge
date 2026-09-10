# Theory: Linux Kernel Memory Management: Transparent Huge Pages (THP) and khugepaged

## 1. 개요: 4KB 페이지의 한계와 TLB 미스 오버헤드

현대 컴퓨터 아키텍처(x86-64, ARM64)에서 가상 메모리 주소를 물리 메모리 주소로 변환하는 작업은 하드웨어 **MMU(Memory Management Unit)**와 **TLB(Translation Lookaside Buffer)** 캐시에 의해 처리됩니다.

- **4KB 페이지의 비극**: 64GB 램을 장착한 서버에서 4KB 기본 페이지만 사용할 경우 약 1,677만 개의 페이지가 필요합니다. 반면 CPU의 L1 dTLB 엔트리는 64~128개, L2 sTLB는 1536~2048개에 불과합니다.
- **TLB 스래싱(Thrashing)**: 대용량 데이터베이스나 인메모리 캐시(Redis, Memcached)가 임의 메모리에 접근할 때 TLB 적중률이 급락하여, CPU는 매 메모리 접근마다 4단계 페이지 테이블(PGD -> P4D -> PUD -> PMD -> PTE)을 걷는 **Page Table Walk**를 수행하며 극심한 지연을 겪습니다.

리눅스 커널은 2.6.38부터 **THP(Transparent Huge Pages)**를 도입하여, 512개의 4KB 페이지를 1개의 **2MB PMD 매핑 거대 페이지**로 묶어 TLB 엔트리 1개로 2MB 전체를 커버할 수 있게 만들었습니다.

---

## 2. THP의 생명주기 및 핵심 서브시스템

```
    [Page Fault]
          |
          v
   thp_mode 확인
          |
   +------+------+
   |             |
(always/madvise) (never/파편화)
   |             |
   v             v
[2MB 직접 할당] [4KB 폴백 할당]
                 |
                 v
        [khugepaged 백그라운드 데몬]
                 |
        (밀도 검사: >= 448 PTE)
                 |
                 v
        [Collapse: 2MB로 통합]
```

### 2.1 직접 할당(Direct Allocation) vs 폴백(Fallback)
- 애플리케이션이 메모리에 처음 접근하여 페이지 폴트가 발생했을 때, 커널은 주문형으로 즉시 2MB 연속 물리 메모리(Order-9 복합 페이지, Compound Page)를 할당하려고 시도합니다.
- 물리 메모리가 파편화(Fragmentation)되어 연속된 2MB 청크를 찾을 수 없거나 커널 모드가 `never`인 경우, 커널은 성능 저하를 방지하기 위해 4KB 기본 페이지로 즉시 폴백합니다.

### 2.2 khugepaged: 비동기 스캐너 및 지연 통합 (Collapse)
- 초기 폴백으로 인해 4KB 페이지들로 잘게 쪼개져 매핑되었더라도, 커널의 백그라운드 커널 스레드인 **`khugepaged`**가 주기적으로 가상 주소 공간을 스캔합니다.
- **`max_ptes_none` 임계값**: 2MB 범위 내에서 비어있는 PTE 수가 `max_ptes_none` (기본값 64) 이하인 경우, 즉 448개 이상의 4KB 페이지가 빽빽하게 사용되고 있는 경우, `khugepaged`는 이들을 하나의 2MB 거대 페이지로 묶는 **통합(Collapse)** 작업을 수행합니다.
- 이를 통해 파편화가 해소된 후에도 장기적으로 시스템이 거대 페이지의 혜택을 온전히 누릴 수 있습니다.

### 2.3 거대 페이지 분할 (Split Huge Page)
- 2MB 거대 페이지의 일부분에 대해서만 `munmap()`으로 메모리를 해제하거나, `mprotect()`로 접근 권한(읽기 전용 등)을 변경해야 하는 경우, 커널은 해당 2MB 거대 페이지를 512개의 독립된 4KB PTE로 원자적으로 분할(`split_huge_page`)합니다.
