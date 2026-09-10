# 리눅스 커널 eBPF CO-RE(Compile Once – Run Everywhere) 및 BPF Type Format(BTF) 필드 오프셋 릴로케이션 엔진

## 문제 설명

리눅스 커널 내부의 상태를 모니터링하고 추적(Tracing)하는 eBPF 프로그램은 커널 내부 핵심 자료구조(`struct task_struct`, `struct mm_struct`, `struct sock`, `struct sk_buff`)의 멤버 필드를 메모리에서 직접 역참조(`LDX r1, [r2 + offset]`)해야 합니다.

과거 BCC(BPF Compiler Collection) 시절에는 이 문제를 해결하기 위해 프로덕션 서버마다 1GB가 넘는 무거운 LLVM/Clang 컴파일러와 리눅스 커널 헤더(`linux-headers-$(uname -r)`)를 강제로 설치해야 했습니다. 대상 커널 버전이 바뀔 때마다 컴파일 타임에 계산된 구조체 필드 오프셋이 달라지기 때문입니다. 예를 들어, 리눅스 5.15에서는 `task_struct.pid`가 오프셋 `12`에 위치했지만, 새로운 커널 플래그나 보안 필드가 추가된 리눅스 6.1에서는 오프셋 `16`으로 밀려납니다. 예전 오프셋 그대로 바이트코드를 실행하면 **전혀 다른 메모리 영역을 읽거나 커널 패닉, 혹은 BPF 검증기(Verifier)에 의해 로드가 거부**됩니다.

이를 근본적으로 해결하기 위해 리눅스 커널 5.2+과 `libbpf`에 도입된 혁신적 패러다임이 바로 **CO-RE (Compile Once – Run Everywhere, 한 번 컴파일하여 어디서나 실행)**입니다.

CO-RE 환경에서 개발자는 한 번만 eBPF C 코드를 컴파일하여 표준 ELF 객체(`.o`)를 생성합니다. 이때 컴파일러는 커널 자료구조의 메타데이터인 **BTF (BPF Type Format)**와 필드 접근 경로를 담은 **CO-RE 릴로케이션 레코드 (`.BTF.ext` 내 `bpf_core_relo`)**를 바이트코드와 함께 번들링합니다.

그리고 런타임에 프로그램이 대상 호스트 커널에 로드될 때, `libbpf` 로더는:
1. 대상 시스템의 실행 중인 커널 BTF (`/sys/kernel/btf/vmlinux`)를 로드하고,
2. 타입 그래프(Type Graph)를 순회하여 대상 커널에서 해당 필드의 실제 바이트 오프셋, 필드 크기, 및 비트필드 위치를 동적으로 탐색한 뒤,
3. eBPF 바이트코드의 메모리 로드/산술 명령어 즉시값(`imm`) 또는 오프셋(`off`)을 실시간으로 **패치(Relocation, 릴로케이션)**합니다!

당신은 eBPF 런타임 로더 및 커널 서브시스템의 핵심 엔지니어로서, 대상 커널의 BTF 타입 그래프를 탐색하고 6가지 주요 CO-RE 릴로케이션 명령을 처리하여 바이트코드를 실시간으로 재배치하는 **eBPF CO-RE BTF Relocation Machine**을 완성해야 합니다.

---

## 시스템 상세 사양 및 릴로케이션 유형

### 1. BTF 타입 그래프 구조
- `INT`: 정수형 (`size`, `name`, `encoding`)
- `PTR`: 포인터 (`type_id`)
- `STRUCT`: 구조체 (`name`, `size`, `members` 배열)
  - `members`: `{"name": str, "type_id": str, "offset": int, "bit_offset": int, "bit_size": int}`
- `TYPEDEF`, `CONST`, `VOLATILE`: 한정자/별칭 (타입 체이닝을 통해 언래핑 필요)

### 2. 지원하는 CO-RE 릴로케이션 종류 (`kind`)

1. **`FIELD_BYTE_OFFSET` (필드 바이트 오프셋)**:
   - 대상 구조체에서 지정된 접근 경로(`access_path`, 예: `["__sk_common", "skc_dport"]` 또는 `["pid"]`)를 따라 총 바이트 오프셋을 누적 계산합니다.
   - 포인터나 인라인 임베디드 구조체가 중첩되어 있을 경우, 체인을 따라가며 오프셋을 누적합니다.
   - 대상 명령어가 메모리 접근(`LDX`, `STX`, `LD`, `ST`)인 경우 명령어의 `off` 필드를 패치하고, 일반 연산(`ALU_IMM` 등)인 경우 `imm` 필드를 패치합니다.
