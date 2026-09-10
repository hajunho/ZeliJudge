# 리눅스 커널 BPF CO-RE(Compile Once – Run Everywhere) 재배치 및 필드 오프셋 패칭 엔진

## 1. 개요 및 배경

과거 BCC(BPF Compiler Collection) 기반 eBPF 프로그램은 배포 대상 서버마다 로컬 커널 헤더(`linux-headers-$(uname -r)`)와 수백 메가바이트의 Clang/LLVM 컴파일러 툴체인을 직접 설치하고 메모리 상에서 컴파일을 수행해야 했습니다.
이로 인해 빌드 시점의 CPU/메모리 스파이크, 헤더가 제거된 경량 컨테이너 환경에서의 실행 불가 등 심각한 운영적 병목이 발생했습니다.

이를 근본적으로 해결하기 위해 리눅스 5.2 커널에 도입된 표준 아키텍처가 바로 **BPF CO-RE(Compile Once – Run Everywhere, `kernel/bpf/btf.c`, `tools/lib/bpf/relo_core.c`)**입니다.
CO-RE의 기본 철학:
- 개발자의 빌드 머신에서 eBPF C 코드를 단 한 번만 ELF 바이너리로 컴파일합니다. 이때 컴파일러는 컴파일 시점의 커널 구조체 정보인 **BTF(BPF Type Format)**와 함께 **재배치 레코드(Relocation Records)**를 `.BTF.ext` 섹션에 보존합니다.
- 대상 프로덕션 호스트에서 프로그램을 로드할 때, 사용자 공간 라이브러리(`libbpf`)는 호스트 커널의 실제 메모리 레이아웃(`/sys/kernel/btf/vmlinux`)을 읽어옵니다.
- `libbpf`의 CO-RE 재배치 엔진(`relo_core.c`)은 컴파일 시점 타입과 호스트 커널 타입을 이름과 접근 경로(`access_str`)를 통해 매칭하고, eBPF 명령어의 즉시 오프셋(`off`)이나 즉칫값(`imm`)을 **호스트 커널의 실제 물리적 오프셋으로 동적 재기록(Patching)**한 후 `bpf()` 시스템 콜로 커널 검증기(Verifier)에 전달합니다.

CO-RE의 6대 핵심 재배치 유형 (`enum bpf_core_relo_kind`):
1. **`FIELD_BYTE_OFFSET`**: 구조체 멤버의 바이트 오프셋 재배치 (예: `task_struct->pid`가 버전별로 2184에서 2248로 이동 시 `LDX` 오프셋 자동 패칭).
2. **`FIELD_BYTE_SIZE`**: 구조체 멤버 크기 재배치 (예: 32비트 int에서 64비트 ulong으로 확장 시 즉칫값 갱신).
3. **`FIELD_EXISTS`**: 호스트 커널에 해당 멤버가 존재하는지 판정 (존재 시 1, 미존재 시 0 반환하여 조건 분기 최적화 및 Dead Code 제거).
4. **`TYPE_EXISTS`**: 특정 구조체/타입이 호스트 커널 BTF에 정의되어 있는지 확인 (1 또는 0).
5. **`TYPE_SIZE`**: `sizeof(struct target)` 크기를 호스트 커널 기준으로 동적 도출.
6. **`ENUMVAL_VALUE`**: 커널 버전마다 열거형(Enum) 상숫값이 달라져도 실제 호스트 값으로 치환.

본 과제에서는 `tools/lib/bpf/relo_core.c`의 CO-RE 재배치 알고리즘을 모사하는 고신뢰성 eBPF 바이트코드 패칭 엔진을 구현합니다.

---

## 2. 아키텍처 다이어그램

```
+-----------------------------------------------------------------------------------------+
|                    Build Machine (Compile Time: Clang -target bpf)                      |
|   vmlinux.h (Build Kernel BTF)                                                          |
|   struct task_struct {                                                                  |
|       int state;      // offset: 0                                                      |
|       void *stack;    // offset: 8                                                      |
|       int pid;        // offset: 2184  <-- Compile-time offset                          |
|   };                                                                                    |
|   eBPF Bytecode:  r0 = *(u32 *)(r1 + 2184)   (LDX insn off=2184, relo: "0:2")           |
+-----------------------------------------------------------------------------------------+
                                         |
                                         | Single Generic ELF Object (.o)
                                         v
+-----------------------------------------------------------------------------------------+
|                  Target Production Server (Runtime: libbpf CO-RE Engine)                |
|                                                                                         |
|   Host Kernel BTF (/sys/kernel/btf/vmlinux)                                             |
|   struct task_struct {                                                                  |
|       int state;      // offset: 0                                                      |
|       int flags;      // offset: 4  <-- New field inserted in this kernel!              |
|       void *stack;    // offset: 8                                                      |
|       int pid;        // offset: 2248 <-- Actual Runtime offset                         |
|   };                                                                                    |
|                                                                                         |
|   [ CO-RE Path Matching (access_str: "2" -> member "pid") ]                             |
|   Match "pid" in Target BTF => Resolved Target Offset = 2248                            |
|                                                                                         |
|   [ Instruction Patching ]                                                              |
|   Old Instruction: r0 = *(u32 *)(r1 + 2184)                                             |
|   ===> Patched:    r0 = *(u32 *)(r1 + 2248)                                             |
+-----------------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------------+
|                     Linux Kernel BPF Verifier & JIT Compiler                            |
|   Loads and runs flawlessly without recompiling Clang on production host!               |
+-----------------------------------------------------------------------------------------+
```

