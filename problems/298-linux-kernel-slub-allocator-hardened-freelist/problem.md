# 리눅스 커널 SLUB 할당자 빠른 경로 및 하든드 프리리스트 보안 (Linux Kernel SLUB Allocator Fast Path & Hardened Freelist Security)

## 문제 설명

리눅스 커널의 **SLUB(Queued/Unqueued Slab Allocator - `mm/slub.c`)**는 커널 내부에서 작은 크기의 객체(Task Struct, Inode, dentry, sk_buff, kmalloc 등)를 고속으로 할당/해제하는 기본 메모리 할당자입니다.
기존 SLAB 할당자의 복잡한 큐 및 메타데이터 오버헤드를 대폭 줄이고, 멀티코어 환경에서 락 경합(Lock Contention)을 제거하기 위해 **CPU별 로컬 슬랩 캐시(`kmem_cache_cpu`) 기반 Fast Path**와 **노드별 부분 슬랩 리스트(`kmem_cache_node->partial`) 기반 Slow Path**로 구성되어 있습니다.

또한 커널 힙 익스플로잇(Heap Overflow, Use-After-Free, Fastbin Dup 등) 공격자가 해제된 객체 내부의 `freelist` 포인터를 변조하여 임의 메모리 쓰기(Arbitrary Write)를 수행하는 공격을 원천 방어하기 위해, **하든드 프리리스트(`CONFIG_SLAB_FREELIST_HARDENED`)** 포인터 난독화(XOR Obfuscation with Random Cookie & Pointer Address)를 도입했습니다.

본 문제에서는 리눅스 커널 `mm/slub.c`의 핵심 동작 메커니즘을 충실히 모델링한 커널 SLUB 메모리 할당자 시뮬레이터를 구현합니다.

---

## 동작 명세

### 1. 객체 크기 정렬 및 슬랩 용량 계산
- 입력 `obj_size`와 `align`에 따라 실제 할당 단위 크기 `actual_size`를 계산합니다:
  $$	ext{actual\_size} = \left\lfloor rac{	ext{obj\_size} + 	ext{align} - 1}{	ext{align}} ightfloor 	imes 	ext{align}$$
- 슬랩 1개당 담을 수 있는 총 객체 수:
  $$	ext{objs\_per\_slab} = \lfloor 	ext{slab\_size} / 	ext{actual\_size} floor$$

### 2. 하든드 프리리스트 포인터 난독화 (`CONFIG_SLAB_FREELIST_HARDENED`)
- 해제된 객체는 다음 가용 객체의 주소를 가리키는 `freelist` 포인터를 보관합니다.
- `hardened` 옵션이 활성화된 경우, 평문 주소 대신 다음과 같이 암호화하여 저장합니다:
  $$	ext{encoded\_ptr} = 	ext{next\_ptr} \oplus 	ext{ptr\_addr} \oplus 	ext{cookie}$$
  (단, `next_ptr`가 `None`인 경우 0으로 취급)
- 복호화(Dereference):
  $$	ext{decoded\_ptr} = 	ext{encoded\_ptr} \oplus 	ext{ptr\_addr} \oplus 	ext{cookie}$$
  (결과가 0이면 `None`)
- 복호화된 포인터가 유효한 슬랩 내부 객체 범위(`[base, base + slab_size)`) 및 정렬(`(ptr - base) % actual_size == 0`)을 만족하지 않으면, 즉시 `FREELIST_CORRUPTION_DETECTED` 오류를 발생시키고 오염을 감지합니다.

### 3. 할당 경로 (`ALLOC`)
1. **Fast Path (`kmem_cache_cpu`)**:
   - 현재 활성 `cpu_slab`이 존재하고 `freelist_head`가 비어있지 않으면 Fast Path를 탑니다.
   - `addr = slab.freelist_head`를 꺼내고, 메모리에 저장된 인코딩 포인터를 복호화하여 다음 `freelist_head`로 갱신합니다.
   - `slab.inuse += 1`, `fast_path_allocs += 1`.