2. **`FIELD_BYTE_SIZE` (필드 바이트 크기)**:
   - 접근 경로 끝에 위치한 최종 필드 타입의 크기(`size` 바이트)를 계산하여 명령어의 `imm`에 패치합니다.
3. **`FIELD_EXISTS` (필드 존재 여부 확인, `bpf_core_field_exists`)**:
   - 대상 커널 BTF에 해당 필드가 존재하면 `imm = 1`, 존재하지 않으면 `imm = 0`으로 패치합니다.
4. **`TYPE_EXISTS` (타입 존재 여부 확인, `bpf_core_type_exists`)**:
   - 대상 커널 BTF에 지정된 구조체/타입 이름이 존재하면 `imm = 1`, 아니면 `imm = 0`으로 패치합니다.
5. **`TYPE_SIZE` (구조체 크기, `bpf_core_type_size`)**:
   - 대상 커널 BTF에서 지정된 구조체의 전체 바이트 크기(`size`)를 찾아 `imm`에 패치합니다.
6. **`FIELD_BIT_OFFSET` & `FIELD_BIT_SIZE` (비트필드 재배치)**:
   - 구조체 내부 비트필드 멤버의 비트 오프셋(`bit_offset`) 및 비트 너비(`bit_size`)를 추출하여 `imm`에 패치합니다.

### 3. 필드 부재 및 에러 정책
- 대상 커널에서 필수 필드/타입이 존재하지 않고 `allow_missing == false`인 경우:
  `status: "FAILED_FIELD_NOT_FOUND"` 또는 `"FAILED_TYPE_NOT_FOUND"`, `failed_relocations += 1`.
- `allow_missing == true`인 경우 (조건부 폴백):
  해당 필드를 0으로 패치하고 `status: "SUCCESS_ZERO_FALLBACK"`, `successful_relocations += 1`.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다:

```json
{
  "target_btf": {
    "1": {"kind": "INT", "name": "int", "size": 4},
    "2": {"kind": "PTR", "type_id": "3"},
    "3": {
      "kind": "STRUCT", "name": "task_struct", "size": 144,
      "members": [
        {"name": "state", "type_id": "1", "offset": 0},
        {"name": "pid", "type_id": "1", "offset": 12},
        {"name": "parent", "type_id": "2", "offset": 16}
      ]
    }
  },
  "instructions": [
    {"insn_idx": 0, "op": "LDX", "dst": 1, "src": 2, "off": 4, "imm": 0},
    {"insn_idx": 1, "op": "ALU_IMM", "dst": 3, "src": 0, "off": 0, "imm": 0}
  ],
  "relocations": [
    {
      "insn_idx": 0,
      "kind": "FIELD_BYTE_OFFSET",
      "root_type_name": "task_struct",
      "access_path": ["pid"]
    },
    {
      "insn_idx": 1,
      "kind": "FIELD_EXISTS",
      "root_type_name": "task_struct",
      "access_path": ["pid"]
    }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 릴로케이션 요약, 상세 결과, 및 패치 완료된 eBPF 명령어 배열을 포함하는 단일 JSON 라인을 출력합니다:

```json
{
  "relocation_summary": {
    "total_relocations": 2,
    "successful_relocations": 2,
    "failed_relocations": 0
  },
  "relocation_details": [
    {
      "insn_idx": 0,
      "kind": "FIELD_BYTE_OFFSET",
      "root_type": "task_struct",
      "access_path": ["pid"],
      "status": "SUCCESS",
      "original_val": 4,
      "relocated_val": 12,
      "patched_field": "off"
    },
    {
      "insn_idx": 1,
      "kind": "FIELD_EXISTS",
      "root_type": "task_struct",
      "access_path": ["pid"],
      "status": "SUCCESS",
      "original_val": 0,
      "relocated_val": 1,
      "patched_field": "imm"
    }
  ],
  "patched_instructions": [
    {"insn_idx": 0, "op": "LDX", "dst": 1, "src": 2, "off": 12, "imm": 0},
    {"insn_idx": 1, "op": "ALU_IMM", "dst": 3, "src": 0, "off": 0, "imm": 1}
  ]
}
```
