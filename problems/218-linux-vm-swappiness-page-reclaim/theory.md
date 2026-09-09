# 이론 백서: 리눅스 커널 가상 메모리(VM) 관리: `vm.swappiness`의 진실과 `mm/vmscan.c` 메모리 회수 동역학

## 1. 개요 및 배경 (Background)

현대 엔터프라이즈 리눅스 서버에서 메모리는 두 가지 핵심 용도로 사용됩니다:
1. **익명 메모리 (Anonymous Memory)**: 프로세스의 힙(Heap), 스택(Stack), BSS, 익명 `mmap()` 영역 및 DB 공유 메모리(`shared_buffers`). 파일 시스템에 백업되지 않으므로 디스크로 내보내려면 반드시 **스왑 공간(Swap Space)**에 기록해야 합니다.
2. **파일 백업 메모리 (File-backed Memory / Page Cache)**: 디스크 상의 파일 데이터를 메모리에 올려둔 페이지 캐시(Page Cache). 클린(Clean) 상태인 경우 디스크에 다시 쓸 필요 없이 즉시 해제(Discard/Eviction)할 수 있습니다.

많은 인프라 엔지니어와 DBA들이 "스왑이 발생하면 디스크 I/O 병목으로 시스템이 느려진다"는 단순한 직관에 이끌려 다음과 같은 설정을 적용합니다:
- `swapoff -a` (스왑 완전 비활성화)
- `sysctl -w vm.swappiness=0` 또는 `vm.swappiness=1`

그러나 이러한 설정은 메모리 부족(Memory Pressure) 상황에서 리눅스 커널이 파일 페이지 캐시를 무차별적으로 파괴하도록 강제하여, 데이터베이스의 실효 처리량을 파탄에 이르게 하는 **페이지 캐시 쓰레싱(Page Cache Thrashing)**과 **OOM Killer 돌발 종료**를 초래합니다.

---

## 2. 리눅스 커널 메모리 회수 아키텍처 (`mm/vmscan.c`)

### 2.1. 이중 LRU 리스트 구조
리눅스 커널의 각 메모리 노드/존(Zone)은 페이지들을 4개의 핵심 LRU(Least Recently Used) 리스트로 관리합니다:
- `LRU_INACTIVE_ANON`: 최근에 참조되지 않은 익명 페이지 (스왑 아웃 후보)
- `LRU_ACTIVE_ANON`: 활발히 사용 중인 익명 페이지
- `LRU_INACTIVE_FILE`: 최근에 참조되지 않은 페이지 캐시 (축출 1순위)
- `LRU_ACTIVE_FILE`: 활발히 참조 중인 페이지 캐시 (축출 2순위)

### 2.2. 존 워터마크(Zone Watermarks)와 kswapd
커널의 가용 메모리가 저수위선(`WMARK_LOW`) 아래로 떨어지면, 백그라운드 메모리 회수 데몬인 `kswapd`가 기상하여 가용 메모리가 고수위선(`WMARK_HIGH`)에 도달할 때까지 페이지 회수를 시도합니다.

```
 Physical Memory Zone
 ┌────────────────────────────────────────────────────────┐
 │ Free Memory > WMARK_HIGH   : 평온 (kswapd 수면)         │
 ├────────────────────────────────────────────────────────┤ ── WMARK_HIGH
 │ WMARK_LOW < Free < HIGH    : 안정권                     │
 ├────────────────────────────────────────────────────────┤ ── WMARK_LOW (kswapd 기상!)
 │ WMARK_MIN < Free < LOW     : 비동기 회수 진행 중        │
 ├────────────────────────────────────────────────────────┤ ── WMARK_MIN (Direct Reclaim!)
 │ Free < WMARK_MIN           : 할당 스레드 블로킹 & OOM   │
 └────────────────────────────────────────────────────────┘ ── 0 MB
```

만약 프로세스의 메모리 할당 속도가 `kswapd`의 비동기 회수 속도를 초과하여 가용 메모리가 최소 수위선(`WMARK_MIN`) 미만으로 추락하면, 메모리를 요청한 애플리케이션 스레드가 직접 메모리 회수 작업에 투입되는 **직접 회수(Direct Reclaim)** 상태에 진입하여 D-상태(Uninterruptible Sleep) 락에 걸립니다.

---

## 3. `get_scan_count()`와 `vm.swappiness`의 동작 원리

`kswapd`와 Direct Reclaim 루틴이 실행될 때, 커널은 `get_scan_count()` 함수를 호출하여 익명 LRU 리스트와 파일 LRU 리스트에서 각각 몇 개의 페이지를 스캔하여 회수할지 결정합니다.

```c
/* mm/vmscan.c get_scan_count() 핵심 공식 */
u64 anon_prio = swappiness;
u64 file_prio = 200 - swappiness;

/* 스캔 비율 */
ap = anon_prio;
fp = file_prio;
```

### 3.1. `swappiness` 값의 의미
- `swappiness = 60` (리눅스 기본값):
  $$ap = 60, \quad fp = 140 \implies \text{익명 : 파일 스캔 비율} = 30\% : 70\%$$
- `swappiness = 100`:
  $$ap = 100, \quad fp = 100 \implies \text{익명 : 파일 스캔 비율} = 50\% : 50\%$$
