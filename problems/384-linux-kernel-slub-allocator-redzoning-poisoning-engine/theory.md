# Theory: Linux Kernel SLUB Memory Allocator & Runtime Integrity Hardening (`mm/slub.c`)

## 1. 리눅스 슬랩 할당자 진화와 SLUB의 설계 철학

리눅스 커널의 동적 메모리 할당 계층은 페이지 프레임 단위(4KB/2MB)를 관리하는 **Buddy Allocator**(`mm/page_alloc.c`) 위에 구축됩니다. 그러나 커널 내부 자료구조(`struct task_struct`, `struct inode`, `struct dentry`, `struct sk_buff` 등)는 수십~수백 바이트 크기이며, 매 초 수만 번 이상 빈번하게 할당/해제됩니다.

- **SLAB (`mm/slab.c`)**: 본래 SunOS의 Bonwick 논문(1994)에 기반한 전통적 할당자입니다. 큐 구조와 컬러링(coloring), per-CPU/per-node 오브젝트 캐시를 갖추었으나 메타데이터 오버헤드가 크고 NUMA 확장에 한계가 있었습니다.
- **SLOB (`mm/slob.c`)**: 임베디드 소형 시스템용 K&R First-fit 단순 할당자 (Linux 6.4에서 공식 제거).
- **SLUB (`mm/slub.c`)**: Christoph Lameter가 설계한 차세대 비단편화 슬랩 할당자입니다. 슬랩 페이지(`struct slab` / `struct page`)의 메타데이터를 최소화하고 외부 큐 없이 객체 내부 인라인 포인터(Freelist Pointer)를 활용하여 캐시 친화적인 LIFO 프리리스트를 구현했습니다.

---

## 2. SLUB 디버그 및 런타임 보안 아키텍처

커널 부팅 옵션 `slub_debug` 또는 빌드 옵션(`CONFIG_SLUB_DEBUG`)을 활성화하면 객체 레이아웃에 다음과 같은 방어 계층이 주입됩니다:

### 2.1 레드존(Redzone Guard, `SLAB_RED_ZONE`)
- **목적**: 힙 버퍼 언더플로우(Underflow) 및 오버플로우(Overflow) 탐지.
- **원리**: 페이로드 앞뒤에 `redzone_size` 바이트만큼 매직 바이트(`0xbb`)를 기록합니다.
  - Left Redzone: `slot_addr ~ slot_addr + redzone_size - 1`
  - Right Redzone: `payload_addr + object_size ~ slot_addr + slot_size - 1`
- **검증**: `kfree()` 호출 시 또는 `check_slab()` 호출 시 해당 영역 바이트가 `0xbb`와 일치하지 않으면 즉각 경고(`SLUB_REDZONE_*_DETECTED`)를 출력합니다.

### 2.2 객체 포이즈닝(Object Poisoning, `SLAB_POISON`)
- **목적**: 해제된 객체에 대한 댕글링 포인터 쓰기(Use-After-Free) 탐지.
- **원리**: 객체가 `kfree()`로 해제되면 페이로드 전체를 `0x6b`(`POISON_FREE`)로 덮어씁니다.
- **검증**: 객체가 재할당(`kmalloc()`)될 때 페이로드에 `0x6b`가 아닌 바이트가 존재하는지 사전 스캔합니다. 비정상 바이트 발견 시 객체가 프리리스트에 머무는 동안 부정한 쓰기가 발생했음을 확인하고 `SLUB_POISON_CORRUPTED_BEFORE_ALLOC` 경고를 보고합니다.

### 2.3 프리리스트 포인터 하드닝(`CONFIG_SLAB_FREELIST_HARDENED`)
- **배경**: 해제된 객체의 첫 8바이트에 다음 가용 객체의 주소(`next`)를 저장합니다. 공격자가 인접 버퍼 오버플로우로 이 포인터를 조작하면, 다음 할당 시 임의의 커널 주소를 획득(Arbitrary Write)할 수 있는 Freelist Hijacking이 발생합니다.
- **암호화 공식**:
  $$\text{encoded\_ptr} = \text{target\_ptr} \oplus \text{cookie} \oplus \text{swab64}(\text{ptr\_addr})$$
  - `cookie`: 슬랩 캐시(`struct kmem_cache`) 생성 시 per-cache 무작위 생성되는 64비트 엔트로피 값.
  - `swab64`: 64비트 바이트 순서 반전(Byte Swapping). 주소 상위 비트와 하위 비트의 편향을 파괴합니다.
- **디코딩 및 검증**:
  $$\text{target\_ptr} = \text{encoded\_ptr} \oplus \text{cookie} \oplus \text{swab64}(\text{ptr\_addr})$$
  복호화된 포인터가 슬랩 경계를 벗어나거나 유효한 슬롯 주소와 일치하지 않으면 즉각 `BUG()` 또는 `panic()`을 발생시킵니다.

### 2.4 프리리스트 무작위화(`CONFIG_SLAB_FREELIST_RANDOM`)
- 초기 슬랩 페이지 생성 시 0부터 $N-1$까지 순차적 프리리스트 대신, PRNG 기반 Fisher-Yates 셔플링을 적용합니다.
- 공격자가 힙 레이아웃의 선형적 연속성을 예측할 수 없도록 만들어 힙 익스플로잇(Heap Spraying / ROP Chain injection) 난이도를 극대화합니다.
