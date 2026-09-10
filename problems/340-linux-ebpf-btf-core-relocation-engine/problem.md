# 리눅스 커널 eBPF BPF Type Format (BTF) 기반 CO-RE (Compile Once – Run Everywhere) 재배치 엔진

## 문제 설명

리눅스 커널 관측 및 보안의 핵심 표준인 **eBPF(Extended Berkeley Packet Filter)**의 오랜 난제 중 하나는 **커널 간 이식성(Portability)** 문제였습니다. 개발자가 컴파일한 eBPF 프로그램이 커널 내부 구조체(예: `task_struct`, `mm_struct`, `sk_buff`)의 멤버 변수를 읽을 때, 해당 변수의 바이트 오프셋(Offset)은 커널 버전, 컴파일러 옵션, 또는 커널 빌드 설정(`#ifdef CONFIG_*`)에 따라 달라집니다. 과거 BCC(BPF Compiler Collection)는 이를 해결하기 위해 실행 대상 호스트마다 무거운 `kernel-devel` 헤더 패키지와 Clang/LLVM 툴체인을 설치하여 현장에서 C 코드를 컴파일해야 했습니다.

이 문제를 근본적으로 해결한 현대 리눅스 커널의 핵심 혁신 기술이 바로 **CO-RE (Compile Once – Run Everywhere)**와 **BTF (BPF Type Format)**입니다.
1. **단 한 번의 컴파일**: 개발자는 로컬 머신에서 생성된 단일 헤더(`vmlinux.h`)를 기반으로 Clang을 사용하여 eBPF 바이트코드를 단 1회 컴파일합니다. 이때 Clang은 구조체 멤버에 접근하는 명령어에 대해 **BTF 재배치 레코드(`bpf_core_relo`)**를 `.BTF.ext` ELF 섹션에 기록합니다.
2. **현장 동적 재배치(Libbpf / BPF Loader)**: 컴파일된 BPF 바이너리가 대상 호스트에 배포되면, BPF 로더는 대상 호스트 커널의 `/sys/kernel/btf/vmlinux`에 내장된 실제 **타깃 BTF**를 읽어 들입니다.
3. **명령어 패치(Instruction Patching)**: 로더는 소스 BTF와 타깃 BTF 간의 구조체 이름, 필드 이름 경로(`access_str`, 예: `"0:2:1"`), 구조체 플레이버(Flavor, `___compat` 등)를 일치시켜 실제 타깃 커널의 멤버 오프셋 및 크기를 계산한 후, BPF 바이트코드의 메모리 로드/스토어 오프셋(`off`) 또는 즉시값(`imm`)을 현장에서 직접 덮어씁니다.

본 문제에서는 리눅스 커널과 Libbpf의 핵심 컴포넌트인 **eBPF CO-RE BTF 재배치 및 바이트코드 패치 엔진**을 정밀하게 구현해야 합니다.

---

## 시스템 아키텍처 및 CO-RE 재배치 파이프라인

```
+---------------------------------------------------------------------------------------------------+
|               Linux Kernel eBPF CO-RE (Compile Once - Run Everywhere) Engine                      |
+---------------------------------------------------------------------------------------------------+

   [ Developer Machine: Source BTF ]                    [ Target Node: Kernel Target BTF ]
   +---------------------------------------+            +---------------------------------------+
   | struct task_struct {                  |            | struct task_struct {                  |
   |   int pid;         // offset: 16      |            |   int flags;       // offset: 16      |
   |   char comm[16];   // offset: 20      |   ===>     |   int pid;         // offset: 20 (SHIFT!) |
   |   struct mm *mm;   // offset: 40      |            |   char comm[16];   // offset: 24 (SHIFT!) |
   | };                                    |            |   struct mm *mm;   // offset: 48 (SHIFT!) |
   +---------------------------------------+            +---------------------------------------+
                       |                                                    |
                       v                                                    v
   [ BPF Instructions & Relocation Records ]            [ CO-RE Type Matcher & Flavor Resolver ]
   +---------------------------------------+            +---------------------------------------+
   | Insn #0: BPF_LDX_MEM dst:1 off:16     |            | - Strip flavor: task___v2 -> task     |
   | Relo #0: task_struct -> "0:0" (pid)   |            | - Match member name: "pid" in target  |
   | Kind: FIELD_BYTE_OFFSET               |            | - Calculate Target Offset: 20 bytes   |
   +---------------------------------------+            +---------------------------------------+
                       |                                                    |
                       +------------------------+---------------------------+
                                                |
                                                v
                                [ BPF Bytecode Instruction Rewriter ]
                                +-----------------------------------+
                                | Insn #0: BPF_LDX_MEM dst:1 off:20 |  <-- (Patched!)
                                +-----------------------------------+
```

---

