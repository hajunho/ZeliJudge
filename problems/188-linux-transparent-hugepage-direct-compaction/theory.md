# 깊이 있는 컴퓨터 과학: 리눅스 커널 Transparent HugePages (THP), 다이렉트 컴팩션과 CoW 증폭

## 1. 가상 메모리 페이징과 TLB 캐시 구조

### 1.1 x86-64 4단계 페이징과 4KB 기본 페이지
현대 64비트 x86-64 아키텍처는 가상 주소를 물리 주소로 변환하기 위해 4단계(또는 5단계) 페이지 테이블(PGD -> P4D -> PUD -> PMD -> PTE)을 순회(Page Table Walk)합니다.
- **기본 페이지(Base Page)**: \,\text{KB}$ (^{12}\,\text{bytes}$).
- 가상 메모리 \,\text{GB} 매핑하려면 {,}048{,}576 PTE(Page Table Entry)가 필요하며, 페이지 테이블 자체에만 수 메가바이트의 메모리가 소비됩니다.
- CPU의 MMU(Memory Management Unit)는 주소 변환 속도를 극대화하기 위해 변환 결과를 **TLB(Translation Lookaside Buffer)**에 캐싱합니다.

### 1.2 TLB Reach와 2MB 휴즈페이지 (HugePage)
- TLB 엔트리 수는 L1 dTLB 기준 보통 64~128개, L2 sTLB 기준 1024~2048개 수준으로 매우 제한적입니다.
- \,\text{KB}$ 페이지 기준 1024개 TLB 엔트리의 유효 커버리지(**TLB Reach**)는  \times 4\,\text{KB} = 4\,\text{MB} 불과합니다.
- 대용량 데이터베이스나 인메모리 캐시가 수십~수백 기가바이트를 무작위로 탐색할 때, 빈번한 TLB 미스로 인해 CPU 사이클의 \% \sim 30\%$ 이상이 Page Table Walk에 낭비됩니다.
- **2MB HugePage (Order-9 물리 페이지)**:
  - 3단계 PMD(Page Middle Directory) 엔트리에서 리프(Leaf) 플래그를 설정하여 512개의 \,\text{KB}$ 페이지를 하나의 거대한 \,\text{MB}$ 물리 연속 블록으로 매핑합니다.
  - 동일한 1024개 TLB 엔트리로  \times 2\,\text{MB} = 2\,\text{GB} 메모리를 커버할 수 있어 TLB 미스를 극적으로 제거합니다.

---

## 2. Transparent HugePages (THP) 메커니즘과 동작 한계

기존 Hugetlbfs는 애플리케이션이 특수 시스템 콜(mmap(MAP_HUGETLB))과 커널 파라미터 사전 예약(
r_hugepages)을 직접 관리해야 하는 번거로움이 있었습니다.
리눅스 2.6.38부터 도입된 **Transparent HugePages (THP)**는 사용자 코드 수정 없이도 커널이 자동으로 \,\text{MB}$ 휴즈페이지를 할당하고 관리합니다.

### 2.1 THP 할당 경로와 외적 단편화(External Fragmentation)
\,\text{MB}$ 페이지를 할당하기 위해서는 버디 할당자(Buddy Allocator)에서 **연속된 512개의 물리 페이지(Order-9)**가 반드시 확보되어야 합니다.
- 시스템이 장시간 가동되면 물리 메모리는 \,\text{KB}$ 단위로 불규칙하게 할당/해제되어 심각한 **외적 단편화(External Fragmentation)**가 발생합니다.
- 여유 메모리가 수십 기가바이트 남아있더라도, 연속된 \,\text{MB}$ 블록이 단 하나도 존재하지 않을 수 있습니다.

### 2.2 동기식 다이렉트 컴팩션 (Direct Compaction) 지연 참사
연속된 Order-9 블록이 없을 때, 커널의 동작은 /sys/kernel/mm/transparent_hugepage/defrag 설정에 따라 결정됩니다:
1. **lways (동기식 다이렉트 컴팩션, SYNC_DIRECT_COMPACT)**:
   - 메모리를 할당하려는 **사용자 애플리케이션 스레드를 그 자리에서 블로킹(Freeze)**시킵니다.
   - 커널 내부 함수 compact_zone()이 실행되며, 존(Zone)의 시작부터 사용 중인 페이지를 스캔하고(Migration Scanner), 존의 끝부터 빈 페이지를 찾아(Free Scanner) 페이지를 물리적으로 복사하고 이동시킵니다.
   - 이 과정에서 존의 lru_lock을 장시간 점유하며, 사용자 스레드는 수십 밀리초(ms)에서 수백 밀리초 동안 멈춰 서게 됩니다.
   - 결과: 초당 수만 건의 요청을 처리하던 고성능 캐시 서버(Redis, Memcached)나 초저지연 API 서버에서 치명적인 **p99/p999 지연시간 스파이크**가 발생합니다.