2. **Slow Path (`__slab_alloc`)**:
   - `cpu_slab`이 없거나 `freelist_head`가 고갈된 경우:
     - `node_partial` 리스트에 가용 슬랩이 있다면 첫 번째 슬랩을 `cpu_slab`으로 승격시킵니다.
     - `node_partial`도 비어있다면 물리 페이지 할당자로부터 새로운 슬랩(`_new_slab`)을 할당받아 `cpu_slab`으로 설정합니다.
   - 새로운 슬랩의 첫 번째 프리 객체를 꺼내어 할당합니다.
   - `slow_path_allocs += 1`.

### 4. 해제 경로 (`FREE`)
1. **Fast Path Free**:
   - 해제하려는 객체가 현재 활성 `cpu_slab`에 속해 있다면:
     - 객체의 메모리에 현재 `freelist_head`를 인코딩하여 저장하고, `freelist_head`를 해당 객체 주소로 갱신합니다.
     - `slab.inuse -= 1`, `fast_path_frees += 1`.
2. **Slow Path Free**:
   - 해제하려는 객체가 다른 슬랩(원격 슬랩)에 속해 있다면:
     - 해당 슬랩의 프리리스트 맨 앞에 객체를 반환합니다.
     - `slab.inuse -= 1`, `slow_path_frees += 1`.
     - 만약 슬랩이 가득 찬 상태(`inuse == objs_per_slab`)에서 해제된 것이라면, `node_partial` 리스트에 등록합니다.
     - 만약 `inuse == 0` (슬랩 내 모든 객체가 반환됨)이고, `len(node_partial) >= min_partial`이면 슬랩을 파괴하고 페이지 할당자로 반환(`slab_reclaimed = True`, `slabs_freed += 1`)합니다.

### 5. 무결성 및 오류 검출
- **이중 해제(Double Free)**: 할당되지 않았거나 이미 해제된 객체 식별자에 대해 `FREE` 요청이 오면 `DOUBLE_FREE_OR_UNALLOCATED` 오류를 기록하고 카운터를 증가시킵니다.
- **프리리스트 변조(Corruption)**: `CORRUPT` 명령을 통해 해제된 객체 내부의 포인터가 변조되면, 다음 할당 시 복호화 검증 실패로 `FREELIST_CORRUPTION_DETECTED` 오류를 기록합니다.

---

## 입력 형식

JSON 형식으로 표준 입력에 전달됩니다.

```json
{
  "config": {
    "obj_size": 64,
    "align": 8,
    "slab_size": 256,
    "cookie": 1311768467294899696,
    "hardened": true,
    "min_partial": 1
  },
  "operations": [
    {"op": "ALLOC", "id": "p1"},
    {"op": "ALLOC", "id": "p2"},
    {"op": "FREE", "id": "p1"}
  ]
}
```

---

## 출력 형식

```json
{
  "events": [
    {"op": "ALLOC", "id": "p1", "addr": 1048576, "path": "slow_path", "slab_id": 0},
    {"op": "ALLOC", "id": "p2", "addr": 1048640, "path": "fast_path", "slab_id": 0},
    {"op": "FREE", "id": "p1", "addr": 1048576, "path": "fast_path", "slab_id": 0, "slab_reclaimed": false}
  ],
  "stats": {
    "slabs_allocated": 1,
    "slabs_freed": 0,
    "fast_path_allocs": 1,
    "slow_path_allocs": 1,
    "fast_path_frees": 1,
    "slow_path_frees": 0,
    "double_frees_detected": 0,
    "corruptions_detected": 0
  },
  "final_state": {
    "active_slab_id": 0,
    "active_slab_inuse": 1,
    "partial_slabs_count": 0,
    "total_live_slabs": 1
  }
}
```