---

## 3. 핵심 규칙 및 상태 전이 사양

### 3.1 BTF 타입 정의
- 타입은 구조체(`members`), 크기(`size`), 열거형(`values`)으로 구성됨.
- `members`: `[{"name": "...", "type": "...", "offset": byte_offset, "size": byte_size}]`.

### 3.2 접근 경로(`access_str`) 해석
- 콜론(`:`)으로 구분된 0-기반 인덱스 목록.
- 예: `"0:1"`은 `root_type`의 0번째 멤버 $ightarrow$ 해당 멤버 타입의 1번째 멤버를 순차 역참조.
- 컴파일 타임 BTF에서 멤버 이름들의 경로(`path_names`)를 도출한 뒤, 타깃 BTF에서 동일한 이름들을 추적하여 최종 오프셋과 크기를 연산.

### 3.3 재배치 유형별 패칭 규칙
1. `FIELD_BYTE_OFFSET`:
   - 타깃 BTF에서 멤버가 발견되면 명령어의 `off` 필드를 타깃 누적 오프셋으로 재기록.
   - 미발견 시 `status: "FIELD_NOT_FOUND"`.
2. `FIELD_BYTE_SIZE`:
   - 타깃 BTF 멤버 크기를 명령어의 `imm` 필드에 기록.
3. `FIELD_EXISTS`:
   - 타깃 BTF에서 해당 멤버가 존재하면 `imm = 1`, 미존재 시 `imm = 0`.
4. `TYPE_EXISTS`:
   - 타깃 BTF에 `type_name`이 정의되어 있으면 `imm = 1`, 미존재 시 `imm = 0`.
5. `TYPE_SIZE`:
   - 타깃 BTF의 `size`를 `imm`에 기록.
6. `ENUMVAL_VALUE`:
   - 타깃 열거형의 `val_name` 상숫값을 `imm`에 기록.

---

## 4. 입출력 규격

### 입력 JSON 구조
```json
{
  "config": {},
  "operations": [
    {"type": "LOAD_LOCAL_BTF", "types": {
      "task_struct": {
        "size": 4096,
        "members": [
          {"name": "state", "type": "int", "offset": 0, "size": 4},
          {"name": "pid", "type": "int", "offset": 2184, "size": 4}
        ]
      }
    }},
    {"type": "LOAD_TARGET_BTF", "types": {
      "task_struct": {
        "size": 4160,
        "members": [
          {"name": "state", "type": "int", "offset": 0, "size": 4},
          {"name": "flags", "type": "int", "offset": 4, "size": 4},
          {"name": "pid", "type": "int", "offset": 2248, "size": 4}
        ]
      }
    }},
    {"type": "LOAD_PROGRAM", "instructions": [
      {"insn_idx": 0, "op": "LDX", "dst": "r0", "src": "r1", "off": 2184}
    ], "relocations": [
      {"insn_idx": 0, "kind": "FIELD_BYTE_OFFSET", "type_name": "task_struct", "access_str": "1"}
    ]},
    {"type": "RUN_RELOCATIONS"}
  ]
}
```

### 출력 JSON 구조
```json
{
  "operation_results": [
    {
      "op_index": 0,
      "type": "LOAD_LOCAL_BTF",
      "count": 1,
      "status": "LOADED"
    },
    {
      "op_index": 1,
      "type": "LOAD_TARGET_BTF",
      "count": 1,
      "status": "LOADED"
    },
    {
      "op_index": 2,
      "type": "LOAD_PROGRAM",
      "instructions_count": 1,
      "relocations_count": 1,
      "status": "LOADED"
    },
    {
      "op_index": 3,
      "type": "RUN_RELOCATIONS",
      "relocations": [
        {
          "insn_idx": 0,
          "kind": "FIELD_BYTE_OFFSET",
          "status": "SUCCESS",
          "old_val": 2184,
          "new_val": 2248
        }
      ],
      "patched_instructions": [
        {
          "insn_idx": 0,
          "op": "LDX",
          "dst": "r0",
          "src": "r1",
          "off": 2248
        }
      ]
    }
  ],
  "final_instructions": [
    {
      "insn_idx": 0,
      "op": "LDX",
      "dst": "r0",
      "src": "r1",
      "off": 2248
    }
  ],
  "summary": {
    "total_operations": 4,
    "stats": {
      "total_relos_processed": 1,
      "successful_relos": 1,
      "failed_relos": 0,
      "instructions_patched": 1
    }
  }
}
```
