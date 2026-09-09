# Linux CFS(Completely Fair Scheduler)의 가상 실행 시간(vruntime), Nice 가중치와 슬리퍼 기아(Sleeper Starvation) 방어

## 1. 개요: 리눅스 프로세스 스케줄러의 진화와 CFS의 탄생

운영체제 커널의 심장인 CPU 스케줄러는 시스템 내 실행 가능한 수많은 프로세스/스레드에게 CPU 시간을 어떻게 배분할 것인가를 결정합니다.

1. **초기 유닉스 및 리눅스 2.4 ($O(N)$ 스케줄러)**:
   - 틱마다 모든 실행 가능 태스크를 순회하며 우선순위 점수를 계산. 태스크 수가 늘어날수록 스케줄링 오버헤드가 급증.
2. **리눅스 2.6 ($O(1)$ 스케줄러, Ingo Molnar)**:
   - 140개의 우선순위 큐와 `active` / `expired` 런큐 배열을 사용하여 상수 시간 $O(1)$에 다음 태스크를 선택.
   - 그러나 태스크가 "인터랙티브한지, 배치 작업인지"를 판별하기 위해 복잡한 경험적 휴리스틱(Heuristics)에 의존하여 오디오 왜곡, 데스크톱 끊김 등의 문제를 완벽히 해결하지 못함.
3. **리눅스 2.6.23 (CFS, Completely Fair Scheduler, Ingo Molnar)**:
   - 복잡한 휴리스틱을 모두 제거하고, 수학적으로 완벽한 **"이상적인 멀티태스킹 하드웨어(Ideal Multi-tasking Hardware)"** 모델을 도입.
   - $N$개의 동일 우선순위 프로세스가 존재한다면, 하드웨어 레벨에서 단일 CPU가 $N$개로 쪼개져 각각 정확히 $1/N$의 속도로 완전히 동시에 실행되는 상태를 이상적 상태로 정의.
   - 실제 단일 코어 CPU는 한 순간에 하나의 프로세스만 실행할 수 있으므로, **"각 프로세스가 지금까지 누적해서 소모한 가상 실행 시간(vruntime)"**을 기록하고, **항상 가장 덜 실행된(vruntime이 가장 작은) 프로세스를 먼저 실행**시키는 방식으로 공정성을 달성.

---

## 2. CFS 핵심 원리: vruntime과 Nice 가중치

### 2.1 가상 실행 시간 (vruntime, Virtual Runtime)

CFS에서 각 프로세스의 스케줄링 엔티티(`struct sched_entity`)는 자신의 가상 실행 시간인 `vruntime`을 가집니다.

태스크가 물리 CPU에서 $\Delta \text{exec\_time}$ (예: 1ms) 동안 실행되었을 때, `vruntime`은 태스크의 가중치(`weight`)에 반비례하여 증가합니다:

$$\Delta vruntime = \Delta \text{exec\_time} \times \frac{1024}{\text{weight}}$$

- `nice = 0`인 기본 프로세스는 `weight = 1024`를 가집니다. 따라서 $\Delta vruntime = \Delta \text{exec\_time}$이 되어 실제 물리 시간과 가상 시간이 $1:1$로 일치합니다.
- 높은 우선순위 태스크(`nice < 0`): `weight > 1024`이므로 $1024 / \text{weight} < 1$이 됩니다. 즉, **물리 시간을 많이 써도 $vruntime$이 천천히 증가**합니다.
- 낮은 우선순위 태스크(`nice > 0`): `weight < 1024`이므로 $1024 / \text{weight} > 1$이 됩니다. 즉, **물리 시간을 조금만 써도 $vruntime$이 가파르게 증가**합니다.

### 2.2 Nice 가중치 테이블 (`sched_prio_to_weight`)

리눅스 커널 소스(`kernel/sched/core.c`)에 하드코딩된 가중치 테이블은 Nice 값이 1 변할 때마다 약 **$1.25$배 (25%)**의 CPU 점유율 차이를 갖도록 기하급수적으로 설계되었습니다:

```c
const int sched_prio_to_weight[40] = {
 /* -20 */     88761,     71755,     56483,     46273,     36291,
 /* -15 */     29154,     23254,     18705,     14949,     11916,
 /* -10 */      9548,      7620,      6100,      4904,      3906,
 /*  -5 */      3121,      2501,      1991,      1586,      1277,
 /*   0 */      1024,       820,       655,       526,       423,
 /*   5 */       335,       272,       215,       172,       137,
 /*  10 */       110,        87,        70,        56,        45,
 /*  15 */        36,        29,        23,        18,        15,
};
```

