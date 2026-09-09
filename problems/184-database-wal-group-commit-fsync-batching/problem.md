# Problem 184: 데이터베이스 WAL(Write-Ahead Log) Group Commit, fsync() 디스크 플러시 병목과 리더-팔로워 동시성 배칭

## 문제 설명

글로벌 코어 뱅킹 및 전자 결제 정산 플랫폼을 운영하는 데이터 인프라 엔지니어링 팀은 금융 규제 준수를 위해 데이터베이스 트랜잭션의 엄격한 지속성(ACID Durability, `fsync on commit`)을 활성화했습니다.

그러나 초당 수만 건의 결제 요청이 몰리는 피크 타임에 다음과 같은 치명적인 성능 절벽에 직면했습니다:
1. **fsync() 직렬화 락 콘보이(Lock Convoy)와 스레드 풀 고갈**: 각 트랜잭션 커밋마다 개별적으로 `fsync()` 시스템 콜을 호출하자, 최신 NVMe SSD의 하드웨어 플러시 배리어(Flush Barrier) 지연($100\sim500\,\mu\text{s}$)으로 인해 물리적 디스크 동기화 한계($2,000\sim5,000\,\text{IOPS}$)에 도달했습니다. 커밋 대기 큐에 수천 개의 DB 커넥션 스레드가 D-상태(`TASK_UNINTERRUPTIBLE`)로 잠들며 평균 커밋 지연시간이 수십 배 폭증했습니다.
2. **정적 딜레이(Static Delay) 그룹 커밋의 인위적 지연(Latency Penalty)**: 더 많은 트랜잭션을 묶기 위해 강제 수면 지연(`commit_delay`)을 도입했으나, 트래픽 유입이 불규칙하거나 기준 형제 수(`commit_siblings`)를 충족할 때마다 무조건 불필요한 대기 시간이 추가되어 p99 지연시간이 악화되었습니다.
3. **리더-팔로워 파이프라인 그룹 커밋(Pipelined Group Commit)의 구원**: 선행 트랜잭션이 **그룹 리더(Leader)**가 되어 대기 중인 후행 트랜잭션(**Followers**)들의 WAL 레코드를 단 1회의 순차 쓰기와 단 1회의 `fsync()`로 일괄 동기화하는 락-프리 파이프라인 엔진이 필요해졌습니다.

당신은 개별 동기화 모드, 정적 딜레이 그룹 커밋 모드, 그리고 리더-팔로워 파이프라인 그룹 커밋 모드를 정밀하게 시뮬레이션하고, fsync 절감율과 커밋 지연시간을 평가하는 고성능 DB 스토리지 시뮬레이터를 구현해야 합니다.

---

## 핵심 커밋 모드 (Commit Modes)

### 1. `NAIVE_INDIVIDUAL_FSYNC` (개별 fsync 직렬화 모드)
- 각 트랜잭션이 개별적으로 WAL 락을 획득하고, 메모리 버퍼 쓰기 후 개별 `fsync()`를 동기 실행합니다.
- 동일 배치에 동시에 도착한 $N$개의 트랜잭션은 순차적으로 대기열을 통과하므로, 후행 트랜잭션들은 선행 트랜잭션들의 fsync 시간만큼 대기 지연(Queuing Delay)이 누적됩니다.
- fsync 호출 횟수는 트랜잭션 수와 동일합니다 ($\text{fsync\_calls} = N$).
- 평가 판정(Verdict): `FSYNC_IO_CONVOY_BOTTLENECK` (트랜잭션 3건 이상 시 `status: FAILED`)

### 2. `STATIC_DELAY_GROUP_COMMIT` (정적 딜레이 그룹 커밋)
- 고전 PostgreSQL의 `commit_delay` / `commit_siblings` 메커니즘을 모방합니다.
- 큐에 대기 중인 트랜잭션 수(형제 수)가 최소 기준(`commit_siblings_min`) 이상이면, 리더가 추가 배칭을 위해 인위적으로 `commit_delay_us`만큼 대기합니다.
- 기준 미달 시에는 대기 없이 즉시 플러시합니다.
- 최대 배치 크기(`max_batch_size`) 단위로 트랜잭션들을 묶어 단 1회의 `fsync()`로 커밋합니다.
- 평가 판정(Verdict): `STATIC_DELAY_LATENCY_INFLATION`

