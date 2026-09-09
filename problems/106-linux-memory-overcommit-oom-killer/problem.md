# [CS-106] 서버 메모리가 16GB인데 프로세스들이 64GB를 잡고 있어요?!: Linux 가상 메모리 오버커밋(Overcommit)과 OOM-Killer 희생양 스코어링 (`oom_score_adj`)

> **"선생님! 우리 서버 RAM이 16GB밖에 안 되는데, 프로세스들이 `malloc()`으로 총 64GB를 할당받았는데도 에러가 안 나요! 그런데 왜 새벽에 아무 에러 로그도 없이 가장 중요한 Redis 프로세스가 'Killed'라는 단어 하나만 남기고 죽었을까요?!"**
> 
> 데이터 플랫폼을 운영하는 신입 엔지니어 도현이는 서버 모니터링을 보다가 기겁했습니다.
> 16GB 물리 메모리를 탑재한 인스턴스에서 프로세스들의 가상 메모리(VIRT) 총합이 무려 64GB를 넘고 있었기 때문입니다.
> "메모리가 4배나 뻥튀기되었는데 어떻게 프로세스들이 살아있지?" 하고 신기해하던 그 순간, 회사의 메인 캐시이자 세션 스토리지인 Redis 프로세스가 `Exit Code 137 (SIGKILL)`로 돌연 즉사했습니다.
> 
> 애플리케이션 로그에는 에러 스택트레이스가 단 한 줄도 없었습니다.
> 당황한 도현이에게 인프라 아키텍트는 `dmesg -T` 명령어를 실행하여 커널 로그를 보여주었습니다:
> `Out of memory: Killed process 1420 (redis-server) total-vm:16777216kB, anon-rss:12582912kB, oom_score_adj:0`
> 
> "도현 씨, 항공사가 비행기 좌석 100개에 예약 150명을 받는 '오버부킹'을 하듯, 리눅스 커널도 메모리를 '오버커밋'해요. 하지만 승객이 전부 공항에 나타나면, 기장은 비행기를 띄우기 위해 가장 덩치 큰 승객을 비행기 밖으로 던져버립니다(OOM-Killer)."

---

## 1. 문제 배경과 현실 비유: 비행기 초과 예약(오버부킹)과 승객 강제 퇴출

리눅스 커널은 메모리 활용률을 극대화하기 위해, 실제 물리 RAM보다 더 많은 가상 메모리 할당을 허용하는 **오버커밋(Overcommit)** 정책을 사용합니다.

### 1) 오버커밋 3대 모드 (`/proc/sys/vm/overcommit_memory`)
- **`0` (Heuristic)**: 커널이 직관적으로 너무 큰 요청이 아니면 허용합니다.
- **`1` (Always)**: 물리 메모리 한도와 무관하게 모든 `malloc()` 요청을 무조건 승인합니다 (Redis 권장 모드).
- **`2` (Strict / No Overcommit)**: 다음 공식으로 계산되는 커밋 한도(Commit Limit)를 절대 넘을 수 없으며, 초과 시 `malloc()`이 `ENOMEM`으로 즉시 실패합니다:
  $$	ext{CommitLimit} = 	ext{Swap} + \left(	ext{RAM} 	imes rac{	ext{overcommit\_ratio}}{100}ight)$$

### 2) OOM-Killer의 희생양 선정 알고리즘 (`oom_badness`)
가상 메모리에 실제 데이터 쓰기(Page Touch)가 시작되어 물리 RAM이 고갈(OOM)되면, 커널은 시스템 전체의 크래시(Kernel Panic)를 막기 위해 희생자 프로세스를 골라 강제 살해(`SIGKILL`)합니다.
- **기본 점수 (Base Score)**: 전체 물리 RAM 대비 프로세스의 실제 사용량(RSS) 비율 (0 ~ 1000점)
  $$	ext{base\_score} = \left\lfloor rac{	ext{proc\_rss\_pages}}{	ext{total\_ram\_pages}} 	imes 1000 ightfloor$$
- **관리자 보정치 (`oom_score_adj`)**: `-1000 ~ +1000`
  - `-1000` (OOM_SCORE_ADJ_MIN): **영구 사형 면제(IMMUNE)**. 아무리 메모리를 많이 써도 절대 죽이지 않음 (`sshd`, `systemd` 등).
  - 양수(`+300`, `+1000`): 메모리를 적게 쓰더라도 먼저 사살되는 총알받이 지정.
