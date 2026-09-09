# 리눅스 커널 blk-mq 블록 레이어: NVMe 멀티큐 아키텍처와 I/O 스케줄러(none, mq-deadline, kyber, bfq) 분석

## 1. 개요: 단일 큐 스토리지에서 멀티큐(blk-mq) NVMe로의 혁명

과거 수십 년간 리눅스 커널의 블록 레이어는 회전식 하드 디스크 드라이브(HDD)와 초창기 SATA/SAS SSD를 위해 설계된 **레거시 단일 큐(Single-Queue) 블록 계층**을 사용했습니다.

이 구조에서는 모든 CPU 코어가 단 하나의 전역 큐 락(`q->queue_lock`)을 획득해야만 I/O 요청을 제출할 수 있었습니다. I/O 처리에 수 밀리초($1 \sim 10\,\text{ms}$)가 걸리던 시절에는 락 경합이 큰 문제가 되지 않았으나, 초당 수십만~수백만 IOPS를 처리하고 지연시간이 수십 마이크로초($20 \sim 50\,\mu\text{s}$)에 불과한 **초고속 PCIe NVMe SSD**가 등장하면서 전역 락은 심각한 CPU 병목 지점으로 전락했습니다.

리눅스 커널 3.13부터 도입된 **`blk-mq` (Multi-Queue Block Layer)**는 이 병목을 완벽히 제거하기 위해 **2계층 큐잉 아키텍처**를 수립했습니다:

```
[애플리케이션 스레드 (64 CPU Cores)]
   │        │        │        │
   ▼        ▼        ▼        ▼
┌──────────────────────────────────────┐
│  Per-CPU Software Queues (ctx)       │  <=== CPU 코어별 락리스(Lockless) 큐잉!
│  [sw_q 0]  [sw_q 1] ... [sw_q 63]    │
└──────────────────┬───────────────────┘
                   │
         [I/O Scheduler 레이어]
         (none / kyber / mq-deadline / bfq)
                   │
                   ▼
┌──────────────────────────────────────┐
│  Hardware Dispatch Queues (hctx)     │  <=== NVMe 하드웨어 큐와 1:1 또는 N:M 매핑!
│  [hw_q 0]  [hw_q 1] ... [hw_q 31]    │
└──────────────────┬───────────────────┘
                   │  DMA Submission
                   ▼
┌──────────────────────────────────────┐
│  NVMe Controller Hardware SQs / CQs  │  <=== 최대 64,000개 하드웨어 큐 동시 처리!
└──────────────────────────────────────┘
```

---

## 2. 4대 I/O 스케줄러 알고리즘 심층 비교

I/O 스케줄러는 소프트웨어 스테이징 큐(`ctx`)에서 하드웨어 디스패치 큐(`hctx`)로 I/O 요청을 전달하는 방식을 결정합니다:

### 2.1 `none` (No-op blk-mq)
- **개념**: 소프트웨어 스케줄러 레이어를 **완전히 바이패스(Bypass)**합니다.
- **동작 원리**: CPU 코어별 소프트웨어 큐에 들어온 I/O 요청을 어떤 정렬, 병합, 지연도 거치지 않고 대응하는 NVMe 하드웨어 제출 큐(SQ)로 즉시 락리스 직결합니다.
- **장점**: CPU 스핀락 오버헤드가 $0.1 \sim 0.2\%$ 미만이며, 디바이스의 물리적 최대 한계치(800,000 ~ 1,200,000 IOPS)와 초저지연($50\,\mu\text{s}$)을 $100\%$ 추출합니다.
- **단점**: 커널 레벨의 우선순위 제어가 없으므로, 백그라운드 쓰기(예: RocksDB 컴팩션, 체크포인트)가 수십만 IOPS로 몰아칠 경우 하드웨어 큐가 포화되어 대화형 쿼리 읽기 꼬리 지연시간(Tail Latency)이 $15\,\text{ms}$ 이상으로 튈 수 있습니다.
- **적용 대상**: 순수 읽기 전용 캐시, 고성능 전용 DB 서버, 고르게 분산된 NVMe 워크로드.

---

