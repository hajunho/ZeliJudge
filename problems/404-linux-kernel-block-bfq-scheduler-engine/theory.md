# 심층 이론: Linux 커널 블록 레이어 BFQ(Budget Fair Queueing) 스케줄러 내부 구조와 B-WF2Q+ 수학적 원리

---

## 1. 리눅스 블록 I/O 스케줄러의 진화와 패러다임 변화

전통적인 단일 큐(Legacy Single-Queue) 시절부터 현대의 멀티 큐(blk-mq, Multi-Queue Block Layer) 아키텍처에 이르기까지 리눅스 커널의 블록 I/O 스케줄러는 스토리지 하드웨어의 발전 속도에 맞춰 끊임없이 진화해 왔습니다.

| 스케줄러 | 도입 커널 | 코어 알고리즘 | 최적 타깃 디바이스 | 주요 한계점 |
| :--- | :--- | :--- | :--- | :--- |
| **No-op / None** | Linux 2.6 | 단순 FIFO / 머지(Merge)만 수행 | 하드웨어 큐가 강력한 고속 NVMe | 프로세스 간 서비스 격리 및 QoS 부재 |
| **Deadline / mq-deadline** | Linux 2.6 | LBA 정렬 레드-블랙 트리 + 기아 방지 FIFO | 범용 서버, 낮은 CPU 오버헤드 | 가중치 기반 대역폭 비례 분배 불가 |
| **CFQ (Completely Fair)** | Linux 2.6.13 | 시간 슬라이스(Time Slice) 기반 라운드 로빈 | 회전식 디스크(HDD) | 플래시 SSD의 비대칭 처리량 및 시간 불공정 |
| **Kyber** | Linux 4.12 | 목표 읽기/동기 지연 시간 피드백 제어 | 초고속 NVMe SSD | 엄격한 최악 지연 상한 보장 불가 |
| **BFQ (Budget Fair)** | Linux 4.12 | $B-WF^2Q+$ (섹터 예산 기반 공정 큐잉) | 데스크톱, 모바일(Android), 다중 테넌트 | 복잡한 가상 시간 계산으로 인한 연산 오버헤드 |

CFQ의 치명적 결함은 **"시간 슬라이스"**에 있었습니다. 회전식 자기 디스크(HDD)에서는 헤드가 디스크의 외주(Outer track)에 위치하는지 내주(Inner track)에 위치하는지에 따라 100ms 동안 읽을 수 있는 데이터 양이 최대 2배 차이가 납니다. 플래시 메모리(SSD)에서는 상황이 더욱 극단적입니다. 연속된 블록을 읽는 프로세스는 100ms 동안 수백 메가바이트를 읽을 수 있지만, 무작위 4KB 쓰기를 수행하는 프로세스는 가비지 컬렉션(GC)이나 블록 소거 오버헤드로 인해 수 메가바이트밖에 전송하지 못합니다. 결국 시간 기반 슬라이스는 서비스 단위(데이터 볼륨)의 극심한 불공정을 초래했습니다.

**BFQ(Budget Fair Queueing)**는 서비스의 단위를 시간이 아닌 **섹터(Sector, 512B 바이트 단위)**로 정의함으로써 이 문제를 완벽하게 해결했습니다.

---

## 2. B-WF2Q+ 알고리즘의 수학적 증명과 최악 지연 보장

BFQ의 핵심 수학적 기반은 Jon C. R. Bennett과 Hui Zhang이 1996년에 발표한 **$WF^2Q+$ (Worst-case Fair Weighted Fair Queueing)**입니다. Paolo Valente는 이를 스토리지 블록 장치의 디스크 헤드 시크 및 플래시 내부 큐잉 특성에 맞게 패킷 크기 대신 **섹터 예산($B_i$)**을 사용하는 $B-WF^2Q+$로 정립했습니다.

### 2.1 가상 시간(Virtual Time)의 정의와 단조성