- **최종 점수**:
  $$	ext{oom\_score} = \min(1000, \max(0, 	ext{base\_score} + 	ext{oom\_score\_adj}))$$
- 면제되지 않은 프로세스 중 `oom_score`가 가장 높은 프로세스에게 `SIGKILL`을 투하하여 메모리를 강제 회수합니다!

---

## 2. 요구사항 및 명령어 사양

당신은 리눅스 커널의 메모리 오버커밋 정책과 OOM-Killer 희생양 스코어링 알고리즘을 시뮬레이션하는 `KernelMemorySimulator` 엔진을 구현해야 합니다.
표준 입력(`stdin`)으로 들어오는 명령어들을 한 줄씩 파싱하여 정확한 형식으로 표준 출력(`stdout`)에 출력하십시오.

### 지원 명령어 목록

1. `INIT_KERNEL <ram_pages> <swap_pages> <mode: 0|1|2> <ratio>`
   - 커널 메모리를 초기화합니다.
   - `commit_limit = swap_pages + (ram_pages * ratio) // 100`
   - 출력: `INIT_KERNEL ram=<ram_pages> swap=<swap_pages> mode=<mode> ratio=<ratio>% commit_limit=<commit_limit>`

2. `SPAWN_PROCESS <pid> <name> <oom_score_adj>`
   - 프로세스를 생성합니다 (`oom_score_adj`: -1000 ~ +1000).
   - 출력: `SPAWN_PROCESS pid=<pid> name=<name> adj=<oom_score_adj>`

3. `SET_OOM_SCORE_ADJ <pid> <new_adj>`
   - 프로세스의 사형 보정치를 변경합니다.
   - 출력: `SET_ADJ pid=<pid> name=<name> old_adj=<old> new_adj=<new_adj>`

4. `MALLOC <pid> <pages>`
   - 프로세스가 가상 메모리 `<pages>` 할당을 요청합니다.
   - Mode 2에서 `total_committed + pages > commit_limit`이면:
     - 출력: `MALLOC_FAILED pid=<pid> requested=<pages> reason=ENOMEM_COMMIT_LIMIT_EXCEEDED commit_limit=<limit> total_committed=<total>`
   - Mode 0에서 `total_committed + pages > ram + swap`이면:
     - 출력: `MALLOC_FAILED pid=<pid> requested=<pages> reason=ENOMEM_HEURISTIC_EXCEEDED`
   - 승인 시:
     - 출력: `MALLOC_OK pid=<pid> pages=<pages> vma=<vma> total_committed=<total>`

5. `TOUCH_PAGES <pid> <pages>`
   - 가상 메모리에 실제 데이터를 기록하여 물리 RAM(RSS)을 소비합니다.
   - 만약 `proc.rss + pages > proc.vma`이면:
     - 출력: `ERROR pid=<pid> reason=TOUCH_EXCEEDS_VMA requested=<pages> vma=<vma> current_rss=<rss>`
   - 물리 메모리 할당 시도:
     - 만약 잔여 물리 RAM(`total_ram - total_resident`)이 충분하면:
       - 출력: `TOUCH_OK pid=<pid> touched=<pages> current_rss=<rss> total_rss=<total_resident>`
     - 잔여 물리 RAM이 부족하면 **OOM_KILLER 발동**:
       - 출력: `OOM_KILLER_INVOKED available_ram=<rem> requested=<pages>`
       - 사형 후보자 선정: 살아있는 프로세스 중 `oom_score_adj == -1000`인 프로세스는 면제(제외).
       - 후보가 아무도 없으면:
         - 출력: `KERNEL_PANIC reason=OUT_OF_MEMORY_NO_KILLABLE_PROCESS`
       - 최고점 프로세스(동점 시 PID 큰 순서)를 희생양으로 사살하여 메모리 회수:
         - 출력: `OOM_KILL victim_pid=<victim.pid> name=<victim.name> rss_pages=<freed_rss> oom_score=<score>`
       - 만약 사살된 프로세스가 본인(`pid == victim.pid`)이면 작업 중단:
         - 출력: `TOUCH_ABORTED pid=<pid> reason=PROCESS_KILLED_BY_OOM`
       - 타 프로세스가 사살되어 메모리가 확보되었으면 계속해서 `TOUCH` 시도.

