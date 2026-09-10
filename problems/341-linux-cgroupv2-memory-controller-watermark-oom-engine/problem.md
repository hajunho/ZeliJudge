# 리눅스 커널 Cgroup v2 계층적 메모리 컨트롤러(memcg) 워터마크 회수 및 OOM 킬러 엔진

## 문제 설명

현대 클라우드 네이티브 인프라(Kubernetes, Docker, systemd, containerd)에서 모든 컨테이너와 시스템 서비스는 리눅스 커널의 **Control Groups v2 (cgroup v2)**를 통해 자원을 엄격히 격리하고 통제받습니다. 과거 cgroup v1이 서브시스템 간 계층 불일치와 모호한 OOM 동작으로 비판받았던 것과 달리, cgroup v2는 **단일 통일 계층 구조(Single Unified Hierarchy)** 위에서 작동하며 고도로 정교한 **메모리 워터마크(Watermark) 제어 모델**을 제공합니다.

cgroup v2 메모리 컨트롤러(`mm/memcontrol.c`)의 핵심 4대 워터마크와 동작 규칙은 다음과 같습니다:

1. **`memory.min` (하드 보장/보호)**:
   어떠한 시스템 메모리 압박 상황에서도 절대 회수되지 않는 최우선 보호 메모리 한계선입니다.
2. **`memory.low` (소프트 보호/최선 노력)**:
   다른 할당되지 않은 메모리로 시스템 수요를 충당할 수 있는 한 회수되지 않으며, 비보호 메모리가 고갈되었을 때만 비례 회수됩니다.
3. **`memory.high` (비동기 스로틀링/조절 한계선)**:
   메모리 사용량이 이 임계치를 초과하면 프로세스는 즉시 OOM으로 종료되지 않고, 초과량에 비례하는 **인위적 수면 지연(Throttling Sleep Delay)**을 부과받으며 백그라운드 회수가 트리거됩니다.
4. **`memory.max` (하드 한계선 및 OOM 트리거)**:
   cgroup이 사용할 수 있는 절대적 물리 메모리 상한선입니다. 할당 요청으로 인해 이 한계를 초과하면:
   - 커널은 먼저 페이지 캐시나 회수 가능한 메모리를 강제로 청소하는 **직접 회수(Direct Reclaim)**를 시도합니다.
   - 직접 회수 후에도 여전히 한계를 초과하면 **Memcg OOM 킬러**가 발동합니다.
5. **원자적 그룹 킬 (`memory.oom.group`)**:
   cgroup v1에서는 단일 프로세스만 종료되어 컨테이너가 좀비/손상 상태로 방치되는 문제가 있었습니다. cgroup v2에서는 `memory.oom.group = true`로 설정된 cgroup에서 OOM이 발생하면 해당 cgroup 내의 **모든 프로세스가 단일 트랜잭션으로 원자적으로 동시 종료**됩니다.

본 문제에서는 리눅스 커널 cgroup v2 메모리 서브시스템의 **계층적 메모리 과금(Charge/Uncharge), 워터마크 스로틀링, 직접 회수, 그리고 원자적 OOM 킬러 엔진**을 정밀하게 구현해야 합니다.

---

## 시스템 아키텍처 및 계층적 과금 도식

```
+---------------------------------------------------------------------------------------------------+
|               Linux Kernel Cgroup v2 Hierarchical Memory Controller Engine                        |
+---------------------------------------------------------------------------------------------------+

                          Root Cgroup "/" [Usage: sum of all slices]
                                            |
                       +--------------------+--------------------+
                       |                                         |
             "/system.slice"                            "/kubepods.slice"
             [max: 2,000,000]                           [max: 1,000,000]
                                                                 |
                                                    +------------+------------+
                                                    |                         |
                                              "podA"                    "podB"
                                        [high: 400,000]           [high: 500,000]
                                        [max:  600,000]           [max:  700,000]
                                        [oom_group: true]         [oom_group: false]
                                                    |
                                      +-------------+-------------+
                                      |                           |
                                  PID: 1001                   PID: 1002
                                  [RSS: 250,000]              [RSS: 200,000]

   [ Memory Allocation & Hierarchical Check Flow ]
   Process requests alloc(M)
       |
       v
   Walk leaf -> root:
       Is (usage + M > max) at any ancestor?
           |
          (Yes) ---> Trigger Direct Reclaim on reclaimable cache
           |         Still (usage + M > max)?
           |            |
           |           (Yes) ---> Select Victim (Badness = RSS + oom_score_adj*1000)
           |                      Is oom_group == True?
           |                         |
           |                        (Yes) -> Kill ALL processes in victim's cgroup!
           |                        (No)  -> Kill single victim process
           v
       Is (usage + M > high) at any ancestor?
           |
          (Yes) ---> Calculate Proportional Throttle:
                     delay_ms = min(1000, floor(excess * 100 / high))
```

---

## 엔진 명세 및 규칙

