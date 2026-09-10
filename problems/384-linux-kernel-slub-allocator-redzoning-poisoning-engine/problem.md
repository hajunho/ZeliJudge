# Problem #384: Linux Kernel SLUB Allocator Redzoning, Object Poisoning & Freelist Hardening Engine (`mm/slub.c`)

## 문제 설명

리눅스 커널 메모리 관리 서브시스템에서 **SLUB(Unfragmented Slab Allocator, `mm/slub.c`)**은 디바이스 드라이버, 파일시스템, 네트워킹 스택 등 전 커널 계층에서 수 바이트부터 수 킬로바이트 단위의 고빈도 소형 동적 객체 할당(`kmalloc`, `kmem_cache_alloc`)을 전담하는 핵심 메모리 할당자입니다.

커널 메모리 손상 버그(Out-of-Bounds OOB 쓰기, Use-After-Free UAF, Double-Free, 프리리스트 하이재킹 등)는 특권 승격(Privilege Escalation) 및 시스템 크래시(Kernel Panic)의 주원인이 됩니다. 리눅스 커널은 이를 방어하고 런타임에 즉각 진단하기 위해 강력한 디버깅 및 보안 메커니즘을 제공합니다:

1. **레드존 가드(Redzone, `SLAB_RED_ZONE` / `0xbb`)**:
   - 객체 페이로드의 시작 전(Left Redzone)과 끝 후(Right Redzone)에 고정된 크기(`redzone_size`)의 매직 바이트(`0xbb`) 패딩을 배치합니다.
   - 객체 해제(`kfree`) 시점 또는 슬랩 검증(`VALIDATE_SLAB`) 시 레드존 바이트가 손상되었을 경우 언더플로우(`SLUB_REDZONE_UNDERFLOW_DETECTED`) 또는 오버플로우(`SLUB_REDZONE_OVERFLOW_DETECTED`) 경고를 발생시킵니다.
2. **객체 포이즈닝(Object Poisoning, `SLAB_POISON` / `0x6b`)**:
   - 객체가 해제되어 프리리스트에 반환되면 페이로드 전체를 포이즌 패턴(`0x6b` / `POISON_FREE`)으로 채웁니다.
   - 이후 댕글링 포인터(Dangling Pointer)에 의한 Use-After-Free(UAF) 쓰기가 발생하면, 재할당(`kmalloc`) 시점 또는 슬랩 검증 시 `SLUB_POISON_CORRUPTED_BEFORE_ALLOC`을 포착합니다.
3. **더블 프리(Double-Free) 방어**:
   - 이미 `FREE` 상태인 객체에 대해 `kfree`가 재호출될 경우 즉각적인 `SLUB_DOUBLE_FREE_DETECTED` 패닉 이벤트를 발생시킵니다.
4. **프리리스트 하드닝(Freelist Hardening, `CONFIG_SLAB_FREELIST_HARDENED`)**:
   - 단일 연결 리스트의 `next` 포인터를 평문으로 저장할 경우 힙 오버플로우 공격에 의해 임의 주소 쓰기 프리미티브(Freelist Hijacking)로 악용될 수 있습니다.
   - 이를 방어하기 위해 per-cache 난수 쿠키(`cookie`)와 현재 객체 페이로드 주소의 바이트 스왑 값(`swab64(ptr_addr)`)을 사용해 XOR 암호화합니다:
     $$\text{encoded\_next} = \text{target\_addr} \oplus \text{cookie} \oplus \text{swab64}(\text{curr\_addr})$$
   - `kmalloc` 시 복호화된 타깃 주소가 슬랩 내 유효 정렬 객체 주소가 아닐 경우 `SLUB_FREELIST_CORRUPTED` 패닉을 발생시킵니다.
5. **프리리스트 셔플링(Freelist Randomization, `CONFIG_SLAB_FREELIST_RANDOM`)**:
   - 슬랩 초기화 시 연속적인 인덱스 순서 대신 결정론적 Fisher-Yates PRNG 알고리즘으로 프리리스트 순서를 무작위화하여 힙 스프레잉(Heap Spraying) 공격을 원천 교란합니다.

