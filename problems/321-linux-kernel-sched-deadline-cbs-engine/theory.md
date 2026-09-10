# SCHED_DEADLINE 실시간 스케줄러의 이론적 배경과 커널 구현 (kernel/sched/deadline.c)

## 1. 고정 우선순위 실시간 스케줄링(POSIX RT)의 한계

리눅스 커널의 전통적인 실시간 스케줄링 클래스인 `SCHED_FIFO`와 `SCHED_RR`은 POSIX.1b 표준을 따르며, 1부터 99까지의 정적 우선순위(Static Priority)를 사용합니다.

그러나 정적 우선순위 방식은 실무에서 치명적인 한계를 드러냈습니다:
1. **CPU 기아 및 시스템 정지 (Starvation Hazard)**: 우선순위 99인 `SCHED_FIFO` 태스크 내부에서 무한 루프나 블로킹 버그가 발생하면, 커널 워커 스레드(`ksoftirqd`, `rcu`, `migration`)와 쉘 세션까지 전부 멈추어 시스템 전체가 먹통이 됩니다. 이를 막기 위해 `sysctl`의 `sched_rt_runtime_us` 트릭이 도입되었으나 임시방편에 불과했습니다.
2. **우선순위 역전 및 비율 단조 스케줄링(RMS)의 비효율**: 류와 레일랜드(Liu & Layland, 1973)의 정적 주기 스케줄링(Rate Monotonic Scheduling)은 주기가 짧을수록 높은 우선순위를 부여하지만, 이용률 상한선이 $U \le n(2^{1/n} - 1) pprox 69.3\%$에 불과하여 CPU 자원의 $30\%$ 이상을 낭비해야 했습니다.

---

## 2. EDF(Earliest Deadline First)와 100% 자원 최적성

류와 레일랜드가 증명한 동적 우선순위 알고리즘인 **EDF(Earliest Deadline First)**는 매 스케줄링 순간마다 **가장 마감시간이 임박한 태스크**에게 동적으로 최우선권을 부여합니다.

- **이론적 최적성(Optimality)**: 단일 프로세서에서 선점형 EDF는 태스크들의 총 대역폭 $\sum (Q_i / P_i) \le 1.0$을 만족하는 한, **어떠한 마감시간 위반(Deadline Miss)도 없이 100% CPU 대역폭을 완전히 활용할 수 있는 최적의 스케줄러**입니다.
- 어떤 다른 스케줄러가 스케줄할 수 있는 태스크 세트라면, EDF는 반드시 스케줄할 수 있습니다.

---

## 3. CBS (Constant Bandwidth Server): 실시간 격리의 핵심

순수 EDF의 치명적 취약점은 하나의 태스크가 약속된 실행 시간 $Q_i$를 초과하여 실행될 경우, 시스템 전체의 마감시간이 도미노처럼 연쇄 붕괴(Domino Effect / Deadline Catastrophe)한다는 점입니다.

이를 완벽히 해결하기 위해 아베니와 부타초(Luca Abeni & Giorgio Buttazzo, 1998)는 **CBS (Constant Bandwidth Server)** 이론을 제안했습니다.
- 각 실시간 태스크를 하나의 "가상 대역폭 서버"로 감싸며, 태스크가 약속된 $Q_i$ 시간을 소진하면 가차 없이 **쓰로틀링(`THROTTLED`)**하여 CPU에서 퇴출합니다.
- 태스크는 자신의 절대 마감시간 $d_i$가 도래하기 전까지는 절대로 다시 CPU를 점유할 수 없습니다.
- 이를 통해 각 태스크는 다른 태스크의 버그나 과부하로부터 완벽한 **시간적 격리(Temporal Isolation)**를 보장받습니다.

---

## 4. 리눅스 커널 `kernel/sched/deadline.c` 아키텍처

리눅스 커널 3.14에 합류한 `dl_sched_class`는 다음과 같은 고성능 아키텍처로 구현되었습니다:

1. **레드-블랙 트리 기반 런큐 (`dl_rq`)**:
   - `rb_node`의 키는 태스크의 절대 마감시간 `dl_se->deadline`입니다.
   - `__pick_first_dl_entity()`는 $O(1)$(캐시된 최좌측 노드)로 가장 빠른 마감시간 태스크를 선택합니다.
2. **hrtimer 기반 쓰로틀링 타이머 (`dl_timer`)**:
   - 예산이 고갈된 태스크는 런큐에서 제거되고, 마감시간 $d_i$에 트리거되는 고해상도 타이머 `hrtimer`에 등록됩니다.
   - 타이머 콜백 `dl_task_timer()`가 실행되면 예산이 보충되고 태스크가 다시 `dl_rq`로 삽입(Enqueue)됩니다.
3. **CBS 기상 검사 (Wake-up Rule)**:
   - 태스크가 수면 상태에서 깨어날 때, 커널은 $t + (q/Q) 	imes D < d_{abs}$ 공식을 검사합니다.
   - 이 규칙은 태스크가 짧은 슬립을 취했을 때는 자신의 기득권을 보존해주고, 너무 긴 슬립으로 마감시간이 낡아버렸을 때는 새로운 마감시간으로 연기하여 신규/기존 태스크 간의 공정성을 완벽하게 유지합니다.
4. **글로벌 인가 제어 (`sched_dl_overflow()`)**:
   - `sched_setattr()` 시스템 콜 호출 시, 커널은 현재 시스템의 총 대역폭을 검사하여 `sysctl_sched_rt_runtime / sysctl_sched_rt_period` (기본 95%)를 넘지 않도록 인가 제어를 엄격히 집행합니다.

오늘날 `SCHED_DEADLINE`은 자율주행 자동차(ROS 2 / AUTOSAR), 로보틱스 모터 제어, 항공우주 비행 제어 및 전문가용 저지연 오디오/비디오(JACK / PipeWire) 파이프라인의 핵심 커널 기술로 활용되고 있습니다.
