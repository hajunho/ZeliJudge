# Problem #086: 새벽 3시 백업만 돌면 Redis가 왜 죽어요?!: Linux fork(), Copy-On-Write (COW)와 메모리 폭증(Memory Spike)

## 1. 문제 설명
글로벌 전자상거래 서비스의 메인 백엔드 엔지니어인 당신은 기이한 장애 보고를 받았습니다.  
새벽 3시마다 트래픽이 주간의 절반 이하로 떨어지는데도, Redis 캐시 서버 컨테이너가 아무런 에러 로그도 없이 갑자기 강제 종료(`SIGKILL`)된다는 것입니다.

시스템 커널 로그(`dmesg`)를 분석한 결과, 범인은 바로 Linux 커널의 **OOM Killer (Out-of-Memory Killer)** 였습니다!  
새벽 3시에 실행된 백그라운드 데이터 스냅샷(`BGSAVE`) 작업 도중, **Linux `fork()` 시스템 콜과 Copy-On-Write (COW) 메커니즘**으로 인해 물리 메모리가 순식간에 시스템 가용한도를 초과해 폭증(Memory Spike)한 것이었습니다.

당신은 Redis의 `fork()` 기반 BGSAVE와 Linux 가상 메모리 페이지 관리 메커니즘을 정밀하게 모사하는 **COW 메모리 스파이크 시뮬레이터**를 구현하여 장애를 진단하고 시스템 안전성을 검증해야 합니다.

---

## 2. 시스템 동작 규칙

### (1) 메모리 모델 및 초기 상태
- 가상 메모리는 고정 크기의 페이지(Page) 단위로 관리됩니다. 페이지 크기는 `PAGE_SIZE_KB` (예: 표준 4KB 또는 Transparent HugePage 2048KB/2MB)입니다.
- 프로세스는 초기 `INITIAL_PAGES`개의 페이지(`P0, P1, ..., P(INITIAL_PAGES - 1)`)를 할당받아 보유합니다.
- 초기 물리 메모리 사용량: $\text{INITIAL\_MEM\_KB} = \text{INITIAL\_PAGES} \times \text{PAGE\_SIZE\_KB}$.
- 초기 상태에서 모든 페이지는 부모 프로세스 전용인 `PRIVATE` 상태입니다.
- 시스템 전체 물리 메모리 한계는 `TOTAL_SYSTEM_RAM_KB`입니다.

---

### (2) 액션 명세

1. `BGSAVE_START`:
   - Redis 메인 프로세스가 `fork()`를 호출하여 자식 프로세스를 생성합니다.
   - 현재 부모가 보유한 모든 페이지는 `COW_SHARED` 상태로 전환되어 부모와 자식이 동일한 물리 메모리 프레임을 공유합니다.
   - 공유되므로 이 시점의 **추가 물리 메모리 증가는 0 KB**입니다.
   - 이미 BGSAVE가 실행 중인 상태(`active_bgsave == True`)에서 다시 호출되면 오류를 출력합니다:
     `ACT <idx> BGSAVE_START ERROR:BGSAVE_ALREADY_IN_PROGRESS TOTAL_MEM_KB:<total_mem>`
   - 정상 시작 시:
     `ACT <idx> BGSAVE_START SHARED_PAGES:<cnt> TOTAL_MEM_KB:<total_mem>`
     (여기서 `<cnt>`는 공유된 페이지 수)

2. `READ <page_id>`:
   - 지정된 페이지(`P<id>`)를 읽습니다.
   - 읽기 작업은 데이터 수정을 가하지 않으므로, 페이지가 `COW_SHARED` 상태이든 `PRIVATE` 상태이든 **페이지 복제를 유발하지 않습니다 (`COW_FAULT:FALSE`)**.
   - 해당 `page_id`가 존재하지 않는 경우:
     `ACT <idx> READ P<id> ERROR:PAGE_NOT_FOUND TOTAL_MEM_KB:<total_mem>`
   - 정상 읽기 시:
     `ACT <idx> READ P<id> COW_FAULT:FALSE TOTAL_MEM_KB:<total_mem>`

