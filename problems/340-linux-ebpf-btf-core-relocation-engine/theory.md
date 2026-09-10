# 리눅스 커널 eBPF CO-RE (Compile Once – Run Everywhere) 및 BTF 심층 이론

## 1. 전통적 eBPF의 이식성 한계와 BCC 아키텍처의 비효율성

eBPF는 커널 내부에서 안전하게 실행되는 샌드박스 바이트코드 가상머신입니다. 그러나 eBPF 프로그램이 커널 자료구조를 읽기 위해 사용하는 C 포인터 역참조(`task->mm->rss`)는 컴파일 시점에 고정된 메모리 오프셋으로 변환됩니다.
- 리눅스 커널은 각 버전마다 자료구조가 끊임없이 변경되며, `CONFIG_PREEMPT`, `CONFIG_NUMA` 등 빌드 옵션에 따라 구조체 필드의 오프셋이 수십 바이트씩 밀려납니다.
- 1세대 툴체인인 **BCC(BPF Compiler Collection)**는 이 문제를 해결하기 위해 타깃 머신에 Clang, LLVM, 커널 헤더(`linux-headers-$(uname -r)`)를 직접 설치하고 실행 시점에 실시간 C 컴파일을 수행했습니다.
- **치명적 문제**: 수백 메가바이트의 컴파일러와 헤더 패키지로 인한 디스크/메모리 낭비, 컴파일 시 수 초 이상의 CPU 스파이크, 컨테이너 및 임베디드 환경에서의 배포 불가능성.

---

## 2. BPF Type Format (BTF)과 vmlinux.h

Linux 5.2부터 도입된 **BTF**는 ELF 포맷의 DWARF 디버그 정보를 극단적으로 압축한 커널 타입 메타데이터 시스템입니다:
- 수백 메가바이트에 달하는 DWARF 디버그 심볼을 단 1~2MB 크기의 바이너리 포맷으로 압축하여 커널 이미지(`/sys/kernel/btf/vmlinux`)에 기본 내장합니다.
- `bpftool btf dump file /sys/kernel/btf/vmlinux format c > vmlinux.h` 명령어를 통해 단 하나의 C 헤더 파일로 모든 커널 구조체 선언을 복원할 수 있습니다.
- 개발자는 더 이상 호스트 커널 헤더를 include할 필요 없이, `vmlinux.h` 하나만으로 모든 eBPF 프로그램을 컴파일할 수 있게 되었습니다.

---

## 3. CO-RE 재배치 메커니즘과 Clang 빌트인 함수

Clang 컴파일러는 eBPF 코드를 바이트코드로 변환할 때, 구조체 접근을 하드코딩하지 않고 재배치 레코드를 남깁니다:

### 3.1 BPF CO-RE 헬퍼 매크로
- `BPF_CORE_READ(dst, src, field1, field2)`: 다단계 포인터 탐색을 CO-RE 안전하게 읽기.
- `bpf_core_field_exists(field)`: 타깃 커널에 특정 필드가 존재하는지 컴파일러 빌트인 `__builtin_preserve_field_info()`를 통해 확인.
- `bpf_core_type_matches(type)`: 특정 커널 구조체 타입 호환성 검증.

### 3.2 ELF `.BTF.ext` 섹션과 `bpf_core_relo`
Clang은 생성된 ELF 바이너리의 `.BTF.ext` 섹션에 다음과 같은 재배치 엔트리를 저장합니다:
```c
struct bpf_core_relo {
    __u32 insn_off;      // 패치할 BPF 명령어 바이트 오프셋
    __u32 type_id;       // 소스 BTF 상의 타입 ID
    __u32 access_str_off;// 접근 경로 문자열 (예: "0:2:1")
    enum bpf_core_relo_kind kind; // 재배치 유형
};
```

---

## 4. Libbpf의 런타임 재배치 알고리즘

BPF 로더(Libbpf 또는 Go `cilium/ebpf`)가 타깃 호스트에서 프로그램을 로드할 때의 단계는 다음과 같습니다:

1. **타깃 BTF 적재**: 호스트 커널의 `/sys/kernel/btf/vmlinux`를 파싱하여 호스트 커널의 실제 타입 그래프를 메모리에 구성.
2. **타입 매칭 및 플레이버 해결 (Struct Flavor)**:
   - 드라이버나 커널 서브시스템이 버전별로 구조체를 다르게 정의했을 때, BPF 프로그램은 `struct task_struct___v1`과 `struct task_struct___v2`를 정의하여 조건부로 처리할 수 있습니다.
   - 로더는 `___` 접미사를 제거하고 호스트 커널의 실제 구조체와 일치하는 플레이버를 선택합니다.
3. **접근 경로 탐색 (Path Traversal)**:
   - 소스 BTF의 `access_str` 인덱스를 따라가며 각 레벨의 멤버 이름을 수집합니다.
   - 타깃 BTF에서 해당 멤버 이름을 검색하여 실제 타깃 커널의 바이트 오프셋을 계산합니다.
4. **인플레이스 바이트코드 패치 (In-place Bytecode Patching)**:
   - `BPF_LDX_MEM` / `BPF_STX_MEM` 명령어의 `off` 필드를 타깃 오프셋으로 갱신합니다.
   - `FIELD_EXISTS` 또는 `FIELD_BYTE_SIZE`의 경우 조건부 점프나 마스크에 사용되는 즉시값(`imm`)을 타깃 값으로 갱신합니다.
5. **커널 검증기(BPF Verifier) 제출**: 최종 패치된 바이트코드를 `bpf(BPF_PROG_LOAD)` 시스템 콜로 커널에 적재합니다.
