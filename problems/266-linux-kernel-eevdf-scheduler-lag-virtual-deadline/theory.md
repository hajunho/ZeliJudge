# [이론 및 배경] CFS의 한계와 리눅스 6.6 EEVDF 스케줄러의 수학적 설계

## 1. CFS의 탄생과 16년 만의 종말

2007년 리눅스 2.6.23에 도입된 **CFS(Completely Fair Scheduler)**는 이전의 $O(1)$ 스케줄러를 대체하며 큰 성공을 거두었습니다.
CFS의 핵심 철학은 **"이상적인 멀티태스킹 하드웨어(Ideal Multi-tasking Hardware)"**의 모사였습니다:
- 모든 태스크는 자신의 가중치 $w_i$에 비례하여 동등한 속도로 진행해야 합니다.
- 각 태스크의 누적 가상 실행 시간 $vruntime_i$를 레드-블랙 트리(Red-Black Tree)에 정렬하고, 항상 트리의 가장 왼쪽 노드(`min_vruntime`)를 꺼내어 실행합니다.

### CFS의 치명적 결함: 지연시간 보장의 부재
CFS의 $vruntime$ 추종 방식은 장기적인 **처리량 공평성(Throughput Fairness)**만을 보장할 뿐, 특정 시점에서의 **응답 지연시간(Latency Bound)**을 보장할 수 없었습니다:
- 오디오 처리(PipeWire, JACK)나 대화형 UI 태스크는 아주 짧은 시간($0.5\text{ms}$)만 CPU를 쓰면 되지만, 바로 그 순간에 즉시 실행되어야 언더런(Xrun)이나 끊김(Glitch)이 발생하지 않습니다.
- CFS에서는 CPU-bound 배치 태스크가 타임슬라이스를 다 쓸 때까지 기다려야 하거나, 반대로 휴리스틱 프리엠션이 과도하게 개입하여 배치 작업의 캐시 국소성(Cache Locality)을 파괴하고 잦은 컨텍스트 스위칭 오버헤드를 초래했습니다.

---

## 2. EEVDF: 공평성과 지연시간의 수학적 통합

피터 훈(Peter Hoon)이 1995년 발표하고 피터 질스트라가 리눅스 6.6에 구현한 **EEVDF(Earliest Eligible Virtual Deadline First)**는 공평성(Fairness)과 지연시간(Latency)을 명쾌하게 분리했습니다:

### 1) 가상 시간 $V$와 래그(Lag)
- 런큐 가상 시간 $V$: 실행 가능한 작업들의 가중치 합에 의해 진행됩니다.
- 작업 $i$의 래그:
  $$lag_i = V - vruntime_i$$
- **적격성(Eligibility)**:
  $$lag_i \ge 0 \iff vruntime_i \le V$$
  - $lag_i \ge 0$인 작업만이 실행 자격을 얻습니다. 이미 자기 몫 이상을 실행한 작업($lag_i < 0$)은 다른 작업들이 자신의 몫을 채울 때까지 기다려야 합니다.

### 2) 가상 데드라인(Virtual Deadline)
- 각 작업은 자신의 특성에 맞는 레이턴시 슬라이스 $q_i$를 요청합니다:
  $$d_i = vruntime_i + q_i \cdot \frac{1024}{w_i}$$
- **스케줄링 규칙**: EEVDF는 오직 **적격한($lag_i \ge 0$) 작업들 중에서 가장 이른 데드라인($\min d_i$)**을 가진 작업을 선택합니다.
- 슬라이스 $q_i$가 작을수록(예: $1\text{ms}$) 데드라인이 가까워져 즉시 CPU를 선점하지만, 슬라이스가 끝나면 $vruntime$이 증가하여 다음 턴에는 데드라인이 밀리므로 장기적인 CPU 점유율은 완벽히 가중치 비율에 수렴합니다.

---

## 3. 슬리퍼(Sleeper) 처리와 래그 감쇠(Lag Decay)

CFS에서는 오랜 시간 슬립한 프로세스가 깨어날 때 `vruntime = min_vruntime - latency_target`으로 인위적으로 $vruntime$을 낮추어 주었습니다.
이는 슬리퍼 태스크가 깨어나는 순간 다른 모든 배치 작업을 짓밟고 CPU를 독차지하는 **스파이크 현상(Thundering Herd & Latency Thievery)**을 낳았습니다.

EEVDF에서는:
- 작업이 슬립할 때의 래그를 보존하되, 슬립 기간 $\Delta t$에 따라 지수 감쇠($e^{-\Delta t / \tau}$)시킵니다.
- 깨어난 작업은 자신의 감쇠된 래그만큼만 우선권을 행사하므로, 인터랙티브 작업의 즉각적인 응답성을 보장하면서도 배치 작업의 기아(Starvation)를 완벽히 차단합니다.
