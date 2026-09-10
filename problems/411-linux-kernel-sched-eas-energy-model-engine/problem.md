# 문제 411: Linux 커널 EAS(Energy Aware Scheduling) 에너지 모델 및 이종 멀티코어 태스크 배치 엔진

## 문제 설명

현대 스마트폰, 태블릿, 웨어러블 디바이스 및 최신 저전력 랩톱은 배터리 수명을 극대화하면서도 순간적인 고성능 요구를 충족하기 위해 서로 다른 성능과 전력 특성을 지닌 CPU 코어들을 조합한 **이종 멀티코어(Heterogeneous Multi-Core / Arm big.LITTLE, DynamIQ, Intel Alder Lake 등)** 아키텍처를 전면 채택하고 있습니다.

일반적으로 고효율 리틀 코어(LITTLE Core: Cortex-A55 등)는 저클럭에서 극도로 낮은 전력을 소모하며, 고성능 빅 코어(BIG Core: Cortex-A78/X3 등)는 높은 클럭과 광폭(Wide) 파이프라인으로 높은 연산량을 처리하지만 리틀 코어 대비 5배~10배 이상의 전력을 소비합니다.

전통적인 리눅스 커널의 CFS(Completely Fair Scheduler)는 "모든 CPU 간의 부하(`load_avg`) 균등 분배(Throughput & Fairness)"만을 최우선 목표로 삼았습니다. 그러나 이종 멀티코어 환경에서 CFS의 단순 부하 균등화는 심각한 재앙을 초래합니다. 단순 백그라운드 동기화 스레드나 메신저 알림 수신과 같은 가벼운 태스크를 부하가 적다는 이유로 빅 코어에 배치하여 귀중한 배터리를 순식간에 고갈시키거나, 반대로 즉각적인 프레임 렌더링이 필요한 무거운 게임 스레드를 리틀 코어에 배치하여 프레임 드롭(Jank)을 발생시키기 때문입니다.

이를 근본적으로 해결하기 위해 리눅스 커널 5.0에 공식 통합된 서브시스템이 바로 **EAS (Energy Aware Scheduling, `kernel/sched/fair.c`, `kernel/sched/energy.c`, `CONFIG_ENERGY_MODEL`)**입니다.

### EAS의 핵심 동작 메커니즘

1. **성능 도메인(Performance Domain, PD)과 동작 성능 지점(OPP)**:
   - 전압과 주파수(DVFS)를 공유하는 CPU 그룹을 성능 도메인(PD)으로 정의합니다 (예: LITTLE 도메인 `[CPU 0..3]`, BIG 도메인 `[CPU 4..7]`).
   - 각 도메인은 하드웨어 전력 특성을 반영한 **OPP(Operating Performance Point)** 테이블을 가집니다.
   - 각 OPP는 해당 주파수에서의 연산 용량(`capacity`)과 소비 전력(`power_mw`)을 명시합니다.

2. **용량 마진(Capacity Margin) 검증 (`fits_capacity()`)**:
   - 태스크의 PELT 연산 가동률(`task_util`)과 대상 CPU의 현재 가동률(`cpu_util`)의 합이 해당 CPU의 최대 연산 용량(`max_capacity`)의 80%(`capacity_margin = 0.8`)를 초과하지 않아야 해당 CPU에 배치될 수 있습니다:
     $$cpu\_util + task\_util \le 0.8 	imes max\_capacity$$
   - 80% 이상의 부하가 걸리면 CPU 주파수가 최대치로 치솟아 전력 효율이 급격히 악화되므로, 리틀 코어의 80% 마진을 초과하는 고부하 태스크는 자동으로 빅 코어 후보군으로 강제 승격됩니다.

3. **시스템 에너지 예측 모델 (`compute_system_energy()`)**:
   - 태스크가 특정 후보 CPU에 배치되었을 때, 각 성능 도메인이 요구하는 최소 OPP 주파수를 산출합니다:
     $$OPP_{cap} = \min \{ opp.capacity \mid opp.capacity \ge \max_{c \in PD}(proj\_util_c) \}$$
   - 해당 OPP에서의 성능 도메인 소비 전력을 도출합니다:
     $$P(PD) = \sum_{c \in PD} \left( rac{proj\_util_c}{OPP_{cap}} 	imes opp.power\_mw ight)$$
   - 전체 시스템 소비 전력 $E_{total} = \sum_{PD} P(PD)$를 계산하여, 가장 전력 소비가 적은 최적의 CPU를 탐색합니다.

4. **캐시 친화도 및 에너지 절감 마진 (`energy_margin_mw`)**:
   - 코어 간 태스크 마이그레이션은 L1/L2 CPU 캐시 미스(Cache Miss)와 상호연결망(Interconnect) 전송 비용을 유발합니다.
   - 따라서 이전 CPU(`prev_cpu`) 대신 다른 최적 CPU(`best_cand`)로 이동하려면, 예상되는 에너지 절감량이 최소 마진 임계값(`energy_margin_mw`, 예: 15mW)을 초과해야만 마이그레이션을 단행합니다.