두 태스크 $A(\text{nice } -5, \text{weight } 3121)$와 $B(\text{nice } 5, \text{weight } 335)$가 있다면:
$$\text{CPU 할당 비율} = \frac{3121}{335} \approx 9.32 : 1$$
$A$는 $B$보다 약 9.3배 더 많은 물리 CPU 시간을 할당받지만, 가상 시간인 $vruntime$의 관점에서는 두 프로세스 모두 동일한 속도로 전진하여 완벽히 공정한 상태를 유지합니다.

### 2.3 레드-블랙 트리(Red-Black Tree)를 이용한 $O(\log N)$ 관리와 $O(1)$ 디스패치

CFS는 실행 가능한 모든 태스크를 `vruntime` 키 기준으로 정렬된 자가 균형 이진 탐색 트리인 **Red-Black Tree**(`cfs_rq->tasks_timeline`)에 보관합니다:
- 가장 $vruntime$이 작은 태스크는 트리의 맨 왼쪽 노드(`rb_leftmost`)에 위치합니다.
- 커널은 항상 포인터 캐싱을 통해 **$O(1)$의 즉각적인 시간**에 다음 실행할 태스크(`pick_next_task_fair`)를 선택합니다.
- 태스크가 실행되어 $vruntime$이 증가하면 트리에서 제거된 후 새로운 $vruntime$ 위치에 $O(\log N)$으로 재삽입됩니다.

---

## 3. `min_vruntime`과 단조 증가 불변식

실행 큐(`cfs_rq`)에는 현재 런큐 내 모든 활성 태스크들의 최소 $vruntime$을 추적하는 **`min_vruntime`** 변수가 존재합니다.

`min_vruntime`은 다음과 같은 엄격한 불변식을 따릅니다:
1. **단조 증가성 (Monotonically Non-Decreasing)**:
   $$\text{min\_vruntime} \leftarrow \max(\text{min\_vruntime}, \min_{t \in \text{runnable}} t.vruntime)$$
   시스템 시간이 거꾸로 흐르지 않듯, 가상 기준 시계인 `min_vruntime`도 절대 뒤로 돌아가지 않습니다.
2. **신규 프로세스 초기화 (`fork`)**:
   만약 새로 생성된 프로세스의 $vruntime$을 0으로 설정한다면 어떻게 될까요?
   시스템이 10일 동안 켜져 있어 기존 태스크들의 $vruntime$이 수억 ms에 달할 때, 신규 태스크가 $vruntime = 0$으로 들어오면 **기존 태스크들의 $vruntime$을 따라잡을 때까지 수일 동안 혼자 CPU를 100% 독점**하게 됩니다!
   따라서 신규 태스크는 반드시 `task->vruntime = min_vruntime`으로 현재 런큐의 기준 시계에 맞춰 초기화되어야 합니다.

---

## 4. 참사의 근원: 슬리퍼 기아와 CPU 독점 (Sleeper CPU Monopoly)

### 4.1 슬리퍼 태스크의 라이프사이클

현대 운영체제의 대다수 태스크(UI 이벤트 루프, 음악/동영상 플레이어의 오디오 출력 스레드, 네트워크 소켓 대기 데몬)는 CPU 연산보다 I/O 입력을 기다리는 **대기(Sleeping) 상태**에 머무릅니다.

```
[Audio Player Task] ---- (10ms 실행) ----> [Sleep for 50ms (오디오 버퍼 채우기 대기)] ----> [Wakeup!]
[Batch Worker Task] ---------------------- (60ms 동안 쉬지 않고 CPU 연산 수행) ------------------------->
```

### 4.2 슬리퍼 페어니스가 없는 나이브한 스케줄러의 파멸

만약 슬리퍼 태스크가 깨어날 때 자신의 과거 $vruntime$을 그대로 유지한다면:
1. $t=10$ms 시점에 `audio` 태스크의 $vruntime$은 10ms였습니다.
2. `audio`가 50ms 동안 잠들어 있는 동안, `worker` 태스크는 쉬지 않고 실행되어 자신의 $vruntime$과 `min_vruntime`을 60ms까지 밀어올렸습니다.
3. $t=60$ms 시점에 `audio`가 깨어났습니다!
4. **나이브한 스케줄러**:
   - `audio->vruntime` = 10ms
   - `worker->vruntime` = 60ms