6. `STATS`
   - 커널 및 프로세스 전체 상태를 출력합니다.
   - 출력 형식:
     - `STATS total_ram=<ram> total_rss=<rss> total_committed=<committed> commit_limit=<limit>`
     - (PID 오름차순으로 각 프로세스 한 줄씩)
       - 생존 시: `PROC pid=<pid> name=<name> vma=<vma> rss=<rss> adj=<adj> oom_score=<score|IMMUNE> status=ALIVE`
       - 사망 시: `PROC pid=<pid> name=<name> status=DEAD`

---

## 3. 입출력 예시

### 예시 입력 1
```text
INIT_KERNEL 1000 200 1 50
SPAWN_PROCESS 1 sshd -1000
SPAWN_PROCESS 2 redis 0
SPAWN_PROCESS 3 batch_worker 300
MALLOC 1 200
MALLOC 2 600
MALLOC 3 400
TOUCH_PAGES 1 100
TOUCH_PAGES 2 500
TOUCH_PAGES 3 300
STATS
SPAWN_PROCESS 4 web_app 0
MALLOC 4 200
TOUCH_PAGES 4 200
STATS
```

### 예시 출력 1
```text
INIT_KERNEL ram=1000 swap=200 mode=1 ratio=50% commit_limit=700
SPAWN_PROCESS pid=1 name=sshd adj=-1000
SPAWN_PROCESS pid=2 name=redis adj=0
SPAWN_PROCESS pid=3 name=batch_worker adj=300
MALLOC_OK pid=1 pages=200 vma=200 total_committed=200
MALLOC_OK pid=2 pages=600 vma=600 total_committed=800
MALLOC_OK pid=3 pages=400 vma=400 total_committed=1200
TOUCH_OK pid=1 touched=100 current_rss=100 total_rss=100
TOUCH_OK pid=2 touched=500 current_rss=500 total_rss=600
TOUCH_OK pid=3 touched=300 current_rss=300 total_rss=900
STATS total_ram=1000 total_rss=900 total_committed=1200 commit_limit=700
PROC pid=1 name=sshd vma=200 rss=100 adj=-1000 oom_score=IMMUNE status=ALIVE
PROC pid=2 name=redis vma=600 rss=500 adj=0 oom_score=500 status=ALIVE
PROC pid=3 name=batch_worker vma=400 rss=300 adj=300 oom_score=600 status=ALIVE
SPAWN_PROCESS pid=4 name=web_app adj=0
MALLOC_OK pid=4 pages=200 vma=200 total_committed=1400
OOM_KILLER_INVOKED available_ram=100 requested=200
OOM_KILL victim_pid=3 name=batch_worker rss_pages=300 oom_score=600
TOUCH_OK pid=4 touched=200 current_rss=200 total_rss=800
STATS total_ram=1000 total_rss=800 total_committed=1000 commit_limit=700
PROC pid=1 name=sshd vma=200 rss=100 adj=-1000 oom_score=IMMUNE status=ALIVE
PROC pid=2 name=redis vma=600 rss=500 adj=0 oom_score=500 status=ALIVE
PROC pid=3 name=batch_worker status=DEAD
PROC pid=4 name=web_app vma=200 rss=200 adj=0 oom_score=200 status=ALIVE
```

---

## 4. 실무 핵심 요약 (Architecture Takeaway)

1. **DB/캐시 데몬의 `oom_score_adj` 사형 면제 설정**:
   - MySQL, Redis, PostgreSQL 등 핵심 스토리지는 메모리 점유율이 높아 OOM-Killer의 1순위 표적이 되기 쉽습니다.
   - `systemd` 서비스 파일에 `OOMScoreAdjust=-1000`을 명시하여 시스템 위기 시에도 절대 사살되지 않도록 보호해야 합니다.
2. **배치/분석 작업의 총알받이 우선순위 지정**:
   - 무거운 분석 스크립트나 배치 컨슈머에 `OOMScoreAdjust=500`을 부여하여, 메모리 압박 시 핵심 웹서버 대신 배치가 안전하게 먼저 희생되도록 유도합니다.
3. **Strict Overcommit (`vm.overcommit_memory = 2`)의 활용**:
   - 금융권이나 미션 크리티컬 시스템에서는 임의의 프로세스가 살해당하는 재앙을 막기 위해, 오버커밋을 엄격히 제한하고 `malloc()` 단계에서 거부되도록 설정합니다.