5. **과부하(Overutilized) 상태 감지 및 CFS 폴백 (Fallback)**:
   - 시스템 내 어느 한 CPU라도 80% 용량 한계를 초과(`cpu_util > 0.8 * max_capacity`)하면, 시스템은 즉시 **과부하(OVERUTILIZED)** 상태로 전이합니다.
   - 과부하 상태에서는 에너지 절약보다 시스템 전체의 연산 처리량 붕괴 방지가 최우선이므로, **EAS 에너지 모델을 즉시 비활성화**하고 전통적인 CFS 로드 밸런싱(가장 가동률이 낮은 CPU로 단순 부하 분산) 모드로 자동 폴백합니다.
   - 부하가 다시 완화되면 자동으로 EAS 정상 모드로 복귀합니다.

여러분은 리눅스 커널 EAS 스케줄러의 성능 도메인/OPP 에너지 계산 엔진, 용량 마진 검사, 캐시 친화도 마진 제어, 과부하 감지 및 CFS 폴백 상태 머신을 충실히 모델링하는 시뮬레이터를 구현해야 합니다.

---

## 시스템 아키텍처 다이어그램

```
+==================================================================================================+
|                        Linux Kernel Energy-Aware Scheduling (EAS)                                |
+==================================================================================================+

   [ Waking Task: task_id, task_util, prev_cpu ]
                       |
                       v
+--------------------------------------------------------------------------------------------------+
| select_task_rq_fair() / find_energy_efficient_cpu() (kernel/sched/fair.c)                        |
|                                                                                                  |
|  [ Step 1: Overutilized Tipping Point Check ]                                                    |
|    - Is ANY CPU util > 0.8 * max_capacity ?                                                      |
|      * YES: ===> [ FALLBACK_CFS ]                                                                |
|                  - EAS Disabled! Prioritize Throughput over Battery                              |
|                  - Select CPU with MINIMUM current utilization across all CPUs                   |
|                                                                                                  |
|      * NO:  ===> [ EAS_ENERGY_OPTIMAL MODE ]                                                     |
|                                                                                                  |
|  [ Step 2: Filter Candidate CPUs by Capacity Margin (fits_capacity) ]                            |
|    - For each Performance Domain (LITTLE / BIG / PRIME):                                         |
|        cpu_util[c] + task_util <= 0.8 * pd.max_capacity ?                                        |
|        * Exclude domains where task does not fit!                                                |
|        * Pick best candidate CPU per fitting domain (lowest util or prev_cpu)                    |
|                                                                                                  |
|  [ Step 3: Energy Model Evaluation (compute_system_energy) ]                                      |
|    - For each Candidate CPU c:                                                                   |
|        1. Simulate projecting task on CPU c                                                      |
|        2. Determine required OPP frequency for each Perf Domain:                                 |
|             OPP_cap = min { opp.cap >= max(proj_util) }                                         |
|        3. Calculate power: P(PD) = sum( (proj_util / OPP_cap) * opp.power_mw )                   |
|        4. Total System Power: E(c) = sum( P(PD) )                                                |
|                                                                                                  |
|  [ Step 4: Cache Affinity & Energy Margin Decision ]                                             |
|    - Compare best_cand vs prev_cpu:                                                              |
|        If E(prev_cpu) - E(best_cand) > energy_margin_mw:                                         |
|            Migrate to best_cand!                                                                 |
|        Else:                                                                                     |
|            Retain on prev_cpu (Preserve L1/L2 Cache warmth!)                                     |
+==================================================================================================+
```

---

## 상세 요구사항 및 동작 규칙

### 1. 시스템 설정 파라미터 (`config`)
- `capacity_margin`: 코어 수용 한계 마진 비율 (기본값: `0.8`, 즉 80%)
- `energy_margin_mw`: 이전 CPU 유지 대비 이주를 결정하기 위한 최소 에너지 절감 임계치 (기본값: `15` mW)
- `perf_domains`: 성능 도메인 배열. 각 도메인은 다음 필드를 포함합니다:
  - `pd_id`: 도메인 식별자 (`"LITTLE"`, `"BIG"`, `"MID"`, `"PRIME"` 등)
  - `cpus`: 소속 CPU 번호 리스트 (예: `[0, 1, 2, 3]`)
  - `max_capacity`: 도메인 CPU의 최대 연산 용량 (예: LITTLE은 `450`, BIG은 `1024`)
  - `opps`: 동작 성능 지점 배열, 각 원소는 `capacity`, `freq_mhz`, `power_mw`를 포함하며 용량 오름차순으로 정렬되어 있습니다.

### 2. 이벤트 트레이스 연산 (`trace`)