### 2.2 `kyber` (Meta / Facebook 저지연 적응형 스케줄러)
- **개념**: Jens Axboe가 페이스북의 프로덕션 워크로드를 위해 개발한 **지연시간 목표 기반 적응형 멀티큐 스케줄러**입니다.
- **동작 원리**:
  1. 복잡한 섹터 정렬 대신, 목표 완료 지연시간(`target_read_latency_us`, 기본 $2,000\,\mu\text{s}$)을 설정합니다.
  2. 롤링 윈도우(약 8ms 주기)로 실제 읽기 요청의 p99 지연시간을 실시간 모니터링합니다.
  3. 백그라운드 쓰기 폭풍으로 인해 읽기 지연시간이 목표치에 근접하면, 비동기 쓰기 도메인의 **디스패치 큐 깊이(Queue Depth)를 $128 \rightarrow 1$로 즉각 축소(Throttle)**합니다.
  4. 읽기 요청에 하드웨어 큐 점유 우선권을 부여하여 읽기 지연시간을 $500\,\mu\text{s}$ 이하로 즉시 안정화시킵니다.
- **장점**: $2 \sim 3\%$ 수준의 극히 낮은 CPU 오버헤드만으로 대화형 쿼리의 꼬리 지연시간을 완벽히 방어합니다.
- **적용 대상**: 대규모 온라인 트랜잭션 처리(OLTP), 대화형 서비스와 백그라운드 배치가 혼재된 엔터프라이즈 환경.

---

### 2.3 `mq-deadline` (Multi-Queue Deadline)
- **개념**: 레거시 Deadline 스케줄러를 멀티큐 아키텍처로 포팅한 방식입니다.
- **동작 원리**:
  - 요청을 읽기 FIFO와 쓰기 FIFO로 분리 관리합니다.
  - 마감시간(`read_expire` 500ms, `write_expire` 5000ms)이 임박한 요청을 우선 디스패치하여 기아 상태를 방지합니다.
- **NVMe 한계**:
  - 디스패치 단계에서 공유 락을 사용하므로, 32~64개 CPU 코어가 동시에 500,000 IOPS 이상을 밀어넣을 때 락 경합(`cpu_spinlock_wait` 약 20~25%)이 발생하여 최대 처리량이 약 280,000 IOPS 수준에서 병목에 걸립니다.
- **적용 대상**: SATA SSD, 단일 큐 스토리지, 쓰기 기아가 치명적인 하이브리드 스토리지.

---

### 2.4 `bfq` (Budget Fair Queueing)
- **개념**: $WF^2Q+$ (Worst-case Fair Weighted Fair Queueing) 알고리즘을 기반으로 프로세스 및 cgroup별 전송 섹터 버짓(Budget)을 공평하게 분배하는 고복잡도 스케줄러.
- **NVMe 참사의 메커니즘**:
  - BFQ는 I/O 1건을 처리할 때마다 가상 시간 계산, 버짓 트래킹, 디스크 아이들링 추론 등 수천 라인의 복잡한 커널 연산과 **전역 스핀락(Global Spinlock)**을 수행합니다.
  - 디바이스의 I/O 처리 시간($50\,\mu\text{s}$)보다 커널 스케줄러 락 획득 대기 시간($80 \sim 150\,\mu\text{s}$)이 더 길어지는 **역전 현상**이 발생합니다.
  - CPU 코어 64개가 커널 스핀락에 갇혀 CPU %sys가 $80\%$까지 치솟으며, 800,000 IOPS 장치가 **95,000 IOPS로 88% 폭락**하고 지연시간이 **$200\,\text{ms}$ 이상으로 폭발**합니다.
- **적용 대상**: 데스크톱 GUI 환경, HDD 환경. **(초고속 NVMe 서버에서는 절대 금기!)**

---

## 3. 프로덕션 NVMe 튜닝 및 운영 실무

### 3.1 스케줄러 확인 및 변경 명령어
```bash
# 1. 현재 NVMe 드라이브의 스케줄러 확인
cat /sys/block/nvme0n1/queue/scheduler
# 출력 예시: [none] mq-deadline kyber bfq

# 2. 실시간 none 스케줄러 적용 (최대 처리량)
echo none > /sys/block/nvme0n1/queue/scheduler

# 3. 실시간 kyber 스케줄러 적용 (대화형 쿼리 보호)
echo kyber > /sys/block/nvme0n1/queue/scheduler
echo 2000 > /sys/block/nvme0n1/queue/kyber_lat_usecs/read
```

### 3.2 영구 적용을 위한 udev 규칙 (`/etc/udev/rules.d/60-nvme-scheduler.rules`)
```udev
# 회전식 디스크(HDD)는 mq-deadline 또는 bfq
ACTION=="add|change", KERNEL=="sd[a-z]*", ATTR{queue/rotational}=="1", ATTR{queue/scheduler}="mq-deadline"

# 고속 NVMe 드라이브는 none 또는 kyber 강제
ACTION=="add|change", KERNEL=="nvme[0-9]*n[0-9]*", ATTR{queue/rotational}=="0", ATTR{queue/scheduler}="none"
```
