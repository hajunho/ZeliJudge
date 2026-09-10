# 394: 리눅스 커널 CPU 스케줄링 — Core Scheduling(PR_SCHED_CORE)과 SMT 교차 하이퍼스레드 투기적 실행 부채널 공격 방어 이론

## 1. 개요 및 마이크로아키텍처 위협 모델 (Microarchitectural Threat Model)

### 1.1 SMT (Simultaneous Multi-Threading)의 자원 공유 구조
대칭형 멀티프로세싱(SMP)에서 개별 CPU 코어는 독립적인 레지스터 셋, ALUs, L1 캐시를 보유합니다. 그러나 인텔 하이퍼스레딩(Hyper-Threading) 및 AMD SMT로 대표되는 동시 멀티스레딩 환경에서는 단일 물리 코어의 연산 자원을 2개 이상의 가상 논리 프로세서(SMT Siblings)가 미세하게 시분할/동시 분배하여 사용합니다:
- **완전 분할(Partitioned) 자원**: 재정렬 버퍼(ROB), 로드/스토어 큐 엔트리 (일반적으로 스레드당 고정 할당)
- **동적 경쟁(Competitively Shared) 자원**: L1 데이터/명령어 캐시, 실행 파이프라인(ALU, FPU, 포트), TLB, 분기 대상 버퍼(BTB)
- **비동기 마이크로아키텍처 버퍼**: 라인 필 버퍼(Line Fill Buffer: LFB), 로드 포트 버퍼, 스토어-로드 포워딩 구조

### 1.2 교차 하이퍼스레드 투기적 실행 공격 (Cross-Thread Speculative Attacks)
2018년 이후 폭발적으로 발견된 하드웨어 취약점들은 물리 코어의 공유 마이크로아키텍처 상태를 악용합니다:
1. **L1TF (L1 Terminal Fault / Foreshadow, CVE-2018-3620)**: 게스트 OS가 비유효(P=0) 페이지 테이블 엔트리를 가리킬 때 CPU가 물리 주소를 투기적으로 변환하며 L1D 캐시 내용을 무차별적으로 읽어 들이는 취약점. 형제 스레드가 하이퍼바이저 메모리를 캐시에 올리면 옆 스레드 게스트가 이를 읽어 냅니다.
2. **MDS (Microarchitectural Data Sampling, ZombieLoad, RIDL, Fallout)**: L1D 캐시 미스가 발생하여 DRAM/L2로부터 데이터를 가져오는 동안 LFB(Line Fill Buffer)나 로드/스토어 버퍼에 임시 보관된 평문 데이터가, 동일 코어의 다른 SMT 스레드에서 실행되는 결함 인출 명령(Faulting Load)에 의해 일시적으로 노출되는 현상.
3. **Cross-Thread Branch Injection (Spectre v2)**: 동일 코어의 형제 스레드가 BTB를 오염시켜 타 스레드의 간접 분기(indirect branch)를 원하는 가젯으로 투기적 점프시키는 공격.

이러한 공격의 근본 원인은 **서로 신뢰하지 않는 테넌트(Untrusted Tenants)가 동일한 물리 코어의 SMT 형제로 동시에 스케줄링되기 때문**입니다.

---

## 2. Core Scheduling (`kernel/sched/core.c`) 아키텍처

리눅스 커널 5.14에서 도입된 Core Scheduling은 CPU 스케줄러의 의사결정 단위를 개별 논리 CPU에서 **물리 코어(Physical Core)** 전체로 격상시켰습니다.

### 2.1 코어 쿠키 (Core Cookie) 프리미티브
커널 내부에서 각 태스크는 64비트 정수 포인터 형태의 쿠키(`task_struct->core_cookie`)를 가집니다:
- `core_cookie == 0` (NULL): 태그되지 않은 기본 태스크 (Default untagged). 신뢰된 호스트 데몬 또는 레거시 프로세스.
- `core_cookie != 0`: 고유한 암호학적/포인터 보안 도메인 식별자. 동일 쿠키를 가진 태스크들만이 동일 물리 코어에서 공존할 수 있습니다.

