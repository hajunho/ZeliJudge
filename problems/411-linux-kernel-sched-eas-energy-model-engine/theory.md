# 이론 문서 411: Linux 커널 EAS(Energy Aware Scheduling) 및 이종 멀티코어 전력 최적화 아키텍처

## 1. 개요 및 배경: 모바일 컴퓨팅의 패러다임 변화와 처리량 vs 전력의 대립

컴퓨팅 역사의 초기부터 데스크톱과 서버 운영체제의 CPU 스케줄러(O(1) 스케줄러, CFS)는 단 하나의 궁극적 목표를 위해 최적화되었습니다: **"시스템 전체의 연산 처리량(Throughput) 극대화와 태스크 간 공정성(Fairness)"**. 모든 CPU 코어가 동일한 마이크로아키텍처와 전력 특성을 가진 대칭형 멀티프로세싱(SMP) 환경에서는, 실행 큐(Runqueue)의 부하를 모든 코어에 균등하게 분산시키는 것만이 최선의 전략이었습니다.

그러나 배터리로 구동되는 모바일 스마트폰, 웨어러블, 자율주행 차량용 엣지 SoC의 출현은 이 전제를 완전히 무너뜨렸습니다:
1. **이종 컴퓨팅(Heterogeneous Computing)**: Arm big.LITTLE 및 DynamIQ 아키텍처는 고효율의 저전력 코어(LITTLE)와 광폭 슈퍼스칼라 고성능 코어(BIG/PRIME)를 단일 칩 위에 통합하였습니다.
2. **비선형적 전력 소비 곡선 (Non-linear Power Curve)**: CMOS 반도체의 동적 소비 전력은 주파수와 전압의 제곱에 비례합니다 ($P \propto C \cdot V^2 \cdot f$). 고성능 빅 코어의 최대 클럭 동작은 리틀 코어 대비 단위 연산당 5배에서 최대 10배 이상의 에너지를 소모합니다.
3. **CFS의 한계**: 기존 CFS는 코어 간 에너지 차이를 인지하지 못하므로, 가벼운 틱(Tick) 타이머나 백그라운드 워커를 부하가 적다는 이유로 빅 코어에 스케줄링하여 배터리를 불필요하게 낭비했습니다.

이를 해결하기 위해 리눅스 커널은 하드웨어 전력 모델을 스케줄링 경로의 일급 객체(First-class Citizen)로 승격시킨 **EAS (Energy Aware Scheduling, `kernel/sched/fair.c`, `CONFIG_ENERGY_MODEL`)**을 도입하였습니다.

---

## 2. Linux 커널 에너지 모델(Energy Model, EM) 프레임워크

EAS의 기반이 되는 것은 커널 내부의 **Energy Model (`include/linux/energy_model.h`, `kernel/sched/energy.c`)** 서브시스템입니다. 디바이스 트리(Device Tree)나 ACPI 테이블로부터 플랫폼의 전력 측정 데이터를 로드하여 다음과 같은 구조로 관리합니다:

```
+==================================================================================================+
|                        Linux Kernel Energy Model Topology                                        |
+==================================================================================================+

   [ SoC Platform (e.g. Octa-Core Tri-Cluster) ]
     |
     +---> Performance Domain 0 (LITTLE: CPUs 0, 1, 2, 3) - Shared DVFS
     |       OPP 0:  800 MHz | Capacity: 150 | Power:  30 mW
     |       OPP 1: 1600 MHz | Capacity: 300 | Power: 100 mW
     |
     +---> Performance Domain 1 (MID: CPUs 4, 5, 6) - Shared DVFS
     |       OPP 0: 1200 MHz | Capacity: 350 | Power: 200 mW
     |       OPP 1: 2200 MHz | Capacity: 650 | Power: 600 mW
     |
     +---> Performance Domain 2 (PRIME: CPU 7) - Independent DVFS
             OPP 0: 1500 MHz | Capacity:  500 | Power:  500 mW
             OPP 1: 3200 MHz | Capacity: 1024 | Power: 1800 mW
+==================================================================================================+
```

