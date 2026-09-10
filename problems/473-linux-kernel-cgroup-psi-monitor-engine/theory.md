# 리눅스 커널 Cgroup v2 PSI(Pressure Stall Information) 아키텍처 이론

## 1. 기존 리소스 지표의 근본적 한계와 PSI의 탄생

전통적인 Linux 지표는 자원의 '점유율(Utilization)'만을 보여줄 뿐, 시스템이 유의미한 작업을 처리하지 못하고 낭비되는 '정체 시간(Stall Time)'을 정량화하지 못했습니다:
- **Load Average**: 디스크 I/O 대기(D-상태) 프로세스까지 무차별 합산하여 고속 NVMe 환경에서는 왜곡이 발생함.
- **Free Memory**: 리눅스는 남는 RAM을 전부 페이지 캐시로 활용하므로 유휴 메모리가 거의 0에 수렴하는 것이 정상적이지만, 단순 모니터링은 이를 가양성(False Positive) OOM 위험으로 오판함.

이에 따라 리눅스 4.20 커널에 도입된 **PSI(Pressure Stall Information)**는 자원 기아로 인해 태스크가 차단된 순수 지연 시간을 CPU 시간의 백분율로 산출하는 혁신적 프레임워크입니다.

---

## 2. SOME vs FULL 스톨의 수학적 모델

어떤 관측 시간 구간 $T$ 동안:
1. **SOME 압박**:
   $$	ext{SOME} = rac{\Delta t(	ext{at least one task stalled})}{T}$$
   일부 스레드가 메모리 직접 회수(Direct Reclaim)나 I/O 대기에 묶여 있으나, 다른 CPU 코어는 활발히 작업 중인 상태입니다.
2. **FULL 압박**:
   $$	ext{FULL} = rac{\Delta t(	ext{ALL active non-idle tasks stalled})}{T}$$
   모든 활성 스레드가 동시에 자원 대기에 묶여 CPU가 완전히 유휴 상태(Wasted Idle)가 된 상태입니다. 
   - 시스템이 물리적 RAM 한계를 초과하여 디스크 스왑 쓰레싱(Thrashing)에 빠졌음을 알리는 가장 확실한 지표입니다.
   - **CPU 압박에 FULL이 없는 이유**: CPU를 기다리는 태스크가 있더라도 최소 1개의 태스크가 CPU를 점유하여 유의미한 연산을 진행하고 있으므로, CPU 사이클 자체가 100% 낭비되는 'FULL 스톨'은 수학적으로 성립하지 않습니다.

---

## 3. 슬라이딩 윈도우 트리거와 유저 공간 OOM 킬러 (`systemd-oomd`)

### 3.1 커널 내부 트리거 메커니즘 (`kernel/sched/psi.c`)
- 커널은 감시 대상 Cgroup에 대해 `pollfd`를 등록받고, 10ms~2초 범위의 슬라이딩 윈도우(`window_us`)와 정체 시간 임계치(`threshold_us`)를 유지합니다.
- 태스크 스케줄링 문맥 전환(`finish_task_switch()`) 및 상태 변경 시점마다 스톨 플래그를 비트마스크로 갱신합니다.
- 임계치 도달 시 커널은 `epoll` 이벤트를 발송하고, 윈도우 크기에 비례하는 쿨다운(Cooldown) 구간 동안 중복 이벤트를 억제하여 인터럽트 폭풍을 방어합니다.

### 3.2 systemd-oomd / Android lmkd 아키텍처
과거 커널 OOM Killer는 전체 시스템 메모리가 고갈된 최후의 순간에야 동작하여 커널 락 경합 및 대규모 프리징을 초래했습니다.
반면 현대 클라우드/컨테이너 아키텍처에서는:
1. `systemd-oomd`가 `cgroup.pressure`의 `full` 스톨 100ms/1s를 모니터링.
2. 스톨 윈도우가 임계치를 넘으면 즉시 경보 수신.
3. Cgroup 내 `memory.current`가 가장 크거나 메모리 누수가 의심되는 컨테이너를 선제적으로 우아하게(Gracefully) 재시작하거나 종료하여 호스트 전체 붕괴를 원천 방어합니다.
