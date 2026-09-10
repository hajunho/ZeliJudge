# #375 - 리눅스 커널 OOM Reaper: D-상태 프로세스 비동기 익명 메모리 회수 & MMF_OOM_SKIP 엔진

## 📖 문제 배경과 시스템 아키텍처

> *"전통적인 리눅스 OOM 킬러는 희생자 프로세스(Victim Task)에게 SIGKILL을 보낸 뒤, 해당 프로세스가 시그널을 처리하고 스스로 `exit_mmap()`을 호출하여 메모리를 반환하기만을 하염없이 기다렸습니다. 그러나 희생자가 응답 없는 NFS I/O나 드라이버 데드락으로 인해 인터럽트 불가능한 대기 상태(`TASK_UNINTERRUPTIBLE` / `D` 상태)에 갇혀 있거나 `mmap_lock`을 쥐고 잠들어 있다면, 메모리는 영원히 반환되지 않고 시스템 전체가 영구 동결(OOM Deadlock)에 빠집니다. 리눅스 4.6에 도입된 **OOM Reaper (`mm/oom_kill.c`, `mm/mmap.c`)**는 전용 커널 스레드를 통해 희생자 프로세스의 발밑에서 비동기적으로 익명 메모리를 강제 언맵(`unmap_page_range`)하여 즉시 회수하고 `MMF_OOM_SKIP`을 마킹함으로써 이 악몽을 종식시켰습니다."*  
> — **Michal Hocko, Linux Kernel Memory Management Maintainer**

대규모 클라우드 및 프로덕션 서버에서 발생하는 가장 치명적인 커널 장애 중 하나는 **OOM 데드락(OOM Liveloop / Hang)**입니다. 메모리가 고갈되어 OOM 킬러가 최악의 프로세스를 사살 대상으로 지목했음에도 불구하고, 해당 프로세스가 I/O 대기(D-state)에 걸려 있거나 락 경합으로 인해 종료되지 못하면, 다른 메모리 할당 스레드들은 OOM 희생자가 죽기만을 기다리며 `schedule_timeout_killable()`에서 무한히 대기하다 커널 패닉에 이릅니다.

리눅스 커널의 **OOM Reaper (`mm/oom_kill.c`)**는 이 문제를 해결하기 위해 다음과 같은 비동기 강제 회수 메커니즘을 작동시킵니다:

```
+-------------------------------------------------------------------------------+
|                       리눅스 커널 OOM Reaper 데이터 흐름                      |
+-------------------------------------------------------------------------------+
  [Memory Watermark Breach: free_pages < min_watermark]
         │
         ▼
  [out_of_memory() -> select_bad_process()]
         │
         ├───► MMF_OOM_SKIP 마킹된 태스크 무시
         └───► 최악의 badness()를 가진 victim 선정 -> SIGKILL 발송
                   │
                   ▼
  [wake_oom_reaper()]
         │
         ├───► victim->mm 을 oom_reaper_list 큐에 등록
         └───► oom_reaper 전용 커널 스레드 기상!
                   │
                   ▼
  [oom_reaper 커널 스레드: __oom_reap_task_mm()]
         │
         ├───► down_read_trylock(&mm->mmap_lock) 시도
         │        │
         │        ├─ 실패 (락 경합 중):
         │        │    retry 카운터 증가 -> 한도 초과 시 MMF_OOM_SKIP 강제 설정!
         │        │
         │        └─ 성공:
         │             unmap_page_range() 호출
         │             • 익명 메모리(anon_pages) 중 mlock 고정(pinned)을 제외한
         │               모든 페이지를 페이지 테이블에서 강제 언맵
         │             • 버디 할당자(Buddy Allocator)로 즉각 free_pages 반환!
         │             • set_bit(MMF_OOM_SKIP, &mm->flags) 마킹!
         ▼
  [새로운 할당 요청 즉시 성공 & OOM 데드락 완전 회피!]
```

### OOM Reaper의 핵심 불변식
1. **희생자 선별과 MMF_OOM_SKIP**:
   - OOM 킬러는 `mmf_oom_skip` 비트가 설정된 프로세스는 이미 회수되었거나 가망이 없는 프로세스로 간주하여 완전히 무시하고 다음 후보를 물색합니다.
2. **비동기 메모리 언맵 (`unmap_page_range`)**:
   - 희생자 프로세스가 깨어나지 못해도, OOM 리퍼 스레드가 `down_read_trylock(&mm->mmap_lock)`에 성공하면 익명 비고정 메모리(`anon_pages - pinned_pages`)를 물리 페이지 프레임으로 즉시 회수합니다.
3. **락 경합 시 안전한 포기 (Safe Bailout)**:
   - 희생자 프로세스가 `mmap_lock` 쓰기 락을 쥐고 있는 경우 리퍼는 무리하게 블록되지 않고 `trylock` 실패 후 재시도하며, 최대 재시도 한도(`max_reap_retries`)를 초과하면 데드락 방지를 위해 `MMF_OOM_SKIP`을 강제로 찍고 다음 타깃으로 넘어갑니다.

---

## 📥 입력 형식 (Input Specification)

입력은 표준 입력(Standard Input)으로 단일 JSON 객체가 주어집니다:

