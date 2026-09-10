# 394: 리눅스 커널 CPU 스케줄링 — Core Scheduling(PR_SCHED_CORE) SMT 교차 하이퍼스레드 추측 실행 부채널 완화 및 쿠키 매칭 엔진

## 1. 개요 (Overview)

현대 x86_64 및 ARM64 프로세서의 **동시 멀티스레딩(SMT: Simultaneous Multi-Threading, 예: Intel Hyper-Threading, AMD SMT)** 기술은 단일 물리 코어(Physical Core)의 연산 파이프라인, 분기 예측기(Branch Predictor), L1 명령어/데이터 캐시, 마이크로아키텍처 버퍼(Line Fill Buffer, Store Buffer)를 여러 논리 CPU(Logical SMT Siblings)가 공유함으로써 스레드 처리량을 20%~40% 향상시킵니다.

그러나 2018~2019년 발견된 **L1TF (L1 Terminal Fault / Foreshadow, CVE-2018-3620)**, **MDS (Microarchitectural Data Sampling / ZombieLoad / RIDL, CVE-2019-11091)**, **Cross-Thread Spectre v2** 등의 투기적 실행(Speculative Execution) 하드웨어 취약점으로 인해, 동일한 물리 코어에서 동시에 실행되는 서로 다른 신뢰 도메인(예: 악의적 멀티테넌트 VM vs 금융 컨테이너) 간에 캐시 필 버퍼의 기밀 데이터가 누출되는 치명적인 보안 재앙이 드러났습니다.

이를 해결하기 위해 과거에는 BIOS에서 하이퍼스레딩을 전면 비활성화(`nosmt`)하는 극단적인 조치를 취했으나, 이는 클라우드 데이터센터 전체 컴퓨팅 용량의 30% 이상을 상실하는 막대한 경제적 손실을 초래했습니다.

리눅스 커널 5.14에 공식 머지된 **코어 스케줄링(Core Scheduling, `kernel/sched/core.c`, `PR_SCHED_CORE`)** 은 하드웨어 SMT를 켜둔 상태에서도 동일한 물리 코어의 SMT 형제 스레드들(Siblings) 간에는 **오직 동일한 보안 쿠키(Core Cookie)** 를 부여받은 태스크들만 동시 실행되도록 보장하는 혁신적인 커널 스케줄링 프레임워크입니다. 만약 한 하이퍼스레드가 특정 테넌트 태스크를 실행 중일 때 다른 형제 스레드에 상이한 쿠키를 가진 태스크만 존재한다면, 커널은 해당 형제 스레드를 즉시 강제 유휴 상태(**Forced Idle**, `sched_core_force_idle`)로 정지시켜 부채널 정보 누출을 원천 봉쇄합니다.

본 문제에서는 리눅스 커널의 Core Scheduling 아키텍처, `PR_SCHED_CORE` 시스템 콜 프리미티브, 코어 리더 선출 알고리즘(`pick_next_task()`), 쿠키 매칭 및 강제 유휴(Forced Idle) 사이클 계량, CFS/RT 계층 우선순위 규칙을 충실히 모델링한 **SMT 하이퍼스레드 쿠키 매칭 및 보안 격리 시뮬레이션 엔진**을 설계 및 구현합니다.

---

## 2. 하드웨어 및 커널 아키텍처 다이어그램

