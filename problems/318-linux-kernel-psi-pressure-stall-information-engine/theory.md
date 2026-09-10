# 리눅스 커널 PSI(Pressure Stall Information) 및 자원 체증 관측 이론 (Linux PSI Theory)

## 1. 기존 리눅스 자원 관측 지표의 한계

### 1.1 Load Average의 맹점
1970년대 유닉스 시절부터 존재하던 `loadavg`는 CPU 런큐에서 대기 중인 프로세스와 `TASK_UNINTERRUPTIBLE`(주로 디스크 I/O) 상태의 프로세스 개수를 합산한 지표입니다.
- **원인 불명**: 부하가 10으로 올랐을 때, 이것이 CPU 연산이 부족한 것인지, 느린 HDD I/O 병목인지, 네트워크 소켓 락인지 분간할 수 없습니다.
- **메모리 압박 침묵**: 시스템 메모리가 부족하여 커널이 페이지 캐시를 회수하거나 압축(zswap)하느라 마이크로초 단위의 미세 지연이 누적되어도, 프로세스가 장시간 블록되지 않는 한 `loadavg`에는 거의 잡히지 않습니다.

### 1.2 PSI(Pressure Stall Information)의 혁신 (Linux 4.20+)
페이스북(Meta)의 요하네스 바이너(Johannes Weiner)가 주도하여 리눅스 커널 메인라인에 안착시킨 PSI는 자원 포화도를 **"시간 손실(Wasted Execution Time)"**이라는 절대적 척도로 측정합니다.

---

## 2. Some vs Full 압력 모델

```
[ Dual-Level PSI Pressure Architecture ]

1. Some Pressure (CPU 공존형 부분 정체)
   Core 0: [ Task 1: RUNNING (계산 중) ]   <-- CPU는 일하고 있음!
   Core 1: [ Task 2: STALLED_MEM (회수 대기) ]
   ==> some = 100%, full = 0%

2. Full Pressure (전면적 생산성 마비 / 쓰레싱)
   Core 0: [ Task 1: STALLED_MEM (회수 대기) ]
   Core 1: [ Task 2: STALLED_MEM (회수 대기) ]
   ==> some = 100%, full = 100%  (Zero CPU Work Done!)
```

### 2.1 Full 압력의 임계성
- `some` 압력은 시스템이 바쁘게 돌아가며 병목이 발생하기 시작했음을 알리는 **경고(Warning)** 신호입니다.
- `full` 압력은 프로세스들이 서로의 자원을 빼앗으며(Thrashing) CPU가 공회전하는 **재앙(Catastrophe)** 신호입니다.
- 안드로이드의 `lowmemorykiller`와 쿠버네티스의 노드 압박 방어 데몬은 `full` 메모리 압력이 0을 넘어서는 순간 즉시 우선순위가 낮은 컨테이너를 사살(Kill)하여 시스템 전체 동결을 방어합니다.

---

## 3. 사용자 공간 트리거와 epoll 인터페이스

### 3.1 무부하 실시간 감시 (Zero-Overhead Epoll)
사용자 공간 데몬이 매초 `/proc/pressure/memory`를 읽는 폴링(Polling) 방식은 그 자체로 CPU와 메모리 오버헤드를 발생시킵니다.
리눅스 커널 PSI 트리거는 다음과 같이 작동합니다:
1. 데몬이 `poll()` / `epoll()` 시스템 콜을 호출하여 수면(Sleep) 상태에 들어갑니다.
2. 커널 스케줄러가 틱(Tick)마다 슬라이딩 윈도우 버킷의 스톨 누적치를 검사합니다.
3. 임계치(`threshold_us`)가 돌파되는 순간, 커널 인터럽트 컨텍스트에서 즉시 대기 큐(`wait_queue_head_t`)를 깨워 사용자 데몬을 호출합니다.
4. 이를 통해 마이크로초 단위의 레이턴시로 OOM 패닉이 발생하기 수백 밀리초 전에 선제적 조치(Pod 축출, 캐시 플러시, 트래픽 셰이핑)를 취할 수 있습니다.
