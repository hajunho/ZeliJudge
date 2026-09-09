# 메모리 할당자 내부 아키텍처: Glibc Ptmalloc vs Jemalloc 심층 분석

## 1. 개요: 현대 멀티코어 환경과 동적 메모리 할당의 딜레마

C/C++, Rust, Go, JVM 등 현대 시스템 프로그래밍 언어와 런타임에서 `malloc()`과 `free()`는 가장 빈번하게 호출되는 기초 연산입니다.  
초기 유닉스 시절 Doug Lea가 설계한 **dlmalloc**은 단일 스레드 환경에서 메모리 사용률을 극대화하는 훌륭한 알고리즘이었으나, 수십~수백 개의 CPU 코어가 병렬로 동작하는 현대 서버 환경에서는 극심한 성능 한계에 직면했습니다:

1. **글로벌 락 병목 (Global Lock Contention)**: 모든 스레드가 단 하나의 힙 뮤텍스를 획득하기 위해 줄을 서며 CPU 코어가 수십 개여도 단일 코어 수준으로 성능이 추락.
2. **외적 단편화 (External Fragmentation)**: 메모리가 작은 조각으로 잘게 쪼개져 총 유휴 메모리는 충분하지만 연속된 공간이 부족하여 새 할당이 실패하거나 RSS가 기형적으로 비대화.
3. **OS 메모리 반환 불가 (Lack of Purging / High Watermark Issue)**: 할당된 메모리를 해제하더라도 물리 메모리(RSS)가 커널로 환원되지 않고 프로세스가 점유한 채 남아 OOM Killer를 유발.

이 문제를 해결하기 위해 등장한 대표적인 두 현대 메모리 할당자가 리눅스 표준인 **Glibc Ptmalloc**과 고성능 분산 시스템의 표준인 **Jemalloc**입니다.

---

## 2. Glibc Ptmalloc의 내부 구조와 한계

Glibc의 기본 메모리 할당자인 Ptmalloc(현재 ptmalloc3 기반)은 Wolfram Gloger가 dlmalloc에 멀티스레드 지원을 추가한 구조입니다.

```
+-------------------------------------------------------------------------+
|                           Glibc Ptmalloc                                |
|                                                                         |
|  [Thread 1]     [Thread 2]       [Thread 3]     [Thread 4]              |
|       \             /                 \             /                   |
|        \           /                   \           /                    |
|       +-------------+                 +-------------+                   |
|       | Arena 0     |                 | Arena 1     |                   |
|       | [Mutex Lock]|                 | [Mutex Lock]|                   |
|       |             |                 |             |                   |
|       | - Fastbins  |                 | - Fastbins  |                   |
|       | - Smallbins |                 | - Smallbins |                   |
|       | - Largebins |                 | - Largebins |                   |
|       | - Top Chunk |                 | - Top Chunk |                   |
|       +-------------+                 +-------------+                   |
+-------------------------------------------------------------------------+
```

### 2.1 아레나(Arena)와 뮤텍스 락 경합
- **아레나 구조**: Ptmalloc은 글로벌 락 병목을 피하기 위해 여러 개의 독립된 힙 영역인 **아레나(Arena)**를 둡니다.
  - `main_arena`: 프로세스의 전통적인 데이터 세그먼트(`brk`/`sbrk`)를 사용하는 메인 힙.
  - `non-main arena`: 보조 스레드를 위해 `mmap()`으로 할당된 64MB(64비트 기준) 단위의 서브 힙.
  - 아레나 최대 개수: `MALLOC_ARENA_MAX = 8 * CPU_CORES` (64비트 기준).
- **락 경합의 필연성**:
  - 스레드가 수백 개로 증가하거나, 특정 아레나에 할당 요청이 집중되면 여러 스레드가 동일한 `arena->mutex`를 획득하기 위해 대기합니다.
  - Ptmalloc에는 **스레드 로컬 캐시가 존재하지 않으므로**, 단 8바이트를 할당하거나 해제할 때도 반드시 아레나 뮤텍스 스핀락 및 커널 `futex` 시스템 콜을 거쳐야 합니다.
  - 이로 인해 멀티스레드 HFT 엔진이나 고동시성 웹 서버에서 CPU의 50~70%가 `__lll_lock_wait_private`에서 낭비되는 참사가 발생합니다.

