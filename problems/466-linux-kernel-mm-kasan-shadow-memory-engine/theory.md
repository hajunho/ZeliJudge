# 리눅스 커널 KASAN(Kernel Address Sanitizer) 섀도 메모리 아키텍처 심층 분석

## 1. 커널 메모리 오염 취약점과 KASAN의 탄생

전통적인 운영체제 커널 디버깅 도구들은 메모리 커럽션을 실시간으로 포착하는 데 명확한 한계를 지니고 있었습니다:
- **`SLAB_DEBUG` / `SLUB_DEBUG`**: 슬랩 프리 리스트 무결성을 검사하거나 객체 앞뒤에 매직 넘버(Poison Cookie)를 기록합니다. 그러나 오염이 발생하는 즉시 감지하는 것이 아니라, 다음 번 `kfree()`나 메모리 할당 시점에 검사하므로 버그의 근원지(Patient Zero)를 놓칩니다.
- **Page Guard / MMU Protection**: 페이지 테이블의 Present 비트를 0으로 만들어 비인가 접근 시 Page Fault를 유발하지만, 4KB 페이지 단위로만 동작하므로 슬랩 내 미세한 오프바이원 버퍼 오버플로우를 감지할 수 없습니다.

구글과 리눅스 커널 커뮤니티가 개발한 **KASAN(Generic KASAN)**은 컴파일러(GCC/Clang)와 커널 런타임의 협업을 통해 **바이트 단위(Byte-granularity)**의 접근 검사를 O(1) 시간에 수행합니다.

---

## 2. 1:8 직접 매핑 섀도 메모리(Shadow Memory) 아키텍처

Generic KASAN의 핵심은 8바이트의 물리/가상 메모리 상태를 1바이트의 섀도 메모리로 인코딩하는 1:8 스케일링입니다.

### 2.1 섀도 주소 변환 수식
x86-64 아키텍처에서 커널 가상 주소는 `0xffff800000000000` 이상에 위치합니다. KASAN은 거대한 연속 가상 메모리 영역을 섀도 메모리로 예약합니다:
$$\text{shadow\_addr} = (\text{kernel\_addr} \gg 3) + \text{KASAN\_SHADOW\_OFFSET}$$

x86-64의 `KASAN_SHADOW_OFFSET`은 보통 `0xdffffc0000000000`으로 설정됩니다. 이 상수를 더함으로써 임의의 유효한 커널 주소 $A$에 대해 $A \gg 3$ 연산을 취한 값이 정확히 섀도 메모리 예약 범위 내의 가상 주소로 사상됩니다.

### 2.2 인라인 인스트루멘테이션 (Inline vs Outline)
`-fsanitize=kernel-address` 플래그로 컴파일할 때:
- **Outline 모드**: 모든 메모리 접근 직전에 `__asan_loadN(addr)` 또는 `__asan_storeN(addr)` 함수를 호출합니다. 바이너리 크기 증가는 적으나 함수 호출 오버헤드가 발생합니다.
- **Inline 모드**: 컴파일러가 검증 어셈블리 명령어를 직접 인라인으로 삽입합니다:
  ```asm
  movq %rax, %rcx
  shrq $3, %rcx
  movb 0xdffffc0000000000(%rcx), %cl
  testb %cl, %cl
  jnz .Lslow_path_or_bug
  movq (%rax), %rbx     # 실제 메모리 역참조
  ```
  `testb %cl, %cl`을 통해 섀도 값이 `0x00`이면 단 3~4 클럭 사이클 만에 정상 경로를 통과하므로, 프로덕션 성능 저하를 2배 이내로 억제합니다.

---

## 3. 부분 청크(Partial Granule)와 레드존 포이즈닝 원리

슬랩 객체 크기는 8의 배수로 떨어지지 않는 경우가 많습니다(예: 27바이트 구조체).
8바이트 단위 섀도 메모리에서 27바이트 객체를 어떻게 1바이트 정밀도로 감시할 수 있을까요?

### 3.1 양수 섀도 값 ($1 \le k \le 7$)의 마법
- $27 = 8 \times 3 + 3$
- 처음 3개의 8바이트 청크(0~23바이트)는 완전 유효하므로 섀도 값 `0x00`이 기록됩니다.
- 4번째 8바이트 청크(24~31바이트)에는 유효 바이트가 3개(24, 25, 26)만 존재합니다.
- KASAN은 이 섀도 바이트에 **`0x03`**을 기록합니다!
- CPU가 27번째 바이트(인덱스 27)를 1바이트 읽으려 하면:
  $$\text{offset} = 27 \& 7 = 3$$
  섀도 값은 `3`입니다. 조건식 $\text{offset} \ge \text{shadow\_val}$ ($3 \ge 3$)이 참이 되므로, 컴파일러 검사 루틴은 즉시 버그 경로로 분기하여 `SLAB_OUT_OF_BOUNDS`를 발생시킵니다!

---

## 4. 커널 보안 버그 탐지 메커니즘 비교

| 버그 유형 | 발생 원인 | KASAN 섀도 값 | 탐지 시점 |
|---|---|---|---|
| **SLAB_OUT_OF_BOUNDS** | 할당된 크기를 초과하여 인접 메모리 침범 (Buffer Overflow) | `0xFB` 또는 $1 \le k \le 7$ 범위 초과 | 불법 메모리 역참조 즉시 |
| **USE_AFTER_FREE** | `kfree()` 후 댕글링 포인터를 통한 역참조 | `0xFC` (`KASAN_SLAB_FREE`) | 해제된 주소 접근 즉시 |
| **DOUBLE_FREE** | 이미 해제된 슬랩 객체에 대해 다시 `kfree()` 호출 | 객체 메타데이터 `freed == True` | 두 번째 `kfree()` 호출 즉시 |
| **PAGE_ALLOC_OUT_OF_BOUNDS**| 버디 할당자 페이지 경계 초과 접근 | `0xFA` (`KASAN_PAGE_REDZONE`) | 경계 초과 접근 즉시 |

KASAN은 커널 퍼징 도구인 **Syzkaller**와 결합하여 지난 수년간 수천 개의 치명적인 리눅스 커널 제로데이 취약점을 사전에 발굴하고 격리하는 데 결정적인 역할을 수행했습니다.