```json
{
  "config": {
    "min_watermark_pages": 500,
    "max_reap_retries": 2,
    "initial_free_pages": 600
  },
  "tasks": [
    {
      "pid": 101,
      "name": "leaky_db",
      "anon_pages": 400,
      "file_pages": 50,
      "pinned_pages": 20,
      "state": "UNINTERRUPTIBLE_D_STATE",
      "holds_mmap_lock_write": false
    },
    {
      "pid": 102,
      "name": "web_worker",
      "anon_pages": 150,
      "file_pages": 30,
      "pinned_pages": 0,
      "state": "RUNNING",
      "holds_mmap_lock_write": false
    }
  ],
  "operations": [
    {
      "type": "MEM_ALLOC",
      "pid": 102,
      "pages": 150
    },
    {
      "type": "REAPER_STEP"
    }
  ]
}
```

### 제약조건 및 파라미터 규칙:
1. `config`:
   - `min_watermark_pages`: OOM 유발 임계 여유 페이지 수 (기본값 `500`).
   - `max_reap_retries`: 락 경합 시 최대 리퍼 재시도 횟수 (기본값 `3`).
   - `initial_free_pages`: 초기 시스템 여유 페이지 수 (기본값 `1000`).
2. `tasks`:
   - `pid`: 고유 프로세스 ID (정수).
   - `name`: 프로세스 명칭.
   - `anon_pages`: 익명 메모리 페이지 수 (양의 정수).
   - `file_pages`: 파일 매핑 페이지 수 (양의 정수).
   - `pinned_pages`: mlock/고정되어 언맵 불가능한 페이지 수 (양의 정수, `pinned_pages <= anon_pages`).
   - `oom_score_adj`: OOM 점수 조정치 (정수, 기본값 `0`).
   - `state`: 태스크 상태 (`"RUNNING"`, `"SLEEPING"`, `"UNINTERRUPTIBLE_D_STATE"`, `"DEAD"`).
   - `holds_mmap_lock_write`: 현재 `mmap_lock` 쓰기 락 보유 여부 (불리언).
3. `operations`:
   - `MEM_ALLOC`:
     - 파라미터: `pid`, `pages`.
     - 동작: `free_pages - pages < min_watermark_pages`이면 워터마크 침범으로 OOM 킬러가 즉각 격발됩니다. 그렇지 않으면 `free_pages -= pages`, `task.anon_pages += pages`.
   - `TRIGGER_OOM`:
     - 수동 OOM 호출. `!mmf_oom_skip` 및 `state != "DEAD"`인 태스크 중 `badness = anon + file + oom_score_adj`가 최대인 태스크를 희생자로 선정하고 리퍼 큐에 등록합니다.
   - `REAPER_STEP`:
     - 리퍼 스레드가 큐의 선두 태스크를 꺼내 처리를 시도합니다.
     - `holds_mmap_lock_write == true`: `trylock` 실패. 재시도 횟수 증가. `attempts >= max_reap_retries`이면 `MMF_OOM_SKIP` 강제 설정 후 큐에서 제거. 아니면 큐 후미에 재등록.
     - `holds_mmap_lock_write == false`: 리핑 성공! `reapable = anon_pages - pinned_pages`만큼 언맵하여 `free_pages += reapable`, `task.anon_pages = task.pinned_pages`, `task.mmf_oom_skip = true` 설정 후 큐에서 제거.
   - `LOCK_ACQUIRE` / `LOCK_RELEASE`:
     - 대상 태스크의 `holds_mmap_lock_write`를 `true`/`false`로 변경.
   - `TASK_STATE_CHANGE`:
     - 대상 태스크의 `state` 변경.
   - `TASK_EXIT`:
     - 대상 태스크가 정상 종료를 시도합니다. `state != "UNINTERRUPTIBLE_D_STATE"`이면 남은 모든 페이지(`anon + file`)를 반환하고 `state = "DEAD"`, `mmf_oom_skip = true`가 됩니다. D-state이면 종료가 블록됩니다.

---

## 📤 출력 형식 (Output Specification)

시뮬레이션 완료 후 최종 시스템 상태를 압축 JSON(`separators=(',', ':')`, `ensure_ascii=False`)으로 출력합니다:

```json
{
  "final_free_pages": 980,
  "reaper_queue_remaining": 0,
  "tasks": {
    "101": {
      "name": "leaky_db",
      "state": "UNINTERRUPTIBLE_D_STATE",
      "anon_pages": 20,
      "file_pages": 50,
      "pinned_pages": 20,
      "is_oom_victim": true,
      "mmf_oom_skip": true,
      "reap_attempts": 0,
      "reaped_pages_total": 380
    },
    "102": {
      "name": "web_worker",
      "state": "RUNNING",
      "anon_pages": 150,
      "file_pages": 30,
      "pinned_pages": 0,
      "is_oom_victim": false,
      "mmf_oom_skip": false,
      "reap_attempts": 0,
      "reaped_pages_total": 0
    }
  },
  "events": [
    {
      "type": "WATERMARK_BREACH",
      "pid": 102,
      "requested": 150,
      "free_pages": 600,
      "watermark": 500
    },
    {
      "type": "OOM_KILL_SELECTED",
      "victim_pid": 101,
      "victim_name": "leaky_db",
      "badness_score": 450,
      "free_pages": 600
    },
    {
      "type": "OOM_REAP_SUCCESS",
      "pid": 101,
      "reaped_pages": 380,
      "remaining_anon": 20,
      "free_pages_now": 980,
      "status": "MMF_OOM_SKIP_SET"
    }
  ]
}
```

---

## 🎯 채점 기준 및 제약 조건

1. 정확성 100%: 8개 모든 테스트케이스의 여유 페이지 및 프로세스 상태가 완벽히 일치해야 합니다.
2. D-상태 프로세스의 정상 종료 불가와 리퍼의 비동기 언맵 동작이 정확히 모사되어야 합니다.
3. `mmf_oom_skip` 설정에 따른 OOM 재선정 배제 로직을 철저히 검증합니다.