```
+========================================================================================+
|                        Physical CPU Core C (Shared L1/L2 Cache & LFB)                  |
|                                                                                        |
|  +-------------------------------------+      +-------------------------------------+  |
|  |     SMT Sibling 0 (CPU 2*C + 0)     |      |     SMT Sibling 1 (CPU 2*C + 1)     |  |
|  |  [Local Runqueue: T_A1, T_A2, ...]  |      |  [Local Runqueue: T_B1, T_B2, ...]  |  |
|  +-------------------------------------+      +-------------------------------------+  |
|                     \                                            /                     |
|                      \==========================================/                      |
|                                            ||                                          |
|                       [Core-Wide Leader Task Election: pick_next_task()]               |
|                       - Highest Priority: max(RT prio) > min(CFS vruntime)             |
|                       - Establish Core-Wide Cookie: K* = task_leader.cookie            |
|                                            ||                                          |
|                      /==========================================\                      |
|                     //                                            \\                     |
|  +-------------------------------------+      +-------------------------------------+  |
|  | Sibling 0 Match: Task has K*?       |      | Sibling 1 Match: Task has K*?       |  |
|  |  [YES] -> RUNNING (Active Execute)  |      |  [NO]  -> FORCED_IDLE (Halt Thread) |  |
|  +-------------------------------------+      +-------------------------------------+  |
|                     ||                                            ||                   |
|                     VV                                            VV                   |
|  [Speculative Execution Boundary Kept]        [Thread Stalled: Zero Leakage MDS/L1TF]  |
+========================================================================================+
```

---

## 3. 핵심 수리 및 스케줄링 규칙 (Mathematical Formulation)

### 3.1 태스크 우선순위 서열 (Task Priority Order)
각 태스크 $T$의 우선순위 튜플 $	ext{Rank}(T)$는 작을수록 높은 우선순위를 갖습니다:
$$	ext{Rank}(T) = egin{cases} (0, -	ext{prio\_val}, 0.0, 	ext{task\_id}) & 	ext{if } T.	ext{prio\_type} = 	ext{"RT"} \ (1, 0, 	ext{vruntime}, 	ext{task\_id}) & 	ext{if } T.	ext{prio\_type} = 	ext{"CFS"} \end{cases}$$
1. **스케줄링 클래스**: 모든 RT(Real-Time) 태스크는 임의의 CFS(Completely Fair Scheduler) 태스크보다 절대적으로 우선합니다.
2. **RT 서열**: RT 태스크 간에는 `prio_val`이 높을수록(1~99) 우선합니다.
3. **CFS 서열**: CFS 태스크 간에는 가상 런타임 `vruntime`이 작을수록 우선합니다.
4. **동점 처리**: 모든 조건이 동일할 경우 문자열 `task_id`의 사전순(오름차순)으로 우선순위를 결정합니다.

### 3.2 코어 리더 선출 및 코어 쿠키 $K^*$ 확정
물리 코어 $C$에 속한 각 SMT 형제 $S \in \{0, 1, \dots, N_{smt}-1\}$의 로컬 런큐에서 실행 대기(`RUNNABLE`) 중인 태스크 중 최우선 태스크 $T_{S}^*$를 선별합니다.
코어 전체 후보 집합 $\{T_S^*\}$ 중 전역 최우선 태스크를 코어 리더(Core Leader)로 선출하며, 해당 태스크의 쿠키가 이번 틱(Tick)의 코어 보안 쿠키 $K^*$로 확정됩니다:
$$T_{	ext{leader}} = rg\min_{T \in \{T_S^*\}} 	ext{Rank}(T), \quad K^* = T_{	ext{leader}}.	ext{cookie}$$

### 3.3 형제 스레드 태스크 선택 및 강제 유휴 (Forced Idle)
각 형제 스레드 $S$에 대해:
1. 로컬 런큐에 $T.	ext{cookie} == K^*$인 실행 가능 태스크가 존재하는 경우:
   해당 조건을 만족하는 태스크 중 $	ext{Rank}(T)$가 가장 우수한 태스크를 선택하여 `RUNNING` 상태로 실행합니다.
2. 로컬 런큐에 실행 가능 태스크는 존재하지만 모두 $T.	ext{cookie} 
e K^*$인 경우:
   추측 실행 부채널 격리를 위해 해당 형제 스레드는 **`FORCED_IDLE`** 상태로 전이되어 실행이 정지(Halt)됩니다.
3. 로컬 런큐에 실행 가능 태스크가 전혀 없는 경우:
   자연 유휴 상태인 **`PURE_IDLE`** 상태가 됩니다.

