# 리눅스 커널 Cgroup v2 메모리 컨트롤러 memory.max 스로틀링 및 OOM 킬러 배드니스 휴리스틱 엔진 (Linux Kernel Memcg OOM Killer Engine)

## 문제 설명

리눅스 커널 컨테이너 환경(Docker, Kubernetes, systemd slice)에서 여러 워크로드가 단일 물리 노드의 메모리를 공유할 때, 특정 컨테이너의 메모리 누수(Memory Leak)나 과도한 소비가 전체 시스템 패닉을 초래하지 않도록 격리(Isolation)하는 핵심 서브시스템이 바로 **Cgroup v2 Memory Controller (`mm/memcontrol.c`)**와 **OOM 킬러 (`mm/oom_kill.c`)**입니다.

과거 Cgroup v1에서는 다중 계층 트리 구조의 복잡성과 회수(Reclaim) 비효율성으로 인해 경합 문제가 심각했으나, Cgroup v2에서는 단일 통합 계층 구조(Unified Hierarchy)와 4계층 워터마크 보호 모델을 도입하여 세밀한 메모리 QoS(Quality of Service) 제어를 지원합니다.

```
+---------------------------------------------------------------------------------+
|               Linux Cgroup v2 Memory Controller & OOM Subsystem                 |
+---------------------------------------------------------------------------------+
| [Root Cgroup: /sys/fs/cgroup]  (Total Host Memory: 16384 MB)                    |
|   |                                                                             |
|   +---> /system.slice (systemd, sshd, journald - oom_score_adj: -1000)          |
|   |                                                                             |
|   +---> /workload.slice                                                         |
|           |                                                                     |
|           +---> /workload/web   (memory.high: 4000, memory.max: 5000)           |
|           +---> /workload/db    (memory.high: 4000, memory.max: 5000)           |
+---------------------------------------------------------------------------------+
                                         |
                       [ Memory Allocation: alloc_pages() ]
                                         |
                                         v
               +---------------------------------------------------+
               |  Cgroup Usage + Alloc > memory.high?              |
               +---------------------------------------------------+
                       | YES                                | NO
                       v                                    |
            [ MEMCG_HIGH_THROTTLE ]                         |
            (비동기 지연 & 스로틀링 알림 로깅)              |
                       |                                    |
                       +-----------------+------------------+
                                         |
                                         v
               +---------------------------------------------------+
               |  Cgroup Usage + Alloc > memory.max?               |
               +---------------------------------------------------+
                       | YES                                | NO
                       v                                    |
           [ Direct Reclaim 시도 ]                          v
           - Page Cache (rss_file) 먼저 회수        [ Charge & Commit ]
                       |                                    ^
        여전히 > max?  v                                    |
               +-----------------------------------+        |
               | memcg OOM Killer 발동             |        |
               | - oom_badness() 계산              |        |
               | - oom_score_adj 가중치 반영       |        |
               | - 희생자 선정 및 SIGKILL 전송     |--------+ (메모리 확보 후 재시도)
               | - 확보 실패 시 OOM_ENOMEM 반환    |
               +-----------------------------------+
```

### 1. Cgroup v2 메모리 임계치 및 회수 워터마크
1. **`memory.high`**: 소프트 제한선. 이를 초과하면 프로세스를 강제 종료(Kill)하지 않고, 스로틀링(Throttling/Delay) 이벤트를 기록하여 백그라운드 회수를 유도합니다.
2. **`memory.max`**: 하드 제한선. 이를 초과하려 할 경우 커널은 즉시 직접 회수(**Direct Reclaim**)를 수행하여 클린 파일 캐시(`rss_file`)를 메모리에서 해제합니다.
3. **OOM Killer 트리거**: 직접 회수를 거친 후에도 메모리가 부족할 경우, 해당 cgroup 서브트리 범위 내에서 **OOM Killer**를 호출하여 최적의 희생자 프로세스를 선정하고 강제 종료시킵니다.

