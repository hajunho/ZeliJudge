# 리눅스 커널 투명한 거대 페이지(THP) 및 메모리 컴팩션 아키텍처 백서 (Theoretical Background)

## 1. 개요: 4KB 페이지의 한계와 TLB 미스 오버헤드

현대 CPU의 메모리 관리 장치(MMU)는 가상 주소를 물리 주소로 변환하기 위해 페이지 테이블(Page Table)을 탐색합니다. 이 변환 속도를 가속하기 위해 최근 변환 결과를 CPU 내부 초고속 하드웨어 캐시인 **TLB(Translation Lookaside Buffer)**에 저장합니다.

- **4KB 페이지(Order 0)의 한계**:
  - 데이터베이스나 JVM이 64GB 힙 메모리를 사용할 경우, $64	ext{ GB} / 4	ext{ KB} = 16,777,216$개의 페이지 엔트리가 필요합니다.
  - 현대 CPU의 L1/L2 TLB 엔트리는 수백~수천 개에 불과하므로, 빈번한 TLB 미스로 인해 CPU 사이클의 20~40%가 4단계 페이지 테이블 룩업(Page Table Walk)에 낭비됩니다.
- **2MB 거대 페이지(Order 9)의 혁신**:
  - $2	ext{ MB} = 512 	imes 4	ext{ KB}$ 페이지를 단일 엔트리로 매핑합니다.
  - TLB 엔트리 1개가 커버하는 메모리 범위가 512배 넓어져 TLB 미스율이 0%에 가깝게 급감합니다.

---

## 2. 컴파운드 페이지(Compound Page)와 PMD 매핑 구조

리눅스 커널은 연속된 $2^k$개의 물리 페이지 프레임을 단일한 대형 객체로 다루기 위해 **컴파운드 페이지(Compound Page)** 메커니즘을 사용합니다 (`include/linux/mm.h`):

```c
struct page {
    unsigned long flags;      /* PG_head, PG_compound 등 */
    ...
    struct page *compound_head; /* Tail 페이지가 Head를 가리키는 포인터 */
    ...
};
```

1. **`PageHead` (선두 페이지)**:
   - 거대 블록의 시작 페이지(Base PFN)입니다.
   - 전체 컴파운드 페이지의 참조 횟수(`refcount`), 페이지 차수(`compound_order`), 매핑 정보를 보관합니다.
2. **`PageTail` (후속 페이지들)**:
   - $Base + 1$부터 $Base + 511$까지의 511개 하위 페이지입니다.
   - 독립된 참조 횟수를 갖지 않고, `compound_head` 포인터를 통해 모든 조회를 선두 페이지로 위임합니다.
3. **PMD 직접 매핑**:
   - 4단계 페이징(PGD $	o$ P4D $	o$ PUD $	o$ PMD $	o$ PTE)에서 최하위 PTE 테이블을 생략하고, **PMD(Page Middle Directory)** 단계에서 직접 2MB 물리 프레임을 가리킵니다.

---

## 3. 외부 단편화와 듀얼 스캐너 메모리 컴팩션 (`compact_zone`)

메모리 사용과 해제가 반복되면 충분한 여유 메모리가 있음에도 512개의 연속된 빈 페이지가 존재하지 않는 **외부 단편화(External Fragmentation)**가 발생합니다.

리눅스 커널의 컴팩션 알고리즘(`mm/compaction.c`)은 두 개의 스캐너가 서로 마주 보고 전진하는 우아한 듀얼 포인터 기법입니다:

```
  PFN 0                                                             PFN Max
  +---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+
  | A | F | A | F | F | A | F | F | F | F | A | F | F | F | F | F | F |
  +---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+
    ^                                                               ^
    |                                                               |
  migrate_scanner                                             free_scanner
  (오른쪽으로 전진하며                                         (왼쪽으로 후진하며
   이동 대상 'A' 탐색)                                          수용 대상 'F' 탐색)
```

1. **페이지 이동 (Page Migration)**:
   - `migrate_scanner`가 발견한 할당 페이지를 `free_scanner`가 확보한 높은 PFN의 빈 페이지로 내용과 페이지 테이블 매핑을 안전하게 복제·이전합니다.
   - 이동 완료 후 원래 위치는 빈 공간(`FREE`)이 됩니다.
2. **수렴 및 종료**:
   - 앞쪽 존의 작은 구멍들이 메워지면서 앞쪽 공간이 깨끗한 대형 연속 빈 블록으로 정돈됩니다.
   - 두 스캐너가 만나는 순간 컴팩션이 완료됩니다.

---

## 4. PMD 분할 (`split_huge_pmd`)과 엔지니어링 실무 튜닝

### 1) 왜 PMD 분할이 필요한가?
- 2MB THP로 매핑된 영역 중 단 4KB 부분에 대해 프로세스가 `munmap()`이나 `madvise(MADV_DONTNEED)`를 호출하면, 2MB 전체를 한꺼번에 날릴 수 없습니다.
- 이때 커널은 즉시 `split_huge_pmd()`를 호출하여:
  1. 2MB PMD 엔트리를 새로운 512 엔트리의 4KB PTE 테이블로 교체합니다.
  2. 컴파운드 페이지의 Head/Tail 플래그를 해제하고 512개의 독립된 `struct page`로 분리합니다.
  3. 요구된 4KB 페이지만 안전하게 회수합니다.

### 2) 데이터베이스 실무 엔지니어링 팁: 왜 Redis는 THP를 끄라고 경고할까?
Redis 시작 시 다음과 같은 경고가 출력됩니다:
```
WARNING you have Transparent Huge Pages (THP) support enabled in your kernel.
This will create latency and memory usage issues with Redis.
```
- **CoW(Copy-on-Write) 증폭 참사**:
  - Redis의 `BGSAVE` 백그라운드 스냅샷은 메인 프로세스와 자식 프로세스가 메모리를 공유합니다.
  - 4KB 단위 페이징에서는 1바이트를 수정할 때 4KB만 복사하면 됩니다.
  - 하지만 THP가 활성화되어 있으면 단 1바이트를 수정해도 **2MB 전체를 복사**해야 하므로, 쓰기 증폭이 512배로 폭증하여 수백 밀리초 동안 이벤트 루프가 동결됩니다.
- **해결책**:
  ```bash
  echo never > /sys/kernel/mm/transparent_hugepage/enabled
  echo never > /sys/kernel/mm/transparent_hugepage/defrag
  ```
  또는 애플리케이션에서 선택적으로 `madvise(MADV_HUGEPAGE)`를 사용하는 방식을 채택합니다.