### 3. `PIPELINED_GROUP_COMMIT` (리더-팔로워 파이프라인 그룹 커밋)
- 최신 MySQL 5.6+ Binary Log Group Commit 및 PostgreSQL 9.3+의 락-프리 그룹 커밋 아키텍처입니다.
- 인위적인 슬립 딜레이가 전혀 없습니다 ($\text{delay} = 0.0\,\mu\text{s}$).
- 리더 트랜잭션이 현재 큐에 누적된 대기 트랜잭션들을 최대 `max_batch_size`까지 즉시 수확(Harvest)하여 일괄 순차 메모리 쓰기 후 단 1회의 `fsync()`를 실행합니다.
- 동일 그룹 내의 모든 팔로워 트랜잭션은 단 1회의 디스크 I/O 없이 리더의 fsync 완료 즉시 동시 커밋 처리됩니다.
- 평가 판정(Verdict): `OPTIMAL_PIPELINED_GROUP_COMMIT`

---

## 하드웨어 I/O 및 성능 수식

### 1. 로그 메모리 버퍼 쓰기 시간
$$\text{write\_time\_us} = \left(\frac{\sum \text{log\_bytes}}{1024.0}\right) \times \text{log\_write\_per\_kb\_us}$$

### 2. 그룹 I/O 소요 시간 (Duration)
$$\text{duration\_us} = \text{delay\_us} + \text{write\_time\_us} + \text{fsync\_latency\_us}$$

### 3. 트랜잭션 지연시간 (Commit Latency)
- 배치 도착 시점(`batch_start_time`)부터 해당 트랜잭션이 속한 그룹의 fsync 완료 시점(`current_time_us`)까지의 경과 시간:
$$\text{latency\_us} = \text{current\_time\_us} - \text{batch\_start\_time}$$

### 4. fsync 절감율 (Fsync Reduction Rate)
$$\text{fsync\_reduction\_rate} = 1.0 - \left(\frac{\text{total\_fsync\_calls}}{\text{total\_transactions}}\right)$$

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "system": {
    "commit_mode": "PIPELINED_GROUP_COMMIT",
    "fsync_latency_us": 200.0,
    "log_write_per_kb_us": 1.0,
    "commit_delay_us": 100.0,
    "commit_siblings_min": 3,
    "max_batch_size": 64
  },
  "workload": [
    {
      "batch_id": 1,
      "transactions": [
        {"tx_id": "tx_001", "log_bytes": 1024},
        {"tx_id": "tx_002", "log_bytes": 2048}
      ]
    }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 다음 형식의 JSON 객체를 들여쓰기 2칸(`indent=2`)으로 출력합니다:

```json
{
  "status": "SUCCESS",
  "summary": {
    "commit_mode": "PIPELINED_GROUP_COMMIT",
    "total_transactions": 2,
    "total_fsync_calls": 1,
    "fsync_reduction_rate": 0.5,
    "average_group_size": 2.0,
    "peak_group_size": 2
  },
  "metrics": {
    "total_transactions": 2,
    "total_fsync_calls": 1,
    "total_log_bytes": 3072,
    "total_io_time_us": 203.0,
    "average_commit_latency_us": 203.0,
    "average_group_size": 2.0,
    "peak_group_size": 2,
    "fsync_reduction_rate": 0.5,
    "verdict": "OPTIMAL_PIPELINED_GROUP_COMMIT"
  },
  "sample_groups": [
    {
      "batch_id": 1,
      "leader_tx": "tx_001",
      "group_size": 2,
      "log_bytes": 3072,
      "fsync_count": 1,
      "duration_us": 203.0,
      "transactions": ["tx_001", "tx_002"]
    }
  ]
}
```

> **성공 기준**: `commit_mode`가 `NAIVE_INDIVIDUAL_FSYNC`이고 `total_transactions > 2`인 경우 병목으로 인해 `status: "FAILED"`, 그 외 최적화 모드는 `status: "SUCCESS"`.