3. `WRITE <page_id>`:
   - 지정된 페이지(`P<id>`)에 데이터를 씁니다.
   - 해당 `page_id`가 존재하지 않는 경우:
     `ACT <idx> WRITE P<id> ERROR:PAGE_NOT_FOUND TOTAL_MEM_KB:<total_mem>`
   - 존재하는 페이지인 경우:
     - 만약 **BGSAVE가 활성 중이고 해당 페이지가 `COW_SHARED` 상태라면**:
       - **하드웨어 페이지 폴트가 발생 (`COW_FAULT:TRUE`)**합니다!
       - OS 커널이 새 물리 페이지를 할당하여 원본 데이터를 복제합니다.
       - 물리 메모리 사용량이 `PAGE_SIZE_KB` 만큼 증가합니다.
       - 해당 페이지는 부모 전용인 `PRIVATE` 상태로 전환됩니다.
       - 만약 이번 쓰기로 인해 `TOTAL_MEM_KB > TOTAL_SYSTEM_RAM_KB`가 되면 즉시 `[OOM_KILLER_TRIGGERED]` 경보 플래그가 붙습니다:
         `ACT <idx> WRITE P<id> COW_FAULT:TRUE STATUS:DIRTY_COPIED MEM_INC_KB:+<page_size> TOTAL_MEM_KB:<total_mem> [OOM_KILLER_TRIGGERED]`
       - 한도 내라면:
         `ACT <idx> WRITE P<id> COW_FAULT:TRUE STATUS:DIRTY_COPIED MEM_INC_KB:+<page_size> TOTAL_MEM_KB:<total_mem>`
     - 만약 BGSAVE가 비활성 상태이거나 이미 `PRIVATE` 상태인 페이지라면:
       - 페이지 폴트나 복제 없이 기존 물리 프레임에 덮어씁니다:
         `ACT <idx> WRITE P<id> COW_FAULT:FALSE STATUS:ALREADY_PRIVATE MEM_INC_KB:0 TOTAL_MEM_KB:<total_mem>`

4. `ALLOC <page_id>`:
   - 새로운 가상 메모리 페이지를 동적으로 할당합니다.
   - 이미 존재하는 `page_id`라면 오류를 출력합니다:
     `ACT <idx> ALLOC P<id> ERROR:ALREADY_ALLOCATED TOTAL_MEM_KB:<total_mem>`
   - 새 페이지인 경우:
     - 1개의 새로운 물리 프레임이 할당되어 물리 메모리가 `PAGE_SIZE_KB`만큼 증가합니다.
     - 페이지 상태는 `PRIVATE`입니다.
     - 메모리 한도 초과 시:
       `ACT <idx> ALLOC P<id> STATUS:ALLOCATED MEM_INC_KB:+<page_size> TOTAL_MEM_KB:<total_mem> [OOM_KILLER_TRIGGERED]`
     - 한도 내라면:
       `ACT <idx> ALLOC P<id> STATUS:ALLOCATED MEM_INC_KB:+<page_size> TOTAL_MEM_KB:<total_mem>`

5. `BGSAVE_FINISH`:
   - 자식 프로세스가 디스크 덤프를 완료하고 종료(`exit()`)합니다.
   - BGSAVE가 활성화되어 있지 않다면 오류를 출력합니다:
     `ACT <idx> BGSAVE_FINISH ERROR:NO_ACTIVE_BGSAVE TOTAL_MEM_KB:<total_mem>`
   - 정상 종료 시:
     - 자식 프로세스가 소멸하면서 자식이 붙잡고 있던 원본 스냅샷 프레임들이 해제됩니다.
     - 해제되는 물리 메모리: $\text{RELEASED\_KB} = (\text{해당 세션에서 복제된 오염 페이지 수}) \times \text{PAGE\_SIZE\_KB}$.
     - 총 물리 메모리 사용량이 $\text{RELEASED\_KB}$ 만큼 감소합니다.
     - 아직 복제되지 않고 `COW_SHARED`로 남아있던 페이지들은 모두 `PRIVATE` 상태로 복귀합니다.
     - 오염 비율 계산: $\text{DIRTY\_RATIO} = (\text{오염 페이지 수} / \text{세션 시작 시 공유 페이지 수} \times 100.0)\%$. (공유 페이지 수가 0이면 0.0%)
     - 출력:
       `ACT <idx> BGSAVE_FINISH DIRTY_PAGES:<dirty_cnt>/<shared_cnt> (<dirty_ratio:.1f>%) RELEASED_KB:<released_kb> TOTAL_MEM_KB:<total_mem>`

