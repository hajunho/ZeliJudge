# 문제 460: Linux Kernel Ftrace 함수 그래프 트레이서 및 리턴 트램펄린 엔진 (Grand Milestone 980 🌟)

## 문제 설명

리눅스 커널의 **Ftrace Function Graph Tracer**(`kernel/trace/trace_functions_graph.c`, `arch/x86/kernel/ftrace.c`)는 커널 함수들의 호출 관계(Call Graph)와 각 함수가 소비한 정확한 실행 시간(소요 시간, Duration)을 나노초 단위로 측정하여 시각화해 주는 커널의 핵심 내장 프로파일링 서브시스템입니다.

Function Graph Tracer가 함수가 시작될 때(`__fentry__`)뿐만 아니라, **함수가 종료되어 복귀하는 시점(`RET`)까지 정확히 가로채어 소요 시간을 측정**하는 원리는 저수준 스택 하이재킹(Stack Hijacking)과 섀도 리턴 스택(Shadow Return Stack) 아키텍처에 기반합니다:

```
+-----------------------------------------------------------------------------------------+
|                  Ftrace Function Graph Tracer Stack Hijacking Flow                      |
+-----------------------------------------------------------------------------------------+

 [CPU Call Stack]                                         [Task Shadow Stack: ret_stack]
  +-----------------------+                                +----------------------------+
  | [Hijacked Ret Addr]   | <------------------------------| ret: 0x401000 (orig_ret)   |
  | = return_to_handler   |                                | func: "vfs_read"           |
  +-----------------------+                                | calltime: 1000 ns          |
                                                           | depth: 0                   |
                                                           +----------------------------+

 1. Function Entry (__fentry__):
    - trace_graph_entry() records calltime.
    - Saves original return address to task's shadow ret_stack.
    - Overwrites return address on CPU stack with &return_to_handler!

 2. Function Execution & Nesting:
    - Child functions also call __fentry__, pushing new frames to shadow ret_stack (depth 1, 2...).

 3. Function Exit (RET):
    - CPU executes RET, popping return_to_handler address instead of original caller!
    - return_to_handler trampoline intercepts return:
        a. Pops frame from shadow ret_stack.
        b. Computes duration = exit_time - calltime.
        c. Emits GRAPH_EXIT trace event.
        d. Restores orig_ret and jumps to the real caller!
```

### 핵심 메커니즘
1. **스택 하이재킹 (`return_to_handler`)**:
   - 함수 진입 시점(`FENTRY_CALL`)에 CPU 하드웨어 스택에 저장된 원래의 복귀 주소(`caller_ret_addr`)를 커널의 리턴 트램펄린 주소(`return_to_handler = 0xffffffff81000000`)로 덮어씁니다.
   - 원래의 복귀 주소와 진입 시각(`calltime`), 함수 이름, 깊이(`depth`)는 태스크 전용 섀도 스택(`ret_stack`)에 안전하게 보관합니다.
2. **트램펄린 가로채기 및 시간 계산 (`FEXIT_RETURN`)**:
   - 함수가 `RET`을 수행하여 하드웨어 스택에서 팝한 주소가 `return_to_handler`인 경우, 섀도 스택에서 프레임을 팝하여 `duration_ns = exit_time - calltime`을 계산하고 원래 주소(`restored_ret`)로 정상 복귀시킵니다.
   - 하드웨어 스택의 주소가 트램펄린 주소가 아닌 경우 가로채기 대상이 아니므로 `NORMAL_RETURN`을 반환합니다.
3. **루트 함수 필터링 (`graph_funcs`)**:
   - `graph_funcs` 목록이 설정된 경우, 지정된 루트 함수가 호출되기 전까지의 상위 호출은 `FILTERED_OUT`되며, 루트 함수 및 그 자식 함수들만 트레이싱 대상이 됩니다. 루트 함수가 리턴되면 다시 필터링이 활성화됩니다.
4. **최대 깊이 제약 (`max_depth`)**:
   - 섀도 스택의 깊이가 `max_depth`에 도달하면 더 깊은 자식 함수는 `DEPTH_OVERFLOW`로 처리되어 스택 하이재킹을 수행하지 않고 일반 실행됩니다 (`stats.depth_overflows += 1`).

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:
- `config`:
  - `max_depth`: int (기본값: 16)
  - `return_to_handler_addr`: int (기본값: `0xffffffff81000000`)
- `operations`: 일련의 연산 배열.

지원되는 연산:
1. `{"op": "CONFIGURE", "enabled": bool, "graph_funcs": list[str]|null, "max_depth": int|null}`
   - 트레이서 활성화 여부, 대상 루트 함수 목록, 최대 추적 깊이를 설정합니다.
2. `{"op": "FENTRY_CALL", "func": str, "caller_ret_addr": int, "timestamp": int}`
   - 함수 진입 훅을 호출합니다.
   - 비활성화 시 `TRACING_DISABLED`, 필터 제외 시 `FILTERED_OUT`, 깊이 초과 시 `DEPTH_OVERFLOW`.
   - 성공 시 하드웨어 스택을 `return_to_handler`로 하이재킹하고 `GRAPH_ENTRY` 이벤트 기록.
3. `{"op": "FEXIT_RETURN", "timestamp": int}`
   - 함수 종료 훅을 호출합니다.
   - 하드웨어 스택이 비었으면 `EMPTY_HW_STACK`.
   - 복귀 주소가 트램펄린이 아니면 `NORMAL_RETURN`.
   - 트램펄린 적중 시 섀도 스택에서 프레임을 꺼내 소요 시간을 계산하고 `GRAPH_EXIT` 이벤트 반환.
4. `{"op": "QUERY_TRACER_STATE"}`
   - 현재 깊이, 스택 길이, 기록된 이벤트 목록, 통계(`stats`)를 반환합니다.

---

## 출력 형식

표준 출력(stdout)으로 각 연산의 결과를 담은 JSON을 한 줄(compact)로 출력합니다:
```json
{"results": [...]}
```