이상적인 GPS(Generalized Processor Sharing) 모델에서는 모든 활성 흐름(Active Flow)이 자신의 가중치 비율에 따라 동시에 유체를 흘려보내듯 서비스를 받습니다. 그러나 패킷이나 디스크 섹터는 원자적(Atomic)으로 전송되어야 합니다.

시스템 가상 시간 $V(t)$는 시스템이 제공한 실제 누적 서비스를 활성 가중치들의 합으로 정규화한 값입니다:

$$\frac{dV(t)}{dt} = \frac{\sum_{i \in \text{active}} r_i(t)}{\sum_{i \in \text{active}} W_i}$$

여기서 $r_i(t)$는 실제 스토리지 장치가 엔티티 $i$에 전달한 데이터 전송률(Sectors/sec)입니다. 이산 사건(Discrete Event) 관점에서 엔티티 $i$가 $\Delta s$ 섹터의 서비스를 완료하면 가상 시간은 다음과 같이 증가합니다:

$$V(t + \Delta t) = V(t) + \frac{\Delta s}{\sum_{k \in \text{active}} W_k}$$

### 2.2 적격성(Eligibility)과 최악 지연 상한 (Worst-Case Lag Bound)

일반적인 WFQ(Weighted Fair Queueing)는 단순히 완료 가상 시각($F_i$)이 가장 빠른 엔티티를 선택합니다. 하지만 이 경우 아직 자기 차례가 오지 않은(미래의) 대량 예산 엔티티가 디바이스를 미리 선점하여 다른 작은 엔티티의 지연 시간을 폭증시키는 문제가 발생합니다.

$WF^2Q+$는 **적격성 조건(Eligibility Condition)**을 추가하여 이를 방지합니다:

$$S_i \le V(t)$$

엔티티 $i$의 가상 시작 시각 $S_i$가 현재 시스템 가상 시각 $V(t)$ 이하일 때만 해당 엔티티를 스케줄링 후보로 허용합니다.

- **가상 시작 시각**:
  $$S_i = \max\left(V(t_{\text{act}}), F_i^{\text{prev}}\right)$$
- **가상 완료 시각**:
  $$F_i = S_i + \frac{B_i}{W_i^{\text{eff}}}$$

이 적격성 조건을 통해 $B-WF^2Q+$는 임의의 시간 간격 $[t_1, t_2]$ 동안 엔티티 $i$가 이상적인 GPS 서비스 대비 뒤처지거나 앞서나가는 **서비스 래그(Service Lag, $\text{Lag}_i(t)$)**를 단일 최대 요청 크기 $L_{\max}$ 이내로 완벽히 억제합니다:

$$-\frac{L_{\max}}{W_{\min}} \le \text{Lag}_i(t) \le L_{\max}$$

---

## 3. 적응형 예산(Adaptive Budgeting)의 제어 이론적 메커니즘

BFQ는 정적 예산에 머무르지 않고, 각 큐의 I/O 소비 패턴을 관찰하여 실시간으로 예산 $B_i$를 동적으로 적응시킵니다(`bfq_bfqq_charge_budget`).

```
                          [ Dynamic Budget State Machine ]

                            +----------------------+
                            | Initial Allocation   |
                            | B_i = default_budget |
                            +----------------------+
                                       |
                   +-------------------+-------------------+
                   |                                       |
                   v                                       v
         [ Exhausted All Budget ]                [ Emptied with < 50% ]
                   |                                       |
                   v                                       v
         Double Budget:                          Downscale Budget:
         B_new = min(B_max, 2 * B)               B_new = max(B_min, max(consumed, B/2))
         (High Throughput Stream)                (Latency-Sensitive Burst)
```