### 3.4 불변식 검증 (Security Invariant)
어떠한 스케줄링 틱에서도 동일한 물리 코어 $C$의 서로 다른 형제 스레드에서 동시에 실행 중인(`RUNNING`) 태스크들의 쿠키 집합의 크기는 1을 초과할 수 없습니다:
$$|\{T.	ext{cookie} \mid T 	ext{ is RUNNING on SMT siblings of core } C\}| \le 1$$
이를 위반할 경우 `security_violations` 카운터를 증가시킵니다 (정상 스케줄러에서는 항상 0이어야 함).

### 3.5 사이클 및 강제 유휴 비율 계량 (Cycle Accounting)
슬라이스 단위 $\Delta t$ 동안:
- 태스크 실행 시간 $e = \min(\Delta t, 	ext{burst\_remaining})$:
  - $	ext{active\_exec\_cycles} \mathrel{+}= e$
  - 잔여 슬라이스 유휴: $(\Delta t - e > 0)$이면 $	ext{pure\_idle\_cycles} \mathrel{+}= (\Delta t - e)$
  - CFS 태스크는 가상 런타임 증가: $	ext{vruntime} \mathrel{+}= e$
- 강제 유휴 스레드: $	ext{forced\_idle\_cycles} \mathrel{+}= \Delta t$
- 자연 유휴 스레드: $	ext{pure\_idle\_cycles} \mathrel{+}= \Delta t$
- 전체 클러스터 강제 유휴 비율:
  $$	ext{forced\_idle\_ratio} = rac{\sum_C 	ext{forced\_idle\_cycles}}{\sum_C (	ext{active} + 	ext{forced} + 	ext{pure})}$$

### 3.6 `PR_SCHED_CORE` 연산
- `PR_SCHED_CORE_CREATE`: 특정 태스크에 새로운 고유 쿠키를 할당합니다.
- `PR_SCHED_CORE_SHARE_TO`: `source` 태스크의 쿠키를 `target` 태스크에 복사(공유)합니다.
- `PR_SCHED_CORE_SHARE_FROM`: `source` 태스크의 쿠키를 호출 태스크에 복제합니다.
- `PR_SCHED_CORE_RESET`: 태스크의 쿠키를 `"0"` (기본 태그 없음)으로 초기화합니다.

---

## 4. 입력 형식 (Input Specification)

표준 입력(stdin)으로 JSON 객체가 주어집니다:
```json
{
  "config": {
    "num_cores": 1,
    "siblings_per_core": 2,
    "slice_duration": 10
  },
  "tasks": [
    {
      "task_id": "vCPU-TenantA",
      "cookie": "tenant_A",
      "prio_type": "CFS",
      "prio_val": 0,
      "vruntime": 10.0,
      "burst": 20,
      "assigned_core": 0,
      "assigned_sibling": 0
    }
  ],
  "events": [
    {
      "at_time": 10,
      "action": "PR_SCHED_CORE",
      "op": "PR_SCHED_CORE_SHARE_TO",
      "source": "A1",
      "target": "A2"
    }
  ],
  "max_ticks": 100
}
```

---

## 5. 출력 형식 (Output Specification)

표준 출력(stdout)으로 공백 없는 압축 JSON(Compact JSON)을 출력합니다:
```json
{
  "total_time": 40,
  "ticks_executed": 4,
  "security_violations": 0,
  "isolation_guaranteed": true,
  "completed_tasks": ["A1", "A2"],
  "forced_idle_ratio": 0.25,
  "core_stats": {
    "0": {
      "active_exec_cycles": 60,
      "forced_idle_cycles": 20,
      "pure_idle_cycles": 0
    }
  },
  "task_log": {
    "A1": {
      "burst_initial": 30,
      "burst_remaining": 0,
      "total_exec": 30,
      "completion_time": 40,
      "final_cookie": "tenant_A",
      "final_vruntime": 40.0,
      "state": "COMPLETED"
    }
  },
  "audit_events": [
    {
      "timestamp": 0,
      "core_id": 0,
      "cookie": "tenant_A",
      "sibling_0": "A1",
      "sibling_1": "FORCED_IDLE"
    }
  ]
}
```
