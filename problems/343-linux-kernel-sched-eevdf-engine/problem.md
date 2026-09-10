# Linux 6.6 Kernel EEVDF(Earliest Eligible Virtual Deadline First) CPU 스케줄러 엔진

## 문제 설명

리눅스 커널 6.6(2023년 말)부터 지난 16년간(2007년 리눅스 2.6.23 이후) 기본 CPU 스케줄러로 사용되던 **CFS(Completely Fair Scheduler)**가 공식 퇴출되고, 피터 질스트라(Peter Zijlstra)에 의해 **EEVDF(Earliest Eligible Virtual Deadline First)** 스케줄러로 완전히 대체되었습니다.

CFS는 각 태스크의 가상 런타임($v_i$)을 일치시키는 공정성에는 뛰어났으나, 오디오 쓰레드나 UI 렌더러와 같은 **지연 민감형(Latency-sensitive)** 작업이 CPU를 즉각 선점해야 할 때 휴리스틱(`latency-nice`, `min_vruntime` 트릭)에 의존해야 했고, 이로 인해 처리량(Throughput)과 반응성(Latency) 사이에서 끊임없는 충돌과 지연 급증(Latency Spike)을 유발했습니다.

EEVDF는 Peter Hoon의 1995년 학술 논문을 기반으로 **지연(Lag) 기반 적격성(Eligibility)**과 **가상 마감시간(Virtual Deadline)**이라는 수학적으로 완벽한 이중 축을 도입하여 이 난제를 정복했습니다:

```
                            +-------------------------------+
                            |   실행 가능 태스크 집합 (RQ)   |
                            +-------------------------------+
                                            |
                                            v
               +---------------------------------------------------------+
               | 1단계: 적격성(Eligibility) 검사                          |
               | 태스크 가상 런타임 v_i <= 전역 가상 시간 V (즉 Lag >= 0)  |
               +---------------------------------------------------------+
                        |                                       |
                   [적격 태스크]                           [부적격 태스크]
                   v_i <= V                                v_i > V
                        |                                  (자신의 몫을 초과 사용함)
                        v                                       |
       +-----------------------------------+                    v
       | 2단계: 가상 마감시간(Deadline) 탐색 |                선택 대상 제외
       | d_i = v_i + (q_i * 1024) / w_i    |
       | 최소 마감시간 태스크 선점 선택      |
       +-----------------------------------+
                        |
                        v
                 CPU 실행 (Dispatch)
```

본 문제에서는 리눅스 6.6 커널의 EEVDF 스케줄링 아키텍처를 정밀하게 시뮬레이션하는 **이산 시간 EEVDF CPU 스케줄러 엔진**을 구현해야 합니다.

---

## 핵심 메커니즘 및 명세

### 1. 가중치(Weight) 및 시간 척도
리눅스 커널 `kernel/sched/sched.h`의 표준 `prio_to_weight` 테이블을 사용합니다:
- `nice = 0`의 기준 가중치는 `1024`입니다.
- 주요 가중치 매핑:
  - `-20: 88761`, `-15: 29154`, `-10: 9548`, `-5: 3121`, `-2: 1586`
  - `0: 1024`
  - `1: 820`, `2: 655`, `3: 526`, `4: 423`, `5: 335`, `10: 110`, `19: 15`

### 2. 가상 시간($V$) 및 태스크 가상 런타임($v_i$)
- 실행 가능 큐에 등록된 태스크들의 총 가중치:
  $$W = \sum_{j \in \text{runnable}} w_j$$
- 현재 CPU에서 태스크 $i$가 물리 시간 $\Delta t$ (ns) 동안 실행되면:
  - 태스크 가상 런타임 증가:
    $$\Delta v_i = \frac{\Delta t \times 1024.0}{w_i}$$
  - 전역 평균 가상 시간 증가:
    $$\Delta V = \frac{\Delta t \times 1024.0}{W}$$

### 3. 지연(Lag) 및 적격성(Eligibility) 판정
- 태스크 $i$의 지연(Lag):
  $$L_i = V - v_i$$
- 태스크 $i$는 **$v_i \le V$ (즉 $L_i \ge 0$)**일 때만 CPU를 할당받을 수 있는 **적격(Eligible)** 상태로 인정됩니다.
- 부동소수점 오차를 감안하여 $v_i \le V + 10^{-9}$를 적격 조건으로 판정합니다.