## 재배치 규칙 및 엔진 명세

### 1. BTF 구조체 및 멤버 표현
- 각 BTF는 타입 ID(`id`), 종류(`kind`: `"STRUCT"`, `"INT"`, `"PTR"` 등), 이름(`name`), 크기(`size`), 그리고 멤버 목록(`members`)을 가집니다.
- 멤버는 `name`, `type_id`, `offset_bytes`, `size`를 포함합니다.

### 2. 구조체 플레이버(Struct Flavor) 처리
- 소스 또는 타깃 구조체 이름에 삼중 밑줄(`___`)이 포함된 경우(예: `task_struct___compat`, `task_struct___v2`):
  - 기저 타입 이름(Base Name)은 `___` 앞부분(`task_struct`)으로 추출됩니다.
  - 타깃 커널 검색 시 정확한 기저 이름을 우선 조회하고, 일치하는 타입이 없으면 동일 기저 이름을 공유하는 플레이버 타입을 대체 매칭합니다.

### 3. 필드 접근 경로(Access String) 해석
- `access_str`은 콜론(`:`)으로 구분된 인덱스 열입니다 (예: `"0:2:0"`):
  - 첫 번째 인덱스 `0`은 베이스 객체 접근자입니다.
  - 이후 인덱스는 소스 BTF의 구조체 멤버 순서를 나타냅니다.
  - 엔진은 소스 BTF를 따라 멤버 이름 시퀀스(예: `["mm", "rss"]`)를 추출한 후, 타깃 BTF에서 해당 이름을 가진 멤버를 순차적으로 탐색하여 타깃 누적 오프셋을 계산합니다.

### 4. 5대 재배치 종류 (`kind`)
1. `FIELD_BYTE_OFFSET`: 대상 필드의 타깃 누적 바이트 오프셋을 계산하여 해당 명령어의 `off` 필드에 기록합니다.
2. `FIELD_BYTE_SIZE`: 대상 필드의 바이트 크기를 계산하여 해당 명령어의 `imm` 필드에 기록합니다.
3. `FIELD_EXISTS`: 대상 필드가 타깃 구조체에 존재하면 `imm = 1`, 존재하지 않으면 `imm = 0`으로 패치합니다.
4. `TYPE_EXISTS`: 대상 타입이 타깃 BTF에 존재하면 `imm = 1`, 없으면 `imm = 0`으로 패치합니다.
5. `TYPE_SIZE`: 대상 타입의 타깃 전체 `size`를 계산하여 `imm` 필드에 기록합니다.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "target_btf": {
    "types": {
      "1": {
        "id": 1,
        "kind": "STRUCT",
        "name": "task_struct",
        "size": 160,
        "members": [
          {"name": "pid", "type_id": 10, "offset_bytes": 20, "size": 4}
        ]
      },
      "10": {"id": 10, "kind": "INT", "name": "int", "size": 4}
    }
  },
  "program": {
    "source_btf": {
      "types": {
        "1": {
          "id": 1,
          "kind": "STRUCT",
          "name": "task_struct",
          "size": 128,
          "members": [
            {"name": "pid", "type_id": 10, "offset_bytes": 16, "size": 4}
          ]
        },
        "10": {"id": 10, "kind": "INT", "name": "int", "size": 4}
      }
    },
    "instructions": [
      {"opcode": "BPF_LDX_MEM", "dst": 1, "src": 2, "off": 16, "imm": 0}
    ],
    "relocations": [
      {"insn_idx": 0, "type_id": 1, "access_str": "0:0", "kind": "FIELD_BYTE_OFFSET"}
    ]
  }
}
```

---

## 출력 형식

표준 출력(stdout)으로 패치된 명령어 목록, 재배치 로그, 요약 결과를 담은 JSON 객체를 공백 없는 압축 형식(`separators=(',', ':')`)으로 출력합니다:

```json
{
  "patched_instructions": [
    {"opcode": "BPF_LDX_MEM", "dst": 1, "src": 2, "off": 20, "imm": 0}
  ],
  "relocation_log": [
    {"insn_idx": 0, "kind": "FIELD_BYTE_OFFSET", "resolved_offset": 20, "status": "RESOLVED"}
  ],
  "summary": {
    "total_relocations": 1,
    "successful_relocations": 1,
    "status": "SUCCESS"
  }
}
```

---

## 제약 조건

- BPF 명령어 수: $1 \le N \le 1,000$
- 재배치 레코드 수: $1 \le R \le 500$
- BTF 타입 수: $1 \le |T| \le 500$
- 지원 kind: `FIELD_BYTE_OFFSET`, `FIELD_BYTE_SIZE`, `FIELD_EXISTS`, `TYPE_EXISTS`, `TYPE_SIZE`
- 표준 라이브러리만을 사용하여 구현해야 함
