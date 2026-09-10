# 리눅스 커널 eBPF 검증기 레지스터 범위 추적 및 분기 가지치기 (Linux Kernel eBPF Verifier Range Tracking & Branch Pruning)

## 문제 설명

리눅스 커널의 **eBPF(Extended Berkeley Packet Filter)** 서브시스템은 사용자 공간에서 작성된 임베디드 바이트코드를 커널 공간(XDP, TC, kprobe, tracepoint 등)에서 안전하게 직접 JIT 컴파일하여 실행할 수 있도록 지원합니다.
커널 공간의 메모리 충돌, 커널 패닉(Kernel Panic), 무한 루프, 인가되지 않은 메모리 임의 접근을 사전에 원천 차단하기 위해, 커널은 코드가 적재(Load)되기 직전에 **eBPF 검증기(Verifier - `kernel/bpf/verifier.c`)**를 통해 수학적 **추상 해석(Abstract Interpretation)** 기반의 정적 분석을 수행합니다.

본 문제에서는 실제 리눅스 커널 eBPF 검증기의 핵심 원리인 **추상 해석 기반 레지스터 상태 및 수치 범위 추적(Register Range Tracking: `umin`, `umax`)**, **패킷 포인터 경계 검증(`PTR_TO_PACKET` Bounds Checking)**, **초기화되지 않은 레지스터(`NOT_INIT`) 검출**, 그리고 **상태 포함 관계(State Subsumption)를 활용한 분기 가지치기(Branch Pruning - `states_equal()` / `regsafe()`)** 시뮬레이터를 구현합니다.

---

## 동작 명세

### 1. eBPF 가상 레지스터 모델 (Registers: R0 ~ R10)
- **R0**: 함수 반환값 / 프로그램 종료 코드. `EXIT` 명령 시점에 반드시 유효한 스칼라 값이어야 합니다. 미초기화(`NOT_INIT`) 상태로 종료 시 거부됩니다.
- **R1**: 프로그램 인자 / 컨텍스트. 프로그램 시작 시 네트워크 패킷 버퍼 시작점을 가리키는 `PTR_TO_PACKET(off=0, pkt_range=0)`으로 초기화됩니다.
- **R2**: 패킷 끝점(`PTR_TO_PACKET_END`, `off=0`).
- **R10**: 512바이트 스택 프레임 베이스 포인터(`PTR_TO_STACK`, `off=0`, 읽기 전용).
- **R3 ~ R9**: 범용 레지스터로, 프로그램 시작 시 초기화되지 않은 상태(`NOT_INIT`)입니다.

### 2. 레지스터 상태 분류 (`RegType`)
- `NOT_INIT`: 미초기화 상태. 값을 읽으려고 시도하면 검증 거부.
- `SCALAR`: 부호 없는 정수 스칼라 값. 추상 해석을 위한 수치 범위 `[umin, umax]`를 보관합니다.
- `PTR_TO_PACKET`: 패킷 헤더 포인터. 현재 오프셋(`off`)과 검증된 안전 바이트 길이(`pkt_range`)를 가집니다.
- `PTR_TO_PACKET_END`: 패킷 끝 포인터.
- `PTR_TO_STACK`: 커널 스택 포인터.

### 3. 지원 명령어 명세 (Instruction Set)
- `MOV`:
  - `{"op": "MOV", "dst": d, "imm": val}`: `Rd`를 스칼라 상수 `val`(`umin=val, umax=val`)로 설정.
  - `{"op": "MOV", "dst": d, "src": s}`: `Rs`의 상태(타입 및 범위)를 `Rd`로 복사. `Rs`가 `NOT_INIT`이면 `READ_UNINITIALIZED_REG_Rs`로 거부.
- `ADD`:
  - `{"op": "ADD", "dst": d, "imm": val}`: `Rd`가 `SCALAR`이면 `umin += val, umax += val`. `Rd`가 `PTR_TO_PACKET`이면 `off += val`.
  - `{"op": "ADD", "dst": d, "src": s}`: `Rs`가 스칼라이고 `Rd`가 스칼라이면 범위 덧셈(`umin += Rs.umin, umax += Rs.umax`). `Rd`가 패킷 포인터이고 `Rs`가 고정 상수 스칼라이면 `off += Rs.umin`.
- `SUB`:
  - `{"op": "SUB", "dst": d, "imm": val}`: 스칼라 레지스터 감산(`umin = max(0, umin - val), umax = max(0, umax - val)`).
  - `{"op": "SUB", "dst": d, "src": s}`: 스칼라 간 감산(`umin = max(0, umin - Rs.umax), umax = max(0, umax - Rs.umin)`).