### 2. OOM Badness 휴리스틱 계산 공식 (`mm/oom_kill.c`)
각 프로세스 $t$의 위험도 지수(`badness`)는 다음과 같이 계산됩니다:
1. **면제 프로세스**: `oom_score_adj <= -1000` 인 경우, 배드니스는 즉시 `0`이 되며 OOM 킬러 대상에서 절대적으로 제외됩니다 (`KILLED_NEVER`).
2. **일반 프로세스**:
   $$	ext{points} = 	ext{rss\_anon} + 	ext{rss\_file} + 	ext{swap}$$
   $$	ext{adj\_points} = rac{	ext{oom\_score\_adj} 	imes 	ext{total\_memory}}{1000.0}$$
   $$	ext{badness} = \max(1, \lfloor 	ext{points} + 	ext{adj\_points} floor)$$
3. **희생자 선정 우선순위**:
   - `badness`가 가장 큰 프로세스 (내림차순)
   - badness 동점 시: `rss_anon`이 큰 프로세스 (내림차순)
   - RSS 동점 시: `pid`가 작은 프로세스 (오름차순, Linux 커널의 결정론적 타이 브레이킹)
4. **처형 및 회수**:
   - 선정된 희생자는 `alive = False` 처리되고, 점유하고 있던 모든 익명 및 파일 메모리가 상위 계층까지 즉시 언차징(Uncharge) 및 환원됩니다.
   - cgroup 내 모든 프로세스가 면제(`-1000`)이거나 이미 사망하여 희생자를 찾지 못하면 할당 작업은 `{"status": "OOM_ENOMEM"}`으로 실패합니다.

---

## 입력 및 출력 형식

### 입력 형식 (JSON)
표준 입력(stdin)으로 단일 JSON 객체가 주어집니다:
```json
{
  "config": {
    "total_memory": 16384,
    "cgroups": [
      {
        "path": "/workload",
        "parent": "root",
        "memory_high": 10000,
        "memory_max": 12000
      },
      {
        "path": "/workload/web",
        "parent": "/workload",
        "memory_high": 4000,
        "memory_max": 5000
      }
    ]
  },
  "operations": [
    {"op": "ADD_TASK", "pid": 101, "cgroup": "/workload/web", "oom_score_adj": 0},
    {"op": "ALLOC", "pid": 101, "amount": 2500, "is_anon": true},
    {"op": "FREE", "pid": 101, "amount": 500, "is_anon": true},
    {"op": "SET_OOM_SCORE_ADJ", "pid": 101, "oom_score_adj": -200}
  ]
}
```

### 지원 연산 (`operations`)
1. **`ADD_TASK`**:
   - `{"op": "ADD_TASK", "pid": 101, "cgroup": "/path", "oom_score_adj": 0}`
2. **`ALLOC`**:
   - `{"op": "ALLOC", "pid": 101, "amount": 1000, "is_anon": true}`
   - `is_anon`: `true`이면 익명 메모리(`rss_anon`), `false`이면 파일 백업 캐시(`rss_file`).
3. **`FREE`**:
   - `{"op": "FREE", "pid": 101, "amount": 500, "is_anon": true}`
4. **`SET_OOM_SCORE_ADJ`**:
   - `{"op": "SET_OOM_SCORE_ADJ", "pid": 101, "oom_score_adj": 300}`

### 출력 형식 (JSON)
표준 출력(stdout)으로 공백 없는 단일 행 압축 JSON을 출력합니다:
```json
{
  "stats": {
    "allocations": 10,
    "throttles": 2,
    "reclaims": 1,
    "reclaimed_pages": 500,
    "oom_kills": 1,
    "pages_reaped": 2500
  },
  "cgroups": {
    "/workload": {
      "usage": 2000,
      "rss_anon": 2000,
      "rss_file": 0,
      "oom_events": 0,
      "throttle_events": 0,
      "reclaim_events": 0
    }
  },
  "tasks": {
    "101": {
      "alive": true,
      "cgroup": "/workload/web",
      "rss_anon": 2000,
      "rss_file": 0,
      "oom_score_adj": 0,
      "badness": 2000
    }
  },
  "history": [...],
  "event_log": [...]
}
```
