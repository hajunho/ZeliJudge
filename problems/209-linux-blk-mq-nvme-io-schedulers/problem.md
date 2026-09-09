# Problem 209: 초당 100만 IOPS 나오는 NVMe SSD인데 왜 DB 쿼리 응답이 100ms나 걸려요?!: 리눅스 커널 blk-mq 블록 레이어 I/O 스케줄러: none vs mq-deadline vs kyber vs bfq & NVMe 멀티큐 스케줄링 경합 (Linux Block Layer & NVMe I/O Schedulers: none vs mq-deadline vs Kyber vs BFQ under Multi-Queue SSD)

## 문제 배경 및 개요

대규모 클라우드 및 온프레미스 고성능 데이터베이스(RocksDB, PostgreSQL, MySQL InnoDB, ScyllaDB)를 운영하는 인프라 SRE 팀은 PCIe Gen4 엔터프라이즈 NVMe SSD(하드웨어 스펙상 800,000 ~ 1,000,000 IOPS, $50\,\mu\text{s}$ 미만 초저지연)를 도입한 신규 베어메탈 서버 클러스터를 구축했습니다.

그러나 벤치마크 및 프로덕션 부하 테스트를 수행하자마자, 모니터링 대시보드에는 도저히 믿을 수 없는 **"하드웨어 낭비 및 지연시간 폭발 참사"**가 발생했습니다:
1. 초당 500,000건의 I/O(100,000 읽기 + 400,000 쓰기)가 유입되자, 스토리지 처리량이 **95,000 IOPS로 80% 이상 폭락**했습니다.
2. 하드웨어 스펙상 $50\,\mu\text{s}$에 끝나야 할 4KB 랜덤 읽기 p99 응답시간이 무려 **210,000 $\mu\text{s}$ ($210\,\text{ms}$)**까지 치솟았습니다.
3. `top` 및 `perf top` 프로파일링 결과, CPU 사용률의 **78% 이상이 커널 내부 스핀락 경합(`kernel_spinlock_wait`)**에 갇혀 있었습니다.

```
[애플리케이션 스레드 (64 Cores, 500,000 IOPS 요청)]
                    │
                    ▼
       ┌─────────────────────────┐
       │   blk-mq Software Queue │ (CPU별 Lockless Staging)
       └────────────┬────────────┘
                    │
        [I/O 스케줄러 선택의 갈림길]
                    │
   ├── [bfq (Budget Fair Queueing)] ──> [재앙!]
   │   섹터 버짓 계산, 전역 스핀락 락킹!
   │   ==> 78.5% CPU 스핀락 대기, 처리량 95,000 IOPS 폭락, 지연시간 210ms 폭증!
   │
   ├── [mq-deadline] ───────────────> [경합!]
   │   읽기 마감시간(500ms) 보장하나 단일 디스패치 큐 락 경합으로 280,000 IOPS 상한.
   │
   ├── [none (No-op blk-mq)] ────────> [최대 처리량!]
   │   소프트웨어 스케줄러 레이어 완전 바이패스!
   │   ==> 0.2% CPU 오버헤드, 500,000 IOPS 유선 속도 달성, 77us 초저지연.
   │   ==> 단, 대규모 쓰기 폭풍(750k IOPS) 발생 시 읽기가 뒤로 밀리는 꼬리 지연(15.9ms).
   │
   └── [kyber (Meta/Facebook 저지연 스케줄러)] ──> [지연시간 수호신!]
       목표 읽기 지연(2000us) 초과 감지 시, 비동기 쓰기 디스패치 큐 깊이를 1로 자동 스로틀링!
       ==> 쓰기 폭풍 중에도 대화형 쿼리 p99 지연시간을 486us로 완벽 방어!
```

이 참사의 원인은 리눅스 배포판 기본 설정으로 활성화된 **`bfq` (Budget Fair Queueing)** I/O 스케줄러에 있었습니다:
- 구형 회전식 하드디스크(HDD)나 단일 큐 SATA SSD 시절에는 느린 디스크 헤드 이동을 줄이고 프로세스 간 공평성을 부여하기 위해 복잡한 엘리베이터 정렬과 버짓 큐잉이 유효했습니다.
- 그러나 초당 100만 IOPS를 처리하는 현대 멀티큐 NVMe SSD에서는 **스케줄러가 스핀락을 획득하고 복잡한 수학적 버짓을 계산하는 데 드는 CPU 사이클이, SSD 하드웨어가 플래시 메모리에서 데이터를 읽어오는 시간보다 훨씬 더 오래 걸립니다!**
- 따라서 최신 리눅스 커널에서는 소프트웨어 스케줄러를 완전히 바이패스하여 하드웨어 큐로 직결하는 **`none`** 스케줄러, 또는 p99 지연시간을 실시간 측정하여 쓰기 큐 깊이를 적응형으로 제어하는 **`kyber`** 스케줄러를 사용하는 것이 정석입니다.

당신은 리눅스 커널 스토리지 및 데이터베이스 인프라 엔지니어로서, 4대 blk-mq I/O 스케줄러(`none`, `mq-deadline`, `kyber`, `bfq`)의 대역폭, 스핀락 경합 오버헤드, 그리고 쓰기 폭풍 하에서의 읽기 꼬리 지연시간(Tail Latency) 특성을 정밀 진단하는 시뮬레이터를 완성해야 합니다.

---

## 4대 blk-mq I/O 스케줄러 특성 명세