### 1. 계층적 메모리 과금 (`_charge` & `_uncharge`)
- 프로세스가 $M$ 바이트를 할당하면, 해당 프로세스가 속한 리프 cgroup부터 루트(`"/"`)까지 모든 상위 조상 노드의 `usage`와 `reclaimable`이 $M$만큼 증가합니다.
- 메모리 해제 시에도 마찬가지로 리프부터 루트까지 모든 상위 조상 노드에서 해당 바이트가 차감됩니다.

### 2. cgroup 생성 (`CREATE_CGROUP`)
- `path`, `min`, `low`, `high`, `max`, `oom_group` 속성을 받아 새로운 cgroup을 생성합니다.
- 부모 cgroup이 존재해야 합니다.

### 3. 프로세스 연결 (`ATTACH_PROCESS`)
- `pid`, `cgroup`, `initial_rss`, `oom_score_adj`를 등록합니다.
- 초기 RSS가 0보다 크면 해당 cgroup에 즉시 과금됩니다.

### 4. 메모리 할당 (`ALLOC_MEMORY`)
- `pid`, `amount`, `reclaimable` (페이지 캐시 등 회수 가능한 메모리 바이트)을 입력받습니다.
- **Max 한계 검사 및 직접 회수 (Direct Reclaim)**:
  - 리프부터 루트까지의 경로 상에서 `usage + amount > max`를 만족하는 조상이 발견되면:
    - 해당 조상 노드의 서브트리에서 `reclaimable` 메모리를 필요한 만큼 즉시 차감(회수)하고 상위로 전파합니다.
  - 회수 후에도 여전히 `usage + amount > max`인 경우:
    - **OOM Kill** 발동:
      - 해당 한계 초과 cgroup 및 그 하위에 속한 모든 활성 프로세스 중 `badness = rss + oom_score_adj * 1000`가 가장 높은 프로세스를 희생자(`victim`)로 선정합니다.
      - 희생자의 cgroup이 `oom_group == True`이면 해당 cgroup 내의 **모든 프로세스를 종료**하고 메모리를 회수합니다.
      - 그렇지 않으면 단일 희생자 프로세스만 종료하고 메모리를 회수합니다.
      - 할당을 요청한 본인 프로세스가 종료되었다면 `"ALLOCATION_KILLED_BY_OOM"` 상태를 반환합니다.
- **과금 및 High 스로틀링 (Throttling)**:
  - 할당이 성공하면 `usage`와 `reclaimable`에 가산합니다.
  - 경로 상의 조상 노드 중 `usage > high`인 노드가 존재하면 비례 수면 지연을 계산합니다:
    $$\text{excess} = \text{usage} - \text{high}$$
    $$\text{delay\_ms} = \min\left(1000, \left\lfloor \frac{\text{excess} \times 100}{\text{high}} \right\rfloor\right)$$

### 5. 메모리 해제 (`FREE_MEMORY`)
- 프로세스의 RSS를 최대 `amount`만큼 차감하고 상위 계층 전체에 언차지를 반영합니다.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "operations": [
    {
      "op": "CREATE_CGROUP",
      "path": "/kubepods",
      "max": 1000000
    },
    {
      "op": "CREATE_CGROUP",
      "path": "/kubepods/pod1",
      "high": 300000,
      "max": 500000,
      "oom_group": true
    },
    {
      "op": "ATTACH_PROCESS",
      "cgroup": "/kubepods/pod1",
      "pid": 101,
      "initial_rss": 100000,
      "oom_score_adj": 0
    },
    {
      "op": "ALLOC_MEMORY",
      "pid": 101,
      "amount": 250000,
      "reclaimable": 50000
    },
    {
      "op": "FREE_MEMORY",
      "pid": 101,
      "amount": 50000
    }
  ],
  "queries": [
    "/kubepods/pod1",
    "/kubepods"
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 연산 결과 리스트, 질의된 cgroup 상태, 전체 요약을 담은 JSON 객체를 공백 없는 압축 형식(`separators=(',', ':')`)으로 출력합니다:

```json
{
  "results": [
    {
      "status": "CGROUP_CREATED",
      "path": "/kubepods"
    }
  ],
  "cgroup_states": {
    "/kubepods/pod1": {
      "path": "/kubepods/pod1",
      "usage": 300000,
      "reclaimable": 50000,
      "oom_kills": 0,
      "throttled_ms": 0,
      "attached_processes": [
        {"pid": 101, "rss": 300000}
      ]
    }
  },
  "summary": {
    "total_cgroups": 3,
    "active_processes": 1,
    "total_oom_kills": 0
  }
}
```

---

## 제약 조건

- 연산 수: $1 \le Q \le 5,000$
- cgroup 노드 수: $1 \le C \le 500$
- 프로세스 수: $1 \le P \le 2,000$
- 메모리 수치: $0 \le \text{bytes} < 2^{63}$
- 표준 라이브러리만을 사용하여 구현해야 함