### 2.1 성능 도메인(Performance Domain, PD)의 의미
- 도메인 내의 모든 CPU는 클럭 발생기(PLL)와 전압 레귤레이터를 물리적으로 공유합니다.
- 따라서 한 도메인 내에서 단 하나의 코어만이라도 최대 연산 성능을 요구하면, 도메인 내의 다른 모든 코어도 동일한 높은 전압/주파수(OPP)로 동작해야만 합니다.
- EAS는 이 하드웨어적 제약을 완벽히 인지하여, 특정 코어에 태스크를 추가했을 때 해당 도메인 전체의 OPP 상승으로 인한 부수적 전력 증가(Spillover Power)까지 정확히 계산합니다.

---

## 3. 용량 마진(Capacity Margin)과 과부하(Overutilized) 티핑 포인트

EAS는 무조건 에너지만 아끼는 극단적인 절전기가 아닙니다. 사용자 인터랙션의 부드러움(60fps/120fps UI)과 연산 마감 시간(Deadline)을 보장하기 위해 정교한 **임계치 제어**를 수행합니다:

```
                      CPU Utilization Level
   0% ------------------------ 80% (Capacity Margin) ------------------------ 100%
      [    EAS ACTIVE        ] | [       OVERUTILIZED / CFS FALLBACK        ]
      Energy-optimal placement | Throughput is endangered!
      fits_capacity() = TRUE   | Disable Energy Model, Balance Load evenly!
```

### 3.1 80% 용량 마진 (`fits_capacity()`)
- 태스크 가동률과 코어 현재 가동률의 합이 해당 코어 최대 용량의 80%를 넘지 않아야 합니다:
  $$u_{cpu} + u_{task} \le 0.8 	imes C_{max}$$
- 80%를 초과하는 부하가 인가되면 주파수 스케일링(Schedutil) 거버너가 최대 OPP로 고정되며 열 쓰로틀링(Thermal Throttling) 위험이 커집니다.
- 따라서 80% 마진을 넘는 무거운 태스크는 리틀 코어에 머무르지 못하고 즉시 미드/빅 코어로 승격(Upscaling)됩니다.

### 3.2 Overutilized 상태와 CFS 폴백
- 시스템 내의 단 하나의 CPU라도 80% 용량 마진을 초과하면, 시스템은 **OVERUTILIZED** 플래그를 세웁니다.
- 과부하 상태는 시스템이 이미 에너지를 고려할 여유가 없으며, 태스크 큐의 지연 시간(Queueing Latency)이 폭증하여 시스템 응답성이 붕괴될 위기에 처했음을 의미합니다.
- 이때 커널은 EAS 알고리즘을 완전히 바이패스하고, 즉시 전통적인 CFS 부하 분산 로직으로 복귀하여 모든 활성 CPU에 연산량을 넓게 분산(Load Spreading)시킵니다.

---

## 4. 캐시 친화도(Cache Affinity)와 에너지 절감 마진

태스크가 이전에 실행되었던 `prev_cpu`에서 다른 CPU로 마이그레이션되면, L1 명령어/데이터 캐시 및 L2 캐시가 무효화되어 메모리 버스 트래픽과 캐시 리필(Cache Refill) 지연이 발생합니다.

EAS는 이를 방어하기 위해 **에너지 마진 임계값 (`energy_margin_mw`)**을 둡니다:
$$\Delta E = E(prev\_cpu) - E(best\_cand)$$
- $\Delta E > energy\_margin\_mw$: 에너지 절감 효과가 캐시 미스로 인한 손실을 상회하므로 마이그레이션을 단행합니다.
- $\Delta E \le energy\_margin\_mw$: 절감되는 전력이 미미하므로 캐시 웜(Cache Warm) 상태를 유지하기 위해 `prev_cpu`에 잔류합니다.

---

## 5. 실무 모바일 시스템 튜닝 (Android SchedTune / uclamp)

현대 안드로이드 OS는 EAS 스케줄러 상단에 **uclamp (Utilization Clamping / `kernel/sched/core.c`)** 계층을 운영합니다:
1. **Top-App (전경 UI 앱)**: `uclamp.min`을 인위적으로 높여, 가벼운 터치 입력이라도 리틀 코어가 아닌 미드/빅 코어로 선제적 배치(Latency-sensitive Boosting)되도록 유도합니다.
2. **Background (백그라운드 동기화)**: `uclamp.max`를 제한하여, 아무리 연산량이 많아도 빅 코어로 승격되지 못하고 리틀 코어에 묶이도록(Cap to LITTLE) 강제함으로써 배터리를 극단적으로 보존합니다.