### 1. `bfq` (Budget Fair Queueing)
- 프로세스별, cgroup별 전송 섹터 버짓(Budget)을 추적하고 가중치 기반 공평성을 보장하는 고복잡도 스케줄러.
- 엔터프라이즈 멀티큐 NVMe 환경에서는 전역 스핀락 경합(`cpu_spinlock_wait_pct >= 60.0`)으로 인해 유효 IOPS가 100,000 수준으로 급락하며, 평균 및 p99 읽기 지연시간이 200ms 이상으로 폭발합니다.
- 평가 판정(Verdict): `BFQ_NVME_SPINLOCK_COLLAPSE` (`status: FAILED`).

### 2. `mq-deadline` (Multi-Queue Deadline)
- 읽기 요청(기본 만료 500ms)과 쓰기 요청(기본 만료 5000ms)을 분리된 FIFO로 관리하여 읽기 기아(Starvation)를 방지.
- 멀티스레드 동시 요청이 많을 때 디스패치 락 경합(`cpu_spinlock_wait_pct` 약 20~25%)으로 인해 최대 IOPS가 약 280,000 수준으로 제한됩니다.
- 평가 판정(Verdict): `MQ_DEADLINE_LOCK_CONTENTION_THROTTLED`.

### 3. `none` (No-op blk-mq 바이패스)
- 소프트웨어 스케줄러 레이어를 완전히 건너뛰고, CPU 코어별 소프트웨어 큐에서 NVMe 컨트롤러의 하드웨어 제출 큐(Submission Queue)로 직접 락리스(Lockless) 전달.
- CPU 스핀락 오버헤드가 $0.2\%$ 미만이며, 하드웨어 최대 대역폭(800,000+ IOPS)과 마이크로초급 초저지연($< 80\,\mu\text{s}$)을 달성합니다.
- 단, 스케줄러가 개입하지 않으므로 백그라운드 쓰기 요청이 하드웨어 한계치에 근접하는 극단적 폭풍(Burst) 상황에서는 하드웨어 큐 적체로 인해 읽기 꼬리 지연시간이 상승할 수 있습니다 (`NONE_WRITE_BURST_TAIL_SPIKE`).
- 정상 부하에서는 `OPTIMAL_NONE_RAW_NVME_THROUGHPUT`.

### 4. `kyber` (Meta 저지연 적응형 스케줄러)
- 대화형(Interactive) 읽기 지연시간 보호를 위해 설계된 최신 멀티큐 스케줄러.
- 목표 읽기 지연(`target_read_latency_us`, 기본 2000 $\mu$s)을 설정하고 롤링 주기로 완료 지연을 모니터링합니다.
- 쓰기 부하가 급증하여 읽기 p99 지연시간이 상승 조짐을 보이면, 백그라운드 쓰기의 디스패치 큐 깊이(Queue Depth)를 동적으로 스로틀링(`write_throttled = True`)하여 대화형 읽기 요청이 지연 없이 즉시 처리되도록 보장합니다.
- 평가 판정(Verdict): `OPTIMAL_KYBER_LATENCY_THROTTLED`.

---

## 입력 형식

표준 입력(Standard Input)으로 단일 JSON 객체가 주어집니다:

```json
{
  "device_config": {
    "device_type": "NVME_ENTERPRISE_GEN4",
    "max_device_iops": 800000,
    "device_base_latency_us": {
      "read_us": 50.0,
      "write_us": 30.0
    }
  },
  "scheduler_config": {
    "scheduler": "kyber",
    "kyber": {
      "target_read_latency_us": 2000.0,
      "target_write_latency_us": 10000.0
    }
  },
  "workload": {
    "interactive_reads": {
      "iops": 100000,
      "duration_s": 1.0
    },
    "background_writes": {
      "iops": 650000,
      "duration_s": 1.0
    }
  }
}
```

---

## 출력 형식

표준 출력(Standard Output)으로 진단 시뮬레이션 결과 JSON을 들여쓰기 2칸(`indent=2`)으로 출력합니다:

```json
{
  "status": "SUCCESS",
  "verdict": "OPTIMAL_KYBER_LATENCY_THROTTLED",
  "scheduler": "kyber",
  "metrics": {
    "requested_iops": 750000,
    "achieved_iops": 750000,
    "achieved_read_iops": 100000,
    "achieved_write_iops": 650000,
    "throughput_efficiency_pct": 100.0,
    "cpu_spinlock_wait_pct": 2.5,
    "average_read_latency_us": 270.0,
    "p99_read_latency_us": 486.0,
    "write_throttled": true
  }
}
```

---

## 판정 기준 (Verdict Rules)

1. **`BFQ_NVME_SPINLOCK_COLLAPSE`**: `scheduler == "bfq"` 상태에서 스핀락 경합(`cpu_spinlock_wait_pct >= 60.0`) 및 지연시간 폭발이 발생한 경우 (`status: FAILED`).
2. **`MQ_DEADLINE_LOCK_CONTENTION_THROTTLED`**: `scheduler == "mq-deadline"` 상태에서 디스패치 락 경합으로 인해 최대 처리량이 제한된 경우.
3. **`NONE_WRITE_BURST_TAIL_SPIKE`**: `scheduler == "none"` 상태에서 초대형 쓰기 버스트로 인해 하드웨어 큐 큐잉 지연 및 읽기 p99 꼬리 지연 스파이크가 발생한 경우.
4. **`OPTIMAL_NONE_RAW_NVME_THROUGHPUT`**: `scheduler == "none"` 상태에서 0% 대의 스핀락 오버헤드로 하드웨어 라인레이트 초저지연 성능을 완벽히 달성한 경우.
5. **`OPTIMAL_KYBER_LATENCY_THROTTLED`**: `scheduler == "kyber"` 상태에서 쓰기 큐 깊이를 동적으로 조절하여 읽기 p99 지연시간을 목표치 이내로 성공적으로 방어한 경우.