- `swappiness = 0` (Linux 3.5+ 커널):
  $$ap = 0, \quad fp = 200 \implies \text{익명 스캔 완전 배제 (0% : 100%)}$$

### 3.2. `swappiness = 0`의 재앙 (The 0-Swappiness Trap)
1. **페이지 캐시 완전 증발**:
   - 데이터베이스 프로세스가 힙 메모리를 점점 더 많이 차지하게 되면 가용 메모리가 줄어듭니다.
   - `swappiness = 0`이면 커널은 익명 메모리를 단 1바이트도 스왑 아웃하지 않습니다.
   - 따라서 메모리를 비워내기 위해 **오직 파일 페이지 캐시만을 $100\%$ 공격적으로 축출(Evict)**합니다.
   - 32GB 메모리 머신에서 DB 힙이 24GB를 차지하면, DB 테이블/인덱스를 캐싱하던 8GB의 페이지 캐시가 수백 MB 수준으로 증발해 버립니다.
2. **페이지 캐시 쓰레싱 (Page Cache Thrashing)**:
   - 캐시 적중률(Hit Rate)이 $95\%$에서 $20\sim 50\%$로 급락합니다.
   - 모든 데이터베이스 쿼리가 디스크 읽기 I/O(`pread64`)를 발생시킵니다.
   - NVMe/SSD의 IOPS 한계에 도달하며, `%iowait`가 $80\%$를 초과하고 쿼리 응답 지연 시간이 $0.5\text{ms}$에서 $50\sim 200\text{ms}$로 수백 배 폭증합니다.
3. **돌발 OOM Killer (Out of Memory Killer)**:
   - 더 이상 축출할 파일 캐시조차 남아있지 않은 상태에서 새 쿼리가 메모리를 요청하면, 커널은 메모리를 회수할 방법이 전혀 없으므로 Direct Reclaim에서 수 초간 멈춘 뒤 즉시 `out_of_memory()`를 호출하여 메인 DB 프로세스를 사살합니다.

---

## 4. `swappiness = 100`과 느린 스왑(Slow HDD)의 부작용

반대로 회전식 하드 디스크(HDD)에 스왑 파티션이 위치한 레거시 환경에서 `swappiness = 100`으로 과도하게 설정하면:
- 커널이 익명 페이지를 너무 적극적으로 스왑 아웃합니다.
- HDD의 느린 순차/랜덤 쓰기 속도(수십 MB/s, 밀리초 단위 탐색 시간)로 인해 I/O 대기 큐가 포화 상태에 빠집니다.
- 애플리케이션 스레드들이 스왑 쓰기 완료를 기다리느라 수십 초간 D-상태로 멈추는 **스왑 I/O 레이턴시 스파이크(`EXCESSIVE_SWAP_IO_LATENCY_SPIKE`)**가 발생합니다.

---

## 5. 최신 리눅스 커널의 해결책 및 프로덕션 권장사항

```
 +-----------------------------------------------------------------------+
 |                     현대 리눅스 메모리 계층 구조                         |
 +-----------------------------------------------------------------------+
 │  1. Physical RAM (Active Anonymous & Hot Page Cache)                  │
 │      │                                                                │
 │      ▼ 메모리 압박 시 축출 대상 판정                                       │
 │  2. zswap (In-RAM Compressed Pool: LZ4/ZSTD, 3:1 압축)                │
 │      │                                                                │
 │      ▼ zswap 풀 포화 시                                                │
 │  3. Fast NVMe Swap (0.05ms 초고속 I/O)                                │
 +-----------------------------------------------------------------------+
```

### 5.1. 올바른 `swappiness` 설정
- **NVMe SSD 스왑 환경**: `vm.swappiness = 20 ~ 30`
  - 파일 캐시를 $85\%$ 이상의 비율로 보호하면서, 극도로 차가운(Cold) 익명 메모리만을 선택적으로 스왑 아웃하여 페이지 캐시 쓰레싱과 OOM을 동시에 방지합니다.
- **zswap 활성화 환경**: `vm.swappiness = 60`
  - `zswap`은 스왑 아웃 대상 익명 페이지를 디스크로 보내는 대신, RAM 내부의 압축 풀(Compressed Pool)에 3:1 비율로 압축 보관합니다.
  - 디스크 I/O가 전혀 발생하지 않으므로, 스왑 지연 시간 없이 물리 RAM 용량을 사실상 $20\sim 30\%$ 확장하는 효과를 냅니다.

### 5.2. MGLRU (Multi-Gen LRU, Linux 6.1+)
기존 커널의 단순 2-리스트(Active/Inactive) LRU는 페이지의 접근 빈도를 정밀하게 추적하지 못했습니다.
리눅스 6.1부터 도입된 **MGLRU**는 다세대(Generation) 기반으로 페이지를 관리하며, 익명 페이지를 스왑하는 비용과 파일 페이지를 디스크에서 다시 읽어오는 비용(Refault Cost)을 수학적으로 비교합니다.
- 데이터베이스 활성 워킹셋이 페이지 캐시에 머물고 있다면, `swappiness`가 높아도 MGLRU가 파일 캐시의 세대를 보호하여 축출을 차단합니다.
- 이를 통해 클라우드 컨테이너(cgroup v2) 환경에서 페이지 캐시 적중률을 $90\%$ 이상 유지하면서도 메모리 고갈을 완벽히 방어합니다.