- `CHECK_PKT_LEN`:
  - `{"op": "CHECK_PKT_LEN", "dst": d, "imm": val}`: 패킷 경계 검증. `Rd`가 `PTR_TO_PACKET`이어야 하며, 패킷의 안전 검증 범위(`pkt_range`)를 `max(pkt_range, Rd.off + val)`로 갱신합니다.
- `LDX`:
  - `{"op": "LDX", "dst": d, "src": s, "off": offset, "size": S}`: 메모리 로드 (`*(u{S*8} *)(Rs + offset)`).
  - `Rs`가 `PTR_TO_PACKET`일 때, 요구 경계인 `Rs.off + offset + S`가 현재 입증된 `Rs.pkt_range`를 초과하면 즉시 `OUT_OF_BOUNDS_PACKET_READ_REQ_{req}_PROVEN_{proven}` 오류로 거부합니다.
  - 안전성 검증 통과 시 `Rd`는 스칼라 `[0, (1 << (S*8)) - 1]`로 설정됩니다.
- `JGT`:
  - `{"op": "JGT", "dst": d, "imm": val, "off": jump_offset}`: 조건부 분기. `Rd > val`일 경우 `pc + 1 + jump_offset`으로 분기.
  - 분기(Branch Taken) 경로: `Rd.umin = max(Rd.umin, val + 1)`로 범위 축소.
  - 직진(Fallthrough) 경로: `Rd.umax = min(Rd.umax, val)`로 범위 축소.
- `JEQ`:
  - `{"op": "JEQ", "dst": d, "imm": val, "off": jump_offset}`: 조건부 분기. `Rd == val`일 경우 `pc + 1 + jump_offset`으로 분기.
  - 분기 경로: `Rd.umin = max(Rd.umin, val), Rd.umax = min(Rd.umax, val)`.
  - 직진 경로: `Rd != val`.
- `JA`:
  - `{"op": "JA", "off": jump_offset}`: 무조건 점프 (`pc = pc + 1 + jump_offset`).
- `EXIT`:
  - `{"op": "EXIT"}`: 프로그램 종료. `R0`가 `NOT_INIT`이면 `EXIT_WITHOUT_RETURN_VAL_IN_R0`으로 거부.

### 4. 분기 가지치기 (Branch Pruning & State Subsumption)
- DFS 탐색 중 이미 검증이 완료된(Safe EXIT에 도달한) 경로상의 각 PC별 레지스터 상태들을 캐싱합니다.
- 새로운 경로가 특정 PC에 도달했을 때, 기존 캐시된 상태와 비교하여 **현재 상태가 기존 안전 상태에 포함(Subsumed)**되면 더 이상 탐색하지 않고 해당 분기를 즉시 가지치기(`branches_pruned += 1`)하고 안전 종료 처리합니다.
- **포함 판정 조건 (`cur.is_subsumed_by(old)`)**:
  1. 레지스터 타입이 일치해야 함.
  2. `SCALAR`: 현재 수치 범위가 기존 범위의 부분집합이어야 함 (`cur.umin >= old.umin and cur.umax <= old.umax`).
  3. `PTR_TO_PACKET`: 오프셋이 동일하고, 현재 안전 증명 범위가 기존보다 크거나 같아야 함 (`cur.off == old.off and cur.pkt_range >= old.pkt_range`).
  4. 11개 모든 레지스터(R0~R10)가 위 조건을 만족해야 함.

---

## 입력 형식

JSON 형식으로 표준 입력(`sys.stdin`)에 주어집니다.

```json
{
  "config": {
    "max_insns": 1000
  },
  "instructions": [
    {"op": "CHECK_PKT_LEN", "dst": 1, "imm": 14},
    {"op": "LDX", "dst": 3, "src": 1, "off": 0, "size": 4},
    {"op": "MOV", "dst": 0, "imm": 1},
    {"op": "EXIT"}
  ]
}
```

---

## 출력 형식

검증 성공 시:
```json
{
  "verified": true,
  "insns_processed": 4,
  "branches_pruned": 0,
  "paths_explored": 1,
  "status": "PROGRAM_VERIFIED_SAFE"
}
```

검증 실패 시:
```json
{
  "verified": false,
  "rejection_reason": "OUT_OF_BOUNDS_PACKET_READ_REQ_16_PROVEN_14",
  "failing_pc": 1,
  "insns_processed": 2,
  "branches_pruned": 0
}
```