`prctl(2)` 인터페이스:
```c
int prctl(PR_SCHED_CORE, int cs_cmd, pid_t pid, enum pid_type type, unsigned long *cookie);
```
- `PR_SCHED_CORE_CREATE`: 호출 프로세스에 고유 쿠키를 새로 생성하여 바인딩.
- `PR_SCHED_CORE_SHARE_TO`: 특정 대상 PID에 현재 태스크의 쿠키를 복제 부여.
- `PR_SCHED_CORE_SHARE_FROM`: 대상 PID로부터 쿠키를 전달받아 동기화.
- `PR_SCHED_CORE_RESET`: 쿠키를 제거하고 기본 0 상태로 환원.

### 2.2 이중 수준 스케줄링 (Two-Level Scheduling Algorithm)
전통적인 CFS 스케줄러는 각 CPU의 런큐(`rq`)에서 `pick_next_task()`를 독립적으로 호출하지만, Core Scheduling에서는 형제 스레드 간 조율을 수행합니다:

1. **로컬 후보 선정**:
   각 SMT 형제 스레드 $i$는 로컬 런큐에서 가장 실행 우선순위가 높은 태스크 $T_i$를 탐색합니다:
   $$T_i = rg\max_{T \in rq_i} 	ext{Priority}(T)$$
2. **코어 리더 선출 (Leader Election)**:
   물리 코어 $C$에 속한 모든 형제 후보 $\{T_0, T_1, \dots\}$를 비교하여, 전역적으로 가장 높은 우선순위를 지닌 태스크를 코어 리더 $T^*$로 선출합니다:
   $$T^* = rg\max_{i} 	ext{Priority}(T_i), \quad K^* = T^*.	ext{cookie}$$
3. **쿠키 매칭 및 스케줄링 결정**:
   각 형제 스레드 $j$에 대해:
   - $rq_j$에 $T.	ext{cookie} == K^*$인 실행 가능 태스크가 존재하면, 해당 태스크 중 최우선 태스크를 선별하여 실행(`RUNNING`).
   - 만약 $rq_j$에 $K^*$와 일치하는 태스크가 전혀 없고 상이한 쿠키를 가진 태스크만 존재한다면, 보안 정책에 따라 스레드 $j$를 즉시 **`FORCED_IDLE`** 처리합니다.

---

## 3. 강제 유휴 (Forced Idle)와 성능 비용 계량

### 3.1 강제 유휴 (Forced Idle)의 메커니즘
형제 스레드가 강제 유휴 상태에 들어갈 때, 커널은 해당 논리 CPU에 강제 정지 명령(IPI 발송 후 `sched_core_force_idle` 진입)을 내려 CPU 파이프라인에서 명령어가 디코드/인출되지 않도록 HLT 상태로 전환합니다.
이를 통해:
- L1 캐시 미스 발생 차단
- 라인 필 버퍼(LFB) 점유 해제
- 분기 예측기 오염 완전 차단
결과적으로 코어 리더 태스크 $T^*$는 물리 코어의 모든 하드웨어 버퍼를 독점하여 100% 안전하게 실행됩니다.

### 3.2 오버헤드 및 최적화
강제 유휴는 보안을 보장하지만 하이퍼스레드 연산 능력을 낭비하게 됩니다:
$$	ext{Efficiency} = 1.0 - 	ext{forced\_idle\_ratio}$$
클라우드 오케스트레이터(Kubernetes, OpenStack)는 동일 테넌트의 vCPU 스레드들을 동일한 코어 쿠키로 묶고 CPU 친화도(Affinity/NUMA)를 동일 물리 코어에 정렬시킴으로써, 강제 유휴 비율을 0%에 가깝게 유지하면서도 부채널 공격을 완전 방어할 수 있습니다.

---

## 4. 결론

리눅스 커널의 Core Scheduling은 마이크로아키텍처 하드웨어 결함에 대응하여 운영체제 소프트웨어 스케줄러가 제공할 수 있는 가장 우아하고 정교한 해법입니다.
본 시뮬레이션 엔진은 물리 코어-SMT 형제 구조, 리더 선출 알고리즘, 쿠키 일치 불변식 검증, 강제 유휴 사이클 정밀 계량을 모두 충족함으로써 차세대 보안 클라우드 커널의 핵심 원리를 완벽하게 실증합니다.