5. **결과 (참사)**:
   - `audio`의 $vruntime$이 `worker`보다 무려 50ms나 뒤처져 있습니다!
   - `audio`는 RB-Tree의 맨 왼쪽 끝에 말뚝을 박고, 자신의 $vruntime$이 10에서 60에 도달할 때까지 **50ms 동안 단 1밀리초도 양보하지 않고 CPU를 연속 독점 실행**합니다!
   - 그동안 `worker`는 런큐에서 50ms 동안 완전히 굶주려(Starved) 응답이 멈추고 지연 시간(Latency) 스파이크를 겪습니다 (`CATASTROPHIC_SLEEPER_CPU_MONOPOLY`).
   - 만약 10초 동안 잠들었던 백그라운드 데몬이 깨어난다면, 시스템 전체가 10초 동안 프리징되는 대재앙이 발생합니다!

---

## 5. 해결책: 리눅스 커널의 Sleeper Fairness (`place_entity`)

리눅스 커널은 `kernel/sched/fair.c`의 `place_entity` 함수를 통해 이 문제를 완벽하게 해결합니다:

```c
static void
place_entity(struct cfs_rq *cfs_rq, struct sched_entity *se, int initial)
{
    u64 vruntime = cfs_rq->min_vruntime;

    if (!initial) {
        /* sysctl_sched_latency 기본값: 6ms */
        unsigned long thresh = sysctl_sched_latency;

        /* FAIR_SLEEPERS 기능: 슬리퍼 보너스를 절반으로 제한 */
        if (sched_feat(FAIR_SLEEPERS))
            thresh >>= 1; /* 3ms */

        vruntime -= thresh;

        /* 잠에서 깬 태스크의 vruntime을 min_vruntime - thresh 하한선으로 클램핑! */
        vruntime = max_vruntime(se->vruntime, vruntime);
    }

    se->vruntime = vruntime;
}
```

### 5.1 클램핑 공식

깨어난 태스크의 $vruntime$은 다음 공식에 의해 조정됩니다:

$$vruntime \leftarrow \max(vruntime, \text{min\_vruntime} - \frac{\text{sched\_latency}}{2})$$

### 5.2 절묘한 밸런스: 반응성 보너스와 기아 방지

`sched_latency`가 6.0ms인 환경에서 임계값 $\text{thresh} = 3.0$ms입니다:
1. **인터랙티브 반응성 보장 (Latency Bonus)**:
   - 깨어난 `audio`의 $vruntime$은 $\text{min\_vruntime} - 3.0 = 57.0$ms로 보정됩니다.
   - 당시 실행 중이던 `worker`의 $vruntime$은 60.0ms이므로, $57.0 < 60.0$ 조건에 의해 **`audio`가 즉시 `worker`를 선점(Preempt)하여 CPU를 잡습니다.**
   - 덕분에 사용자 키보드 입력이나 사운드 버퍼 전송이 지연 없이 극도로 빠르게 반응합니다!
2. **CPU 독점 방지 (Monopoly Prevention)**:
   - `audio`가 누릴 수 있는 어드밴티지는 정확히 3.0ms뿐입니다.
   - `audio`가 3ms를 실행하고 나면 $vruntime$이 $57.0 + 3.0 = 60.0$ms가 되어 `worker`와 동등해집니다.
   - 이후 두 태스크는 1ms~2ms 단위로 공정하게 교대(Interleaving) 실행되므로, `worker`는 최대 3~4ms 이상 굶주리지 않습니다 (`INTERACTIVE_SLEEPER_FAIR_RESPONSE`)!

---

## 6. 실무 요약 및 성능 튜닝 지표

| 지표 / 설정 항목 | 설명 및 영향 | 권장 설정 / 커널 기본값 |
| :--- | :--- | :--- |
| `sched_latency_ns` | 모든 실행 가능 태스크가 적어도 한 번씩 CPU를 돌려받는 목표 주기 | 기본 6ms (`6000000`) |
| `sched_min_granularity_ns` | 태스크가 선점당하기 전에 보장받는 최소 연속 실행 시간 (컨텍스트 스위칭 오버헤드 방지) | 기본 0.75ms ~ 1ms |
| `FAIR_SLEEPERS` / `GENTLE_FAIR_SLEEPERS` | 슬리퍼 태스크의 $vruntime$ 보너스를 절반으로 제한하는 기아 방지 플래그 | 항상 활성화 (`sysctl /sys/kernel/debug/sched_features`) |
| `max_wait_latency_ms` | 실행 큐에서 CPU를 기다린 최대 지연 시간. 슬리퍼 페어니스가 꺼지면 수십~수백 ms로 폭증 | 10ms 이하 유지 필수 |