---

## 3. 입력 형식

```text
SYSTEM_CONFIG
PAGE_SIZE_KB <int>
TOTAL_SYSTEM_RAM_KB <int>
INITIAL_PAGES <int>
ACTIONS
<ACTION_1>
<ACTION_2>
...
```

- `PAGE_SIZE_KB`: 페이지 크기 (단위: KB, 예: 4 또는 2048)
- `TOTAL_SYSTEM_RAM_KB`: 서버 가용 물리 메모리 한계 (단위: KB)
- `INITIAL_PAGES`: 부모 초기 점유 페이지 수 (ID는 `P0` ~ `P(INITIAL_PAGES-1)`)
- `ACTIONS` 아래 각 줄마다 액션 명령어가 주어집니다.

---

## 4. 출력 형식

각 액션마다 `ACT <act_idx> ...` 형식으로 한 줄씩 결과를 출력합니다 (`act_idx`는 1부터 시작).  
모든 액션이 완료된 후 다음과 같이 `SUMMARY` 통계를 출력합니다:

```text
SUMMARY TOTAL_ACTIONS:<cnt>
SUMMARY TOTAL_BGSAVE_SESSIONS:<cnt>
SUMMARY TOTAL_COW_FAULTS:<cnt>
SUMMARY INITIAL_MEM_KB:<initial_kb>
SUMMARY PEAK_MEM_KB:<peak_kb> (SYSTEM_LIMIT_KB:<limit_kb>)
SUMMARY MEMORY_SPIKE_RATIO:<ratio:.2f>x
SUMMARY OOM_INCIDENT: <OOM_STATUS>
```

- `<ratio>`: `PEAK_MEM_KB / INITIAL_MEM_KB` (소수점 둘째 자리까지 출력, INITIAL_MEM_KB가 0이면 1.00)
- `<OOM_STATUS>`:
  - OOM이 한 번도 발생하지 않은 경우: `NONE`
  - 발생한 경우: `OOM_KILLER_INVOKED (MAX_EXCESS_KB:<excess_kb>)`
    (여기서 `<excess_kb>`는 피크 메모리가 시스템 한계를 초과한 최대 크기 `PEAK_MEM_KB - TOTAL_SYSTEM_RAM_KB`)

---

## 5. 입출력 예시

### 예시 입력 1
```text
SYSTEM_CONFIG
PAGE_SIZE_KB 4
TOTAL_SYSTEM_RAM_KB 48
INITIAL_PAGES 10
ACTIONS
BGSAVE_START
READ 0
WRITE 0
WRITE 0
WRITE 1
WRITE 2
BGSAVE_FINISH
```

### 예시 출력 1
```text
ACT 1 BGSAVE_START SHARED_PAGES:10 TOTAL_MEM_KB:40
ACT 2 READ P0 COW_FAULT:FALSE TOTAL_MEM_KB:40
ACT 3 WRITE P0 COW_FAULT:TRUE STATUS:DIRTY_COPIED MEM_INC_KB:+4 TOTAL_MEM_KB:44
ACT 4 WRITE P0 COW_FAULT:FALSE STATUS:ALREADY_PRIVATE MEM_INC_KB:0 TOTAL_MEM_KB:44
ACT 5 WRITE P1 COW_FAULT:TRUE STATUS:DIRTY_COPIED MEM_INC_KB:+4 TOTAL_MEM_KB:48
ACT 6 WRITE P2 COW_FAULT:TRUE STATUS:DIRTY_COPIED MEM_INC_KB:+4 TOTAL_MEM_KB:52 [OOM_KILLER_TRIGGERED]
ACT 7 BGSAVE_FINISH DIRTY_PAGES:3/10 (30.0%) RELEASED_KB:12 TOTAL_MEM_KB:40
SUMMARY TOTAL_ACTIONS:7
SUMMARY TOTAL_BGSAVE_SESSIONS:1
SUMMARY TOTAL_COW_FAULTS:3
SUMMARY INITIAL_MEM_KB:40
SUMMARY PEAK_MEM_KB:52 (SYSTEM_LIMIT_KB:48)
SUMMARY MEMORY_SPIKE_RATIO:1.30x
SUMMARY OOM_INCIDENT: OOM_KILLER_INVOKED (MAX_EXCESS_KB:4)
```