1. **`UPDATE_CPU_UTIL`**:
   - `time`, `cpu_id`, `util`.
   - 지정된 CPU의 백그라운드 PELT 가동률을 직접 갱신합니다.

2. **`WAKEUP_TASK`**:
   - `time`, `task_id`, `task_util`, `prev_cpu`.
   - 태스크가 대기 상태에서 깨어나 CPU에 스케줄링 배치되는 이벤트입니다.
   - **과부하 검사 (`is_overutilized`)**:
     - 시스템의 모든 CPU 중 어느 하나라도 `cpu_util[c] > capacity_margin * max_capacity[c]`를 만족하면 과부하 상태입니다.
     - 과부하 상태이면 `decision_mode = "FALLBACK_CFS"`, 전체 CPU 중 현재 가동률이 가장 낮은 CPU(동률 시 `prev_cpu`, 그다음 CPU 번호 오름차순)를 타깃으로 선택합니다.
   - **EAS 에너지 최적 배치 (`decision_mode = "EAS_ENERGY_OPTIMAL"`)**:
     - 각 성능 도메인별로 `cpu_util[c] + task_util <= capacity_margin * max_capacity`를 만족하는 CPU들을 찾습니다.
     - 만족하는 CPU 중 가동률이 가장 낮은 CPU(동률 시 `prev_cpu` 우선, 그다음 CPU 번호 오름차순)를 해당 도메인의 대표 후보로 선정합니다.
     - 후보가 존재하는 모든 도메인의 대표 후보들에 대해, 태스크를 해당 CPU에 배치했을 때의 전체 시스템 전력 소모 $E(c)$를 계산합니다.
     - 가장 전력 소모가 적은 후보 `best_cand`를 도출합니다.
     - 만약 `prev_cpu`가 후보군에 포함되어 있다면:
       - $E(prev\_cpu) - E(best\_cand) > energy\_margin\_mw$인 경우에만 `best_cand`로 이동.
       - 그렇지 않다면 캐시 친화도를 위해 `target_cpu = prev_cpu`로 유지.
     - 만약 `prev_cpu`가 후보군에 없다면(용량 초과 등) 즉시 `best_cand`를 타깃으로 선택.
   - 타깃 CPU의 가동률을 `task_util`만큼 증가시키고 활성 태스크에 등록합니다.

3. **`TASK_SLEEP`**:
   - `time`, `task_id`.
   - 태스크가 실행을 마치고 슬립 상태로 진입합니다.
   - 할당되었던 CPU의 가동률에서 해당 태스크의 `task_util`을 차감하고 활성 태스크에서 제거합니다.

---

## 입출력 형식 (JSON)

### 입력 형식 (Standard Input)

```json
{
  "config": {
    "capacity_margin": 0.8,
    "energy_margin_mw": 15,
    "perf_domains": [
      {
        "pd_id": "LITTLE",
        "cpus": [0, 1, 2, 3],
        "max_capacity": 450,
        "opps": [
          {"capacity": 200, "freq_mhz": 800, "power_mw": 50},
          {"capacity": 350, "freq_mhz": 1400, "power_mw": 120},
          {"capacity": 450, "freq_mhz": 1800, "power_mw": 200}
        ]
      },
      {
        "pd_id": "BIG",
        "cpus": [4, 5, 6, 7],
        "max_capacity": 1024,
        "opps": [
          {"capacity": 500, "freq_mhz": 1200, "power_mw": 350},
          {"capacity": 800, "freq_mhz": 2000, "power_mw": 800},
          {"capacity": 1024, "freq_mhz": 2800, "power_mw": 1600}
        ]
      }
    ]
  },
  "trace": [
    {
      "time": 0,
      "type": "WAKEUP_TASK",
      "task_id": "bg_sync",
      "task_util": 100,
      "prev_cpu": 5
    }
  ]
}
```

### 출력 형식 (Standard Output)

공백 없이 압축된 단일 라인 JSON 문자열(`separators=(',', ':')`, `ensure_ascii=False`)로 출력해야 합니다:

```json
{
  "summary": {
    "total_decisions": 1,
    "eas_optimal_count": 1,
    "cfs_fallback_count": 0,
    "final_overutilized": false,
    "final_system_power_mw": 25.0
  },
  "cpu_utilizations": {
    "0": 100,
    "1": 0,
    "2": 0,
    "3": 0,
    "4": 0,
    "5": 0,
    "6": 0,
    "7": 0
  },
  "eas_decisions": [
    {
      "time": 0,
      "task_id": "bg_sync",
      "task_util": 100,
      "prev_cpu": 5,
      "target_cpu": 0,
      "decision_mode": "EAS_ENERGY_OPTIMAL",
      "overutilized": false,
      "estimated_system_power_mw": 25.0
    }
  ],
  "event_logs": [ ... ]
}
```