### 2.2 청크 빈(Bins)과 Top Chunk 피닝(Pinning) 참사
- Ptmalloc은 해제된 메모리를 크기별로 관리하기 위해 다양한 빈을 사용합니다:
  - **Fastbins**: 16B~80B 소형 청크를 위한 단일 연결 리스트 (병합 없이 LIFO로 초고속 재할당).
  - **Smallbins**: 512B 미만 청크를 위한 이중 연결 리스트 (FIFO).
  - **Largebins**: 512B 이상 가변 크기 청크 (크기순 정렬).
  - **Unsorted bin**: 해제된 청크가 1차로 보관되는 임시 완충 지대.
  - **Top chunk (Wilderness chunk)**: 힙의 가장 끝에 위치한 미할당 영역.
- **Top Chunk 피닝 참사 (Memory Bloat)**:
  - 리눅스에서 `brk` 시스템 콜은 힙의 최상단 경계선(Program Break)만을 커널로 낮출 수 있습니다.
  - 만약 힙 중간에 100만 개의 객체를 할당했다가 999,999개를 해제하더라도, **힙의 가장 높은 주소에 단 1개의 활성 객체가 남아있다면(Top Chunk Pinning)**, 그 아래에 있는 기가바이트 단위의 빈 공간을 커널로 반환할 수 없습니다!
  - `madvise(MADV_DONTNEED)`를 통한 인라인 페이지 반환 로직이 빈약하여, 메모리를 해제해도 실제 물리 메모리(RSS)는 피크 상태를 영구히 유지합니다.

---

## 3. Jemalloc의 혁신적인 내부 아키텍처

Jason Evans가 2005년 FreeBSD 프로젝트를 위해 설계하고, 이후 Meta(Facebook)에서 대규모 인프라를 지탱하기 위해 발전시킨 **Jemalloc**은 현대 메모리 할당자의 정점입니다.

```
+-------------------------------------------------------------------------+
|                                Jemalloc                                 |
|                                                                         |
|  [Thread 1]                       [Thread 2]                            |
|       |                                |                                |
|  +----+---------+                 +----+---------+                      |
|  | tcache (L1)  |                 | tcache (L1)  |                      |
|  | [Lock-Free!] |                 | [Lock-Free!] |                      |
|  | Size Classes |                 | Size Classes |                      |
|  +----+---------+                 +----+---------+                      |
|       | (Batch Refill / Flush)         | (Batch Refill / Flush)         |
|       v                                v                                |
|  +-----------------------------------------------+                      |
|  | Shared Arena (L2) - Bins / Runs / Slabs       |                      |
|  | [Decay-based Purging -> madvise(DONTNEED)]    |                      |
|  +-----------------------------------------------+                      |
+-------------------------------------------------------------------------+
```

### 3.1 스레드 로컬 캐시 (`tcache`) - 완벽한 무락(Lock-Free) 할당
Jemalloc 성능의 핵심 비결은 **Thread-local Cache (`tcache`)**에 있습니다:
1. **Zero-Lock Fast Path**:
   - 각 스레드는 스레드 로컬 스토리지(TLS)에 자신만의 소형 크기 클래스 캐시를 가집니다.
   - 스레드가 메모리를 할당할 때, 자신의 `tcache`에서 해당 크기 클래스의 포인터를 팝(Pop)하기만 하면 됩니다.
   - **뮤텍스 락 획득 0건, 원자적(Atomic) CAS 연산조차 없는 순수 포인터 연산**으로 $O(1)$ 초저지연 할당이 완료됩니다.
   - 해제(`free`) 역시 자신의 `tcache`에 슬롯을 푸시(Push)하는 것으로 즉시 완료됩니다.
2. **배치 리필 & 배치 플러시 (Batch Refill & Flush)**:
   - `tcache`가 비었을 때(Miss): 공유 아레나의 락을 **단 1회만 잡고** 한 번에 여러 개(예: 16~32개)의 슬롯을 한꺼번에 가져옵니다.
   - `tcache`가 가득 찼을 때(Overflow): 아레나 락을 1회 잡고 절반의 슬롯을 공유 아레나로 일괄 반환합니다.
   - 이로써 락 획득 빈도를 수십 분의 일(1/32)로 줄여 경합을 사실상 0으로 만듭니다.

