# 이론: Linux Kernel Ftrace Function Graph Tracer 및 리턴 트램펄린 스택 하이재킹 아키텍처

## 1. 커널 함수 프로파일링의 딜레마: 진입 vs 종료

리눅스 커널에서 함수의 진입(Entry)을 감지하는 것은 비교적 직관적입니다. GCC/Clang 컴파일러 옵션인 `-pg` 또는 `-mfentry`를 활성화하면 컴파일러가 모든 함수의 프롤로그(Prologue) 맨 첫 줄에 5바이트 호출 명령어인 `call __fentry__`를 자동으로 생성합니다.

그러나 **함수가 종료되어 복귀하는 시점(Exit)**을 어떻게 감지할 수 있을까요?
- C 언어 함수는 중간에 여러 개의 `return` 문을 가질 수 있습니다.
- 컴파일러가 생성한 기계어에는 수많은 조건부 분기문과 복수의 `ret` 명령어가 산재되어 있어, 정적으로 종료 지점을 일일이 패칭하는 것은 비효율적이며 버그를 유발합니다.

Ftrace Function Graph Tracer는 이 난제를 **함수가 호출될 때 스택 프레임에 기록되는 반환 주소(Return Address)를 런타임에 원자적으로 변조(Hijack)하는 기법**으로 완벽하게 해결했습니다 (`kernel/trace/trace_functions_graph.c`).

---

## 2. 반환 주소 하이재킹과 섀도 스택 (`task_struct->ret_stack`)

CPU가 `call func` 명령어를 실행하면, 복귀할 다음 명령어의 주소(`IP`)를 스택 포인터(`RSP`)가 가리키는 스택 메모리에 푸시(Push)합니다.

```
 [Normal x86 Call Stack]
 RSP ----> [ 0x401050 (Caller's Return Address) ]
```

함수 프롤로그의 `call __fentry__`가 실행되면, Function Graph Tracer는 다음과 같은 스택 하이재킹 파이프라인을 실행합니다:

```c
int trace_graph_entry(struct ftrace_graph_ent *trace)
{
    unsigned long *parent = (unsigned long *)trace->parent_ip;
    unsigned long orig_ret = *parent;

    /* 1. 태스크의 섀도 스택에 원래 복귀 주소와 진입 시각 저장 */
    current->ret_stack[current->curr_ret_stack].ret = orig_ret;
    current->ret_stack[current->curr_ret_stack].func = trace->func;
    current->ret_stack[current->curr_ret_stack].calltime = trace_clock_local();
    current->curr_ret_stack++;

    /* 2. CPU 스택의 복귀 주소를 리턴 트램펄린 주소로 변조! */
    *parent = (unsigned long)return_to_handler;
    return 1;
}
```

이제 함수가 수많은 루프와 조건문을 거쳐 어떤 `return` 문을 통해 `ret` 명령어를 실행하더라도, CPU는 원래의 호출자가 아니라 **Ftrace의 리턴 트램펄린(`return_to_handler`)**으로 무조건 점프하게 됩니다!

---

## 3. 리턴 트램펄린 (`return_to_handler`)의 동작 원리

어셈블리로 작성된 `arch/x86/kernel/ftrace_64.S`의 `return_to_handler`는 다음과 같이 동작합니다:
1. **레지스터 보존**: 함수의 반환값(RAX, RDX)과 상태 플래그를 보존하기 위해 레지스터를 임시 스택에 푸시합니다.
2. **`ftrace_return_to_handler()` 호출**:
   - 태스크의 섀도 스택에서 가장 최근 프레임을 팝(`current->curr_ret_stack--`)합니다.
   - 현재 시각(`now`)을 읽어 소요 시간(`duration = now - calltime`)을 계산합니다.
   - 트레이스 버퍼에 `GRAPH_EXIT` 레코드를 출력합니다.
   - 저장되어 있던 원래 복귀 주소(`orig_ret`)를 반환합니다.
3. **레지스터 복원 및 실제 호출자로 복귀**:
   - 보존했던 반환값 레지스터(RAX, RDX)를 복원합니다.
   - 복원된 `orig_ret` 주소로 점프(`jmp *orig_ret`)하여 원래 호출자가 아무 일도 없었던 것처럼 정상적으로 실행을 이어가게 합니다.

---

## 4. 깊이 제한(`max_graph_depth`) 및 재귀 트랩 방지

1. **섀도 스택 오버플로 방지**:
   - 태스크마다 할당되는 섀도 스택(`ret_stack`)의 크기는 기본 50개(`FTRACE_RETFUNC_DEPTH`)로 고정되어 있습니다.
   - 깊은 재귀 호출(Deep Recursion)이나 장대한 커널 콜 스택으로 인해 한도를 초과하면, tracer는 스택 하이재킹을 중단하고 원래 복귀 주소를 그대로 유지하여 시스템 안정성을 보장합니다.
2. **루트 함수 필터링 (`set_graph_function`)**:
   - 시스템 전체의 모든 함수를 트레이싱하면 엄청난 로그 폭풍(Log Storm)과 오버헤드가 발생합니다.
   - `set_graph_function`에 `vfs_read`와 같은 특정 진입점 함수를 지정하면, 오직 해당 함수가 실행되는 서브트리 내부에서만 스택 하이재킹이 활성화되므로 최소한의 오버헤드로 원하는 병목 구간을 정밀하게 프로파일링할 수 있습니다.