### 4. 가상 마감시간(Virtual Deadline, $d_i$) 및 태스크 선택
- 각 태스크는 자신이 요구하는 타임 슬라이스 $q_i$ (`slice_ns`)를 가집니다.
- 가상 마감시간:
  $$d_i = v_i + \frac{q_i \times 1024.0}{w_i}$$
- **스케줄러 태스크 선택 규칙 (`pick_next`)**:
  1. 현재 실행 가능한 태스크들 중 **적격($v_i \le V$)**인 태스크들의 집합을 필터링합니다.
  2. 적격 태스크가 1개 이상 존재하면, **$d_i$가 가장 작은(가장 이른 마감시간)** 태스크를 선택합니다.
     - 마감시간이 동일한 경우 $v_i$가 작은 순, 그다음 `task_id`의 사전순으로 정렬합니다.
  3. 적격 태스크가 없다면, 전체 실행 가능 태스크 중 $v_i$가 가장 작은 태스크를 선택합니다.

### 5. 연산 명세
- `ADD_TASK`:
  - 파라미터: `task_id`, `nice` (기본 0), `slice_ns` (기본값 설정값)
  - 새 태스크의 초기 $v_i$는 현재 전역 가상 시간 $V$로 설정됩니다.
  - 마감시간 $d_i$를 계산하고 런큐에 등록합니다.
  - 반환: `{"status": "TASK_ADDED", "task_id": ..., "weight": ..., "vruntime": round(v_i, 2), "deadline": round(d_i, 2)}`
- `RUN_STEP`:
  - 파라미터: `delta_ns`
  - 런큐가 비어있으면 시각만 전진시키고 `{"status": "IDLE", "time_ns": ...}` 반환.
  - 현재 태스크가 없거나 교체 필요 시 `pick_next`를 수행합니다.
  - 현재 태스크를 `delta_ns`만큼 실행하고 $v_i$와 $V$를 갱신합니다.
  - 현재 태스크의 누적 슬라이스 사용량이 $q_i$ 이상이면 슬라이스가 만료(`slice_expired = true`)되며 새로운 마감시간을 재계산하고 즉시 재스케줄링(`pick_next`)합니다.
  - 슬라이스가 만료되지 않았더라도, 다른 적격 태스크 중 현재 태스크보다 더 이른 마감시간을 가진 태스크가 나타나면 선점(Preemption)이 발생하여 교체됩니다.
  - 반환: `{"executed_task_id": ..., "runtime_added_ns": delta_ns, "task_vruntime": round(v_i, 2), "task_deadline": round(d_i, 2), "global_vruntime": round(V, 2), "slice_expired": bool, "current_task_id": ...}`
- `SLEEP_TASK`: 태스크를 런큐에서 제거하고 상태를 `"SLEEPING"`으로 변경.
- `WAKE_TASK`: 태스크를 깨움. EEVDF 규칙에 따라 수면 중 무한정 누적된 양의 지연(과도한 우선권)을 방지하기 위해 $v_i = \max(v_i, V)$로 클램핑한 뒤 마감시간을 재계산하고 런큐에 재등록.
- `GET_STATS`: 전역 시각, 전역 가상 시간, 현재 태스크, 전체 태스크 목록(가중치, $v_i$, $d_i$, lag, eligible, 상태 등) 반환.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 전달됩니다:
```json
{
  "config": {
    "default_slice_ns": 3000000
  },
  "operations": [
    { "op": "ADD_TASK", "task_id": "interactive", "nice": 0, "slice_ns": 1000000 },
    { "op": "ADD_TASK", "task_id": "bulk", "nice": 0, "slice_ns": 6000000 },
    { "op": "RUN_STEP", "delta_ns": 1000000 },
    { "op": "GET_STATS" }
  ]
}
```

## 출력 형식

표준 출력(stdout)으로 연산 수행 결과를 담은 JSON 배열을 공백 없이(compact) 출력합니다.

---

## 제약 사항

- $-20 \le \text{nice} \le 19$
- $10^5 \le \text{slice\_ns} \le 10^8$
- $10^4 \le \text{delta\_ns} \le 10^8$
- 연산 수 $N \le 5000$
- 시간 복잡도: 각 연산당 $O(M \log M)$ 이내 (여기서 $M$은 동시 실행 태스크 수).