2. **defer / defer+madvise**:
   - 다이렉트 컴팩션을 수행하지 않고 백그라운드 데몬인 kcompactd에 작업을 위임한 뒤, 즉시 \,\text{KB}$ 기본 페이지를 폴백 할당하여 레이턴시 스파이크를 방지합니다.
3. **madvise**:
   - MADV_HUGEPAGE가 명시된 영역에 대해서만 동기 컴팩션을 시도합니다.
4. **
ever**:
   - 다이렉트 컴팩션을 일절 시도하지 않고 즉시 기본 페이지로 폴백합니다.

---

## 3. Redis fork()와 CoW (Copy-on-Write) 메모리 증폭

### 3.1 Copy-on-Write 기본 원리
Redis는 데이터 지속성(Persistence)을 위해 BGSAVE나 AOF Rewrite를 수행할 때 백그라운드 자식 프로세스를 ork()합니다.
- ork() 직후 부모와 자식은 동일한 물리 페이지를 가리키며, 페이지 테이블 엔트리를 읽기 전용(Read-Only)으로 마킹합니다.
- 어느 한쪽이 쓰기 작업을 시도하면 CPU Page Fault (do_wp_page())가 발생하여 해당 페이지를 물리적으로 복제한 후 쓰기를 허용합니다.

### 3.2 512배 쓰기 및 메모리 증폭 (Huge CoW Amplification)
- \,\text{KB}$ 기본 페이지 환경:
  - 부모 프로세스가 \,\text{bytes}$ 키-값을 수정하면, \,\text{KB}$ 페이지만 복제됩니다. 메모리 낭비는 \,\text{KB}.
- **\,\text{MB}$ THP 환경**:
  - 단 \,\text{byte}$ 또는 \,\text{bytes} 수정하더라도, 커널 핸들러(do_huge_pmd_wp_page())는 **\,\text{MB}$ (512개 페이지) 전체를 한 번에 물리 복제**합니다!
  - 10만 번의 작은 수정이 발생할 경우, 최악의 경우 수십 기가바이트의 메모리가 순식간에 복제되어 물리 메모리가 고갈됩니다.
  - 이는 시스템의 OOM(Out of Memory) 킬러를 유발하여 데이터베이스 프로세스를 강제 종료시키는 대참사로 이어집니다.

---

## 4. 백그라운드 데몬 khugepaged

- 리눅스 커널은 백그라운드 커널 스레드 khugepaged를 운용합니다.
- 주기적으로 프로세스의 가상 메모리 영역(VMA)을 스캔하여, 연속된 512개의 \,\text{KB}$ 페이지가 모두 매핑되어 있으면 이를 하나의 \,\text{MB}$ 휴즈페이지로 합치는(Collapse) 작업을 비동기로 수행합니다.
- 이를 통해 사용자 스레드의 실행을 블로킹하지 않으면서도 점진적으로 휴즈페이지 혜택을 누릴 수 있습니다.

---

## 5. 실무 엔지니어링 권장 설정

| 워크로드 유형 | 추천 THP 설정 | 비고 |
|---|---|---|
| **Redis, Memcached** | enabled=never, defrag=never | CoW 메모리 폭발 및 fork 지연 원천 차단 |
| **MongoDB, Cassandra** | enabled=never | 공식 문서상 THP 완전 비활성화 강력 권고 |
| **Java JVM (대용량 힙)** | enabled=madvise, JVM 옵션 -XX:+UseTransparentHugePages | JVM이 힙 메모리에만 선별적 madvise() 호출 |
| **대용량 데이터 분석 (ClickHouse, Presto)** | enabled=madvise 또는 enabled=always | 대규모 순차 스캔 및 TLB 미스 병목 해소 |

리눅스 커널 파라미터 런타임 적용:
`ash
echo never > /sys/kernel/mm/transparent_hugepage/enabled
echo never > /sys/kernel/mm/transparent_hugepage/defrag
`
또는 /etc/default/grub에 커널 부팅 매개변수로 추가:
`	ext
transparent_hugepage=never
`
