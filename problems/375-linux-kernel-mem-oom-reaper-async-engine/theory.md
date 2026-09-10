# 리눅스 커널 OOM Reaper와 비동기 메모리 회수 아키텍처

## 1. 전통적 OOM 킬러의 치명적 아킬레스건: D-상태 데드락

리눅스 커널의 물리 메모리가 고갈되면 페이지 회수기(`kswapd` 및 Direct Reclaim)가 파일 페이지와 스왑 가능한 익명 페이지를 비워내려 시도합니다. 그러나 더 이상 회수할 수 없는 한계에 도달하면 커널은 `out_of_memory()`를 호출합니다.

OOM 킬러의 고전적인 작동 방식:
1. `select_bad_process()`가 시스템 전체 프로세스 트리를 순회하며 `badness()` 점수를 계산합니다.
2. 가장 많은 메모리를 낭비하고 있는 희생자 태스크(Victim)에게 `SIGKILL` 시그널을 전송합니다.
3. OOM 킬러는 다른 프로세스들의 메모리 할당을 잠시 유보하고, 희생자가 죽을 때까지 기다립니다.

그러나 이 메커니즘에는 치명적인 설계 결함이 존재했습니다:
- **D-상태(TASK_UNINTERRUPTIBLE) 프리징**: 만약 희생자 프로세스가 응답하지 않는 NFS 서버의 I/O를 기다리고 있거나, 디바이스 드라이버 내부의 뮤텍스에서 슬립 중이라면, 프로세스는 유저스페이스 시그널 핸들러나 `do_exit()`에 결코 도달하지 못합니다.
- **메모리 미반환**: 프로세스가 종료되지 않으므로 `exit_mmap()`이 호출되지 않고, 수 기가바이트의 메모리는 여전히 프로세스에 묶여 있습니다.
- **연쇄적 OOM 라이브락(Livelock)**: 다른 프로세스들은 메모리가 없어 OOM 루프에 빠지지만, OOM 킬러는 "이미 죽어가는 희생자가 있다"고 판단하여 새 희생자를 죽이지 못하고 시스템 전체가 멈춰버립니다.

---

## 2. OOM Reaper의 설계와 동작 원리

이 문제를 해결하기 위해 미할 호츠코(Michal Hocko)는 리눅스 커널 4.6에 **OOM Reaper (`mm/oom_kill.c`)**를 도입했습니다.

### 2.1 전용 커널 스레드: `oom_reaper`
OOM 킬러가 프로세스에게 `SIGKILL`을 보낼 때, 즉시 `wake_oom_reaper(victim->mm)`를 호출하여 희생자의 메모리 구조체 `struct mm_struct`를 글로벌 리퍼 리스트에 등록하고 전용 커널 스레드 `oom_reaper`를 깨웁니다.

```c
static int oom_reaper(void *unused)
{
    while (true) {
        struct mm_struct *mm = NULL;
        wait_event_freezable(oom_reaper_wait, (mm = get_next_mm_to_reap()));
        oom_reap_task_mm(mm);
    }
}
```

### 2.2 비동기 언맵: `__oom_reap_task_mm()`
`oom_reaper` 스레드는 희생자 프로세스가 무엇을 하고 있든(설령 D-state로 영구히 멈춰 있든) 상관없이, 커널 권한으로 희생자의 페이지 테이블을 직접 털어냅니다:
1. **`down_read_trylock(&mm->mmap_lock)`**:
   - 블록되지 않는 `trylock`을 사용합니다. 만약 프로세스가 쓰기 락을 잡고 있다면 즉시 물러나 나중에 재시도합니다.
2. **`unmap_page_range()`**:
   - 프로세스의 모든 VMA(Virtual Memory Area)를 순회하며, 페이지 테이블 엔트리(PTE)를 해제하고 물리 페이지를 버디 할당자로 즉각 반환합니다.
   - 단, 공유 메모리(Shared Memory)나 `mlock()` 등으로 고정(Pinned)된 페이지는 안전을 위해 건드리지 않고, 오직 **순수 익명 메모리(Anonymous Pages)**만을 강제 회수합니다.
3. **`set_bit(MMF_OOM_SKIP, &mm->flags)`**:
   - 언맵이 끝나면 `MMF_OOM_SKIP` 플래그를 설정합니다.

---

## 3. MMF_OOM_SKIP 플래그의 역할

`MMF_OOM_SKIP`은 커널 메모리 관리자에게 다음과 같은 결정적 사실을 알립니다:
- *"이 프로세스는 이미 OOM 리퍼에 의해 털릴 수 있는 모든 메모리가 털렸다. 더 이상 이 프로세스에게서 쥐어짤 메모리는 없다."*
- 만약 리퍼가 메모리를 회수했음에도 여전히 시스템 메모리가 부족하다면, OOM 킬러는 `MMF_OOM_SKIP`이 찍힌 프로세스를 건너뛰고 **다음 타깃 프로세스를 즉시 선정하여 사살**할 수 있습니다.
- 이로써 D-상태 프로세스 하나 때문에 시스템 전체가 인질로 잡히는 현상이 100% 방지됩니다.

---

## 4. 락 경합 시의 페일세이프 (Fail-Safe)

만약 희생자 프로세스가 `mmap_lock`을 쥐고 있는 상태에서 D-상태에 빠졌다면 어떻게 될까요?
- 리퍼는 `down_read_trylock()`을 시도하지만 실패합니다.
- 리퍼는 일정 간격으로 재시도(`reap_attempts`)를 수행합니다.
- `MAX_OOM_REAP_RETRIES`에 도달하면, 커널은 이 프로세스의 메모리를 언맵하는 것을 공식적으로 포기하고 강제로 `set_bit(MMF_OOM_SKIP, &mm->flags)`를 마킹합니다.
- 이를 통해 OOM 킬러가 다음 희생자를 죽여 시스템 메모리를 확보할 수 있게 길을 열어줍니다.

본 문제는 OOM 킬러와 OOM 리퍼 커널 스레드의 상호작용, D-state 프로세스 언맵, `mmap_lock` trylock 및 `MMF_OOM_SKIP` 전이 동역학을 완벽하게 재현합니다.
