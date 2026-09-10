# Linux Kernel KASAN (Kernel Address Sanitizer) 아키텍처 및 섀도우 메모리 격리 큐 심층 분석

## 1. 개요 및 설계 철학

C 언어로 작성된 리눅스 커널은 정적 타입 안정성과 메모리 안전성을 보장하지 못하므로, 버퍼 오버플로우(Buffer Overflow/Out-of-Bounds, OOB), 해제 후 사용(Use-After-Free, UAF), 이중 해제(Double-Free)와 같은 메모리 커럽션 버그가 시스템 충돌과 임의 코드 실행(Arbitrary Code Execution, 권한 상승) 취약점의 주된 원인이 됩니다.

**KASAN(Kernel Address Sanitizer)**은 안드레이 코노발로프(Andrey Konovalov), 드미트리 비유코프(Dmitry Vyukov) 등 구글 Syzkaller 및 커널 보안 팀에 의해 리눅스 커널에 도입된 동적 메모리 오류 탐지 프레임워크입니다(`mm/kasan/`). KASAN은 크게 세 가지 모드로 나뉩니다:
1. **Generic KASAN**: 섀도우 메모리 1:8 직접 바이트 매핑을 사용하여 OOB, UAF를 바이트 단위로 엄격히 탐지 (본 구현 모델).
2. **Software Tag-Based KASAN**: 포인터의 상위 바이트(AArch64 TBI: Top-Byte-Ignore)에 8비트 태그를 부여하고 섀도우 메모리 1:16 매핑과 비교하여 OOB, UAF 탐지.
3. **Hardware Tag-Based KASAN**: ARMv8.5-A MTE(Memory Tagging Extension) 하드웨어 명령어를 활용하여 최소한의 오버헤드로 실운영 환경에서 커널 보호.

본 엔진이 모델링하는 **Generic KASAN**은 x86_64를 비롯한 주류 아키텍처에서 커널 개발 및 Syzkaller 퍼징 단계의 사실상 표준(de-facto standard)입니다.

---

## 2. 섀도우 메모리 (Shadow Memory) 1:8 직접 매핑 수학

### 2.1 매핑 수식
Generic KASAN은 매 8바이트 메모리 영역마다 1바이트의 섀도우 메모리를 할당합니다:
$$\text{Shadow Addr} = (\text{Kernel Addr} \gg 3) + \text{KASAN_SHADOW_OFFSET}$$

x86_64의 경우 `KASAN_SHADOW_OFFSET`은 통상 `0xdffffc0000000000`으로 고정되며, 이는 컴파일러 계측 단계에서 단 2~3개의 어셈블리 명령어(Shift, Add, Move)로 변환됩니다:

```assembly
movq    %rdi, %rax
shrq    $3, %rax
movabsq $0xdffffc0000000000, %rcx
addq    %rcx, %rax
cmpb    $0, (%rax)
jne     .Lslow_path_kasan_report
```

### 2.2 섀도우 바이트 인코딩 규칙
1바이트의 섀도우 메모리는 대응되는 8바이트의 메모리 상태를 다음과 같이 표현합니다:
- **`0x00`**: 8바이트 전체가 유효하게 접근 가능 (Fully Addressable).
- **`1` ~ `7` ($k$)**: 시작부터 $k$ 바이트는 정상 접근 가능, 나머지 $(8-k)$ 바이트는 접근 불가 (Partial Chunk Redzone).
- **`0xFC` (`KASAN_KMALLOC_REDZONE`)**: 할당된 객체와 인접 객체 사이를 격리하기 위한 슬랩 레드존 패딩 바이트.
- **`0xFB` (`KASAN_KMALLOC_FREE`)**: `kfree()`에 의해 해제되어 격리 큐(Quarantine)에 수납된 상태.
- **`0xFF` (`KASAN_SHADOW_UNMAPPED`)**: 할당되지 않았거나 슬랩 버디 시스템으로 완전히 환원된 미매핑 상태.

```
커널 메모리 청크 [b0, b1, b2, b3, b4, b5, b6, b7]
섀도우 바이트 값: 0x05
접근 가능 바이트:  O   O   O   O   O   X   X   X
오프셋 index:    0   1   2   3   4   5   6   7
```

만약 프로그램이 $b$ 바이트에 접근할 때 오프셋 $o = b \pmod 8$이 섀도우 바이트 $s$ 이상이면($o \ge s$), 즉시 컴파일러 인라인 체크가 실패하고 슬랩 경계 초과(`SLAB_OUT_OF_BOUNDS`) 커널 패닉 리포트가 트리거됩니다.

---

## 3. 격리 큐 (Quarantine Queue) 메커니즘

### 3.1 UAF 탐지의 딜레마
전통적인 슬랩(SLUB) 할당기는 고성능 캐싱을 위해 직전에 해제된 객체를 다음 할당 요청 시 LIFO(Last-In-First-Out)로 즉시 재할당합니다:
1. 스레드 A가 객체 $P$를 `kfree(P)` 함.
2. 스레드 B가 즉시 `kmalloc()`을 호출하여 동일한 주소 $P$를 재할당받음.
3. 스레드 A가 여전히 가지고 있던 댕글링 포인터 $P$를 역참조(UAF)하여 메모리를 변조함.
4. 이 경우 $P$는 유효한 주소이므로 일반적인 섀도우 메모리 검사로는 UAF를 탐지하지 못하고 데이터 손상(silent corruption)이 발생합니다.

### 3.2 KASAN Quarantine 링 버퍼
이를 방지하기 위해 KASAN은 해제된 객체를 즉시 SLUB 프리리스트로 반환하지 않고 **Quarantine 링 버퍼(`mm/kasan/quarantine.c`)**에 임시 격리합니다:
1. `kfree(P)` 호출 시 객체 $P$의 페이로드와 레드존 전체를 `0xFB` (`KASAN_KMALLOC_FREE`)로 포이즈닝.
2. 객체 $P$를 전역 격리 큐(`quarantine_queue`)에 인큐.
3. 스레드 A가 댕글링 포인터 $P$에 접근하면 섀도우 값이 `0xFB`이므로 즉각적인 `USE_AFTER_FREE` 버그 리포트 생성.
4. 격리 큐의 총 객체 수 또는 메모리 크기가 임계치(`quarantine_capacity`)를 초과하면, 가장 오래된 객체를 디큐(Purge)하여 실제 SLUB 프리리스트로 반환하고 섀도우를 `0xFF`로 변경.

---

## 4. 커널 구현 아키텍처 및 복잡도 분석

| 연산 단계 | 시간 복잡도 | 공간 복잡도 | 설명 |
| :--- | :--- | :--- | :--- |
| **KMALLOC** | $O(N/8)$ | $O(N/8)$ | 8바이트 정렬 후 유효 청크(0), 부분 청크(rem), 레드존(0xFC) 섀도우 기록 |
| **KFREE** | $O(N/8)$ | $O(1)$ | 전체 청크 0xFB 포이즈닝 및 격리 큐 인큐, 큐 초과 시 FIFO 방출 |
| **MEMORY_ACCESS** | $O(S)$ | $O(1)$ | $S$바이트 범위에 대해 섀도우 인덱스 및 비트마스크 검증 |

본 엔진을 통해 리눅스 커널의 가장 정교한 디버깅 및 보안 인프라인 KASAN과 SLUB 격리 큐의 동작 원리를 온전히 체득할 수 있습니다.