당신은 리눅스 커널의 SLUB 디버그 및 보안 서브시스템 엔진을 정밀 시뮬레이션하는 프로그램을 작성해야 합니다.

```
+----------------------------------------------------------------------------------------------------+
|                                    SLUB Slot Layout (in DRAM)                                      |
+------------------------------------+--------------------------------+------------------------------+
|   Left Redzone (redzone_size B)    |   Object Payload (object_size) | Right Redzone (redzone_size) |
|           [ 0xbb 0xbb ... ]        |     [ Data or Poison 0x6b ]    |       [ 0xbb 0xbb ... ]      |
+------------------------------------+--------------------------------+------------------------------+
  ^                                    ^                                ^
  slot_addr                            payload_addr (User Address)      payload_addr + object_size
```

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다:

```json
{
  "config": {
    "slab_size": 1024,
    "object_size": 64,
    "redzone_size": 16,
    "poison_byte": 107,
    "redzone_byte": 187,
    "freelist_hardened": true,
    "freelist_random": false,
    "cookie": 16045690984833335998,
    "base_address": 18446603336221196288,
    "random_seed": 42
  },
  "commands": [
    { "op": "KMALLOC", "obj_id": "obj1", "caller_pc": "0xffffffff81100010" },
    { "op": "WRITE", "obj_id": "obj1", "offset": 64, "data_hex": "ffffffff" },
    { "op": "KFREE", "obj_id": "obj1", "caller_pc": "0xffffffff81100020" },
    { "op": "VALIDATE_SLAB" }
  ]
}
```

- `config`:
  - `slab_size`: 전체 슬랩 페이지 메모리 크기 (기본값: 1024, 단위: 바이트)
  - `object_size`: 객체 페이로드 크기 (기본값: 64 바이트)
  - `redzone_size`: 좌/우 레드존 패딩 크기 (기본값: 16 바이트)
  - `freelist_hardened`: 프리리스트 포인터 난수 XOR 암호화 여부 (기본값: true)
  - `freelist_random`: 프리리스트 셔플링 여부 (기본값: false)
  - `cookie`: 64비트 무작위 정수 쿠키
  - `base_address`: 가상 메모리 기저 주소 (기본값: 0xffff888000000000)
- `commands`:
  - `KMALLOC {obj_id, caller_pc}`: 프리리스트에서 객체 할당.
  - `KFREE {obj_id, caller_pc}`: 객체 레드존 무결성 검증 후 포이즈닝 및 프리리스트 반환.
  - `WRITE {obj_id, offset, data_hex}`: 객체 페이로드 기준 오프셋(`offset < 0`: Left RZ, `0 <= offset < size`: Payload, `offset >= size`: Right RZ)에 16진수 바이트 기록.
  - `CORRUPT_FREELIST_RAW {slot_index, raw_value}`: 프리리스트 메타데이터 원시 값 강제 덮어쓰기 (공격 시뮬레이션).
  - `VALIDATE_SLAB {}`: 슬랩 내 모든 슬롯의 레드존 및 포이즌 상태 일괄 무결성 검사.

---

## 출력 형식

표준 출력(stdout)으로 공백 없이 컴팩트한 단일 JSON 객체를 출력합니다:

```json
{
  "total_slots": 10,
  "allocated_count": 0,
  "free_count": 10,
  "corruptions_detected": 1,
  "events": [ ... ]
}
```

- `total_slots`: 슬랩 내 수용 가능한 총 슬롯 수 (`slab_size // slot_size`)
- `allocated_count`: 현재 `ALLOCATED` 상태인 객체 수
- `free_count`: 현재 `FREE` 상태인 객체 수
- `corruptions_detected`: 감지된 총 오염/경고/패닉 이벤트 수
- `events`: 명령어 실행 결과 이벤트 배열