### 3.2 크기 클래스 (Size Classes)와 슬랩(Slab) 분할
Jemalloc은 내부 단편화(Internal Fragmentation)를 최소화하기 위해 수학적으로 정교하게 분할된 크기 클래스를 사용합니다:
- **Small Classes**: 8, 16, 32, 48, 64, 80, 96, 112, 128, 160, 192, 224, 256 ...
  - 2의 거듭제곱 사이에 4개의 선형 간격을 두는 쿼드-스페이싱(Quad-spaced) 구조를 채택하여 내부 단편화율을 항상 20% 이내로 엄격히 통제합니다.
- **Slab / Run 관리**:
  - 동일한 크기 클래스의 객체들은 전용 슬랩(4KB~수십KB 연속 페이지)에 배치됩니다.
  - 슬랩 내부의 빈 슬롯은 효율적인 비트맵(Bitmap)으로 관리되어 탐색 오버헤드가 없습니다.

### 3.3 지연 시간 기반 페이지 퍼징 (Decay-based Purging)
Ptmalloc과 달리 Jemalloc은 사용하지 않는 물리 메모리를 운영체제에 적극적으로 반환합니다:
1. **감쇠 시간 (`dirty_decay_ms`)**:
   - 객체들이 해제되어 슬랩 내의 모든 객체가 비워지면, 해당 4KB 페이지는 "더티(Dirty)" 상태가 됩니다.
   - Jemalloc은 백그라운드 스레드 또는 연산 틱에서 부드러운 감쇠 곡선(Sigmoid / Linear Decay)을 적용합니다.
2. **`madvise(MADV_DONTNEED)` 호출**:
   - 감쇠 시간이 만료된 더티 페이지에 대해 커널 시스템 콜 `madvise(addr, len, MADV_DONTNEED)`를 호출합니다.
   - 커널은 가상 주소 매핑은 유지하되, 해당 페이지 테이블에 할당되어 있던 물리 RAM 프레임을 즉시 회수합니다.
   - 프로세스의 RSS가 즉시 감소하므로, 대규모 트래픽 버스트 후에도 메모리가 낭비되거나 OOM에 걸리지 않습니다.

---

## 4. Ptmalloc vs Jemalloc 종합 비교

| 특성 | Glibc Ptmalloc | Jemalloc |
|---|---|---|
| **기본 스레드 캐시** | 없음 (전부 아레나 락 필요) | **tcache** (TLS 기반 완전 무락 $O(1)$) |
| **락 획득 빈도** | 모든 malloc/free마다 100% 획득 | tcache 미스/오버플로우 시에만 배치 획득 (< 5%) |
| **단편화 방어** | Fastbin/Smallbin 거친 분할, 병합 지연 | 쿼드-스페이싱 크기 클래스 & 슬랩 비트맵 |
| **커널 메모리 환원** | `brk` Top Chunk 축소 의존 (Top Chunk Pinning 취약) | **Decay-based Purge** (`madvise(MADV_DONTNEED)`) |
| **멀티코어 확장성** | 코어 수가 많을수록 심각한 락 경합 발생 | 수백 코어에서도 선형적(Linear) 확장성 유지 |
| **채택 사례** | Linux 표준 기본값 | **Redis, Rust, Meta Folly, FreeBSD, TiDB, Netty** |

---

## 5. 실무 시스템 튜닝 가이드

### 5.1 Redis와 Jemalloc
- Redis는 싱글 스레드 이벤트 루프로 동작하지만, 백그라운드 I/O 스레드 및 `BGSAVE` fork() 환경에서 극심한 메모리 관리를 요구합니다.
- Redis 창시자 Salvatore Sanfilippo는 Glibc Ptmalloc 환경에서 메모리 단편화율이 2.5~3.0(실제 데이터 대비 3배의 RSS 낭비)에 달하던 문제를 Jemalloc을 도입하여 1.1~1.2 수준으로 안정화했습니다.

### 5.2 환경 변수 튜닝 (MALLOC_CONF)
프로덕션 환경에서 Jemalloc을 사용할 때 다음 환경 변수를 통해 최적의 성능을 튜닝할 수 있습니다:
```bash
# tcache 활성화 및 dirty 페이지 5초 내 감쇠 반환
export MALLOC_CONF="tcache:true,dirty_decay_ms:5000,muzzy_decay_ms:5000"

# 초저지연 HFT 환경 (메모리 반환보다 극단의 지연시간 우선)
export MALLOC_CONF="tcache:true,dirty_decay_ms:-1" # 퍼징 비활성화로 락 최소화
```
