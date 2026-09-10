# 리눅스 커널 SLUB 할당자와 하든드 프리리스트 보안 아키텍처 (Linux Kernel SLUB Allocator & Hardened Freelist Architecture)

## 1. 개요: SLAB에서 SLUB으로의 진화

리눅스 커널 초기에는 Bonwick의 고전적인 SLAB 할당자(`mm/slab.c`)를 사용했습니다. SLAB은 빈번한 객체 생성/소멸 비용을 줄이기 위해 캐싱을 도입했으나 다음과 같은 한계를 지녔습니다:
1. 객체별 큐 및 메타데이터가 비대하여 상당한 메모리 풋프린트 낭비.
2. 대규모 다중 코어(SMP/NUMA) 시스템에서 전역 락 경합으로 인한 성능 병목.

커널 2.6.22부터 Christoph Lameter에 의해 도입된 **SLUB(`mm/slub.c`)**은 불필요한 메타데이터 큐를 제거하고 객체 자체의 메모리 공간에 단일 연결 리스트(Intrusive Free List)를 구성함으로써, 오버헤드를 극소화하고 멀티코어 확장성을 극대화하여 현대 리눅스 커널의 기본 할당자로 자리 잡았습니다.

---

## 2. SLUB의 2단계 계층 구조: Fast Path vs Slow Path

SLUB은 메모리 할당 요청 시 락 획득을 최소화하기 위해 CPU 로컬 캐시와 노드 공유 캐시로 분리됩니다:

```
[kmalloc Request]
       │
       ▼
[kmem_cache_cpu (Per-CPU Local)]
  ├─ freelist != NULL? ───► [Fast Path: Pop from CPU freelist (No Lock)]
  │
  └─ freelist == NULL  (Slow Path)
         │
         ▼
[kmem_cache_node (Per-NUMA Node)]
  ├─ partial list has slab? ───► [Acquire Node Lock -> Refill CPU slab]
  │
  └─ partial list empty ───────► [Buddy Page Allocator: alloc_pages()]
```

### 2.1 Fast Path (`kmem_cache_cpu`)
- 현재 CPU에 할당된 활성 슬랩(`page/slab`)의 `freelist` 헤드 포인터를 원자적으로 읽어 바로 객체를 반환합니다.
- 슬랩 전체에 락을 걸지 않으므로 나노초 단위의 초고속 할당이 가능합니다.

### 2.2 Slow Path (`__slab_alloc`)
- 활성 슬랩의 모든 객체가 소진되면 호출됩니다.
- 현재 슬랩을 '동결 해제(Unfreeze)'하여 가득 찬 상태(Full)로 남겨두고, `kmem_cache_node`의 부분 할당 슬랩 리스트(`partial`)에서 일부가 비어 있는 슬랩을 가져와 새로운 활성 슬랩으로 지정합니다.
- 부분 슬랩마저 없으면 버디 할당자(Buddy Allocator)로부터 물리 4KB 페이지(들)를 새로 할당받아 객체 슬랩을 분할 생성합니다.

---

## 3. 하든드 프리리스트(`CONFIG_SLAB_FREELIST_HARDENED`)의 보안 원리

리눅스 커널 힙 익스플로잇에서 가장 널리 악용되는 기법 중 하나는 **Use-After-Free(UAF)** 또는 **Heap Buffer Overflow**를 통해 해제된 객체 내부의 `freelist` 포인터를 덮어쓰는 공격입니다. 공격자가 `freelist`를 조작하여 커널 제어 구조체(`cred`, `pipe_buffer`, `task_struct`) 주소를 가리키게 만들면, 후속 `kmalloc` 시 해당 구조체가 할당되어 권한 상승(Root Privilege Escalation)으로 이어집니다.

이를 방어하기 위해 리눅스 커널은 **하든드 프리리스트** 기법을 적용했습니다:
$$	ext{encoded\_next} = 	ext{next} \oplus 	ext{ptr\_addr} \oplus 	ext{cookie}$$

### 3.1 암호학적 엔트로피와 방어 메커니즘
1. **ASLR + Random Cookie**: 부팅 시 생성되는 무작위 64비트 정수 `cookie`를 모르면 임의의 목표 주소로 유효한 인코딩 값을 생성할 수 없습니다.
2. **주소 의존성 (`ptr_addr`)**: 인코딩 값에 객체 자신의 주소(`ptr_addr`)가 포함되어 있으므로, 힙 메모리를 다른 위치로 복제(Heap Spraying)하더라도 오프셋 불일치로 인해 복호화 결과가 완전히 깨집니다.
3. **디코딩 무결성 검증**:
   복호화된 주소가 해당 슬랩의 경계 `[base, base + slab_size)` 내에 속하지 않거나, 객체 크기 정렬(`align`)을 만족하지 못하면 커널은 즉시 `BUG_ON` 또는 `FREELIST_CORRUPTION_DETECTED` 패닉을 일으켜 임의 쓰기 발생 직전에 프로세스를 격리합니다.