1. **처리량 극대화 (Upscaling)**:
   - 연속된 대용량 읽기/쓰기를 수행하는 비디오 재생이나 데이터베이스 백업 프로세스는 할당받은 예산을 완전히 소진(`BUDGET_EXHAUSTED`)합니다.
   - 이때 스케줄러는 큐를 교체하는 대신 다음 턴의 예산을 $2 \times B_i$로 두 배 확대합니다 (최대 `max_budget`까지).
   - 이를 통해 잦은 큐 컨텍스트 스위칭과 디바이스 헤드 탐색 오버헤드를 획기적으로 줄여 스토리지 최대 대역폭에 도달합니다.
2. **저지연 보장 및 기아 방지 (Downscaling)**:
   - 반면 4KB 설정 파일을 읽거나 터미널에 키를 입력하는 대화형 프로세스는 256 섹터 중 8 섹터만 소비하고 큐가 비어버립니다(`EMPTY_NO_IDLE` 또는 `EMPTY_TIMEOUT`).
   - 스케줄러는 이 큐의 예산을 즉시 소비된 섹터 또는 절반으로 축소합니다 (최소 `min_budget`까지).
   - 이로 인해 다음에 이 큐가 깨어났을 때 가상 완료 시각 $F_i = S_i + \frac{B_i}{W_i}$가 훨씬 작아져, 서비스 트리 최전방에 빠르게 배치됩니다.

---

## 4. 예측적 유휴 대기(Anticipatory Idling)와 플래시 스토리지

동기식 I/O(Synchronous Read)를 수행하는 프로세스는 요청을 하나 디스크로 보낸 뒤, 블록 레이어의 반환을 기다려 CPU에서 다음 I/O 파라미터를 계산(Think-time)한 후 후속 요청을 보냅니다.

만약 프로세스가 요청 하나를 완료하여 큐가 잠시 비었을 때 스케줄러가 대기하지 않고 즉시 백그라운드 쓰기 큐로 넘어가 버리면:
1. 기계식 드라이브는 다른 실린더로 헤드를 이동(Seek)시키느라 수 밀리초를 낭비합니다.
2. SSD에서도 내부 채널 및 다이(Die)가 백그라운드 블록 쓰기로 점유되어, 잠시 후 도착할 대화형 읽기 요청이 수십 밀리초 동안 큐잉 지연을 겪습니다.

BFQ는 이를 방지하기 위해 **예측적 유휴 대기(Anticipatory Idling, `slice_idle`)** 타이머를 가동합니다. 인터랙티브 큐가 비었을 때 디바이스를 의도적으로 유휴(Idle) 상태로 보존함으로써, 프로세스가 계산을 마치고 발행하는 후속 요청을 제자리에서 즉시 처리합니다.

---

## 5. 저지연 가중치 부스팅(Weight-Raising) 휴리스틱

안드로이드 스마트폰에서 사용자가 화면을 스크롤하거나 앱을 터치할 때, 백그라운드에서는 앱 업데이트나 사진 동기화가 기가바이트 단위로 디스크에 쓰기를 수행하고 있을 수 있습니다.

BFQ의 저지연 엔진(`block/bfq-iosched.c: bfq_bfqq_save_state`)은 프로세스의 씽크 타임을 측정하여 대화형 특성을 감지합니다:
- **부스팅 발동 조건**:
  $$\Delta t_{\text{think}} = t_{\text{arrival}} - t_{\text{last\_completion}} \ge \text{think\_time\_threshold}$$
- **가중치 승격**:
  $$W_i^{\text{eff}} = \min(1000, W_i \times \text{wr\_boost\_factor})$$
  일반적으로 기본 가중치가 100인 큐가 일시적으로 최대 가중치인 **1000**으로 승격됩니다.
- **감쇠(Decay) 및 안전장치**:
  대화형으로 위장한 대용량 다운로더가 대역폭을 독점하는 것을 방지하기 위해, 누적 섹터가 `burst_sectors_threshold`를 넘어서는 순간 부스팅은 즉시 소멸하고 기본 가중치로 회귀합니다.
