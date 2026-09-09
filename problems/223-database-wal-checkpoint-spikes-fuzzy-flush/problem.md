# 문제 223: 데이터베이스 스토리지 엔진: WAL 체크포인트 스파이크(Checkpoint Spikes), 날카로운(Sharp) 체크포인트 vs 분산 플러시(Fuzzy Checkpoint) & 백엔드 동기 쓰기(Backend Writes) 쓰레싱

## 1. 개요 (Incident Scenario)

대규모 엔터프라이즈 결제 및 OLTP 주문 처리를 담당하는 핵심 관계형 데이터베이스(PostgreSQL / MySQL InnoDB 계열) 클러스터를 운영하는 DBA 및 데이터베이스 플랫폼 엔지니어링 팀은 정기적으로 주기적인 API 응답 지연이 5초 이상 치솟는 **체크포인트 스파이크(Checkpoint Spikes)** 장애에 직면했습니다.

관계형 데이터베이스는 성능을 위해 트랜잭션 변경 사항을 메모리 버퍼 풀(`shared_buffers`)에 더티 페이지(Dirty Page)로 유지하고 순차 로그(WAL / Redo Log)에 먼저 기록(Write-Ahead Logging)합니다.
정전이나 크래시 발생 시 복구 시간(RTO)을 단축하고 WAL 디스크 공간을 재사용하기 위해 백그라운드 프로세스인 **체크포인터(Checkpointer)**가 주기적으로 메모리의 더티 페이지를 디스크 스토리지로 동기화(Flush & Fsync)합니다.

그러나 운영 환경에서 파라미터가 잘못 구성되었을 때 다음과 같은 세 가지 치명적인 스토리지 엔진 I/O 병목이 발생했습니다:

1. **날카로운 체크포인트(Sharp Checkpoint)로 인한 디스크 I/O 포화 및 쿼리 프리징**:
   체크포인터가 더티 페이지를 시간 여유 없이 가능한 한 최대 속도로 디스크에 한꺼번에 쏟아붓는 방식(`checkpoint_completion_target = 0.05` 또는 고전적 Sharp Checkpoint)으로 동작할 때, 디스크 I/O 사용률이 수십 초간 100%로 치솟았습니다.
   이로 인해 신규 트랜잭션의 클린 페이지 읽기와 WAL 쓰기 I/O 큐가 디스크 대기열에 갇혀 쿼리 P99 지연시간이 평소 4ms에서 4,500ms 이상으로 폭등하는 톱니파(Sawtooth) 형태의 심각한 지연 스파이크(`SHARP_CHECKPOINT_IO_SPIKE_STALL`)가 발생했습니다.

2. **버퍼 풀 고갈로 인한 백엔드 프로세스 동기 플러시(Backend Writes Thrashing)**:
   대량의 쓰기 트래픽이 유입되는데 백그라운드 라이터(`bgwriter`)가 비활성화되어 있거나 체크포인터의 쓰기 대역폭이 유입 속도를 따라가지 못하면, 공유 버퍼 풀(`shared_buffers`)이 100% 더티 페이지로 가득 차게 됩니다.
   신규 쿼리를 처리해야 하는 유저 백엔드 워커 프로세스(Backend Process)는 자신이 읽어야 할 공간을 마련하기 위해 **다른 트랜잭션의 더티 페이지를 스스로 디스크에 동기적으로 플러시(Backend Writes)**해야만 합니다. 이로 인해 수천 개의 백엔드 프로세스가 디스크 I/O와 버퍼 락 경합에 휘말려 데이터베이스 전체가 쓰레싱 상태에 빠졌습니다(`BACKEND_SYNC_FLUSH_THRASHING`).

3. **작은 WAL 용량 한도로 인한 예정에 없던 빈번한 체크포인트 폭풍**:
   `max_wal_size`가 너무 작게(예: 512MB) 설정되어 있으면, 시간 주기(`checkpoint_timeout = 5분`)가 도달하기도 전에 WAL 파일이 가득 차 25초~32초마다 강제 체크포인트가 격발됩니다. 분산 플러시(Spread)가 무력화되어 디스크 I/O가 쉴 새 없이 요동치는 장애(`WAL_DRIVEN_UNSCHEDULED_CHECKPOINT_BURST`)가 발생했습니다.

4. **퍼지 체크포인트(Fuzzy Spread Checkpoint) 튜닝을 통한 구원**:
   체크포인트 완료 목표 비율을 `checkpoint_completion_target = 0.9`로 설정하고, `max_wal_size`를 16GB 이상으로 넉넉히 확보하며, `bgwriter`를 활성화하여 백엔드용 여유 클린 버퍼를 선제 확보함으로써 디스크 I/O 점유율을 25~35%로 평탄화하고 백엔드 동기 쓰기 0건, P99 지연 5ms 이하의 완벽한 안정성을 달성해야 합니다(`OPTIMAL_FUZZY_SPREAD_CHECKPOINT`).

당신은 데이터베이스 커널 및 스토리지 엔진 전문가로서, 버퍼 풀 더티 페이지 회계, 체크포인터 분산 플러시 속도 계산, 백엔드 직접 쓰기 발생 여부 및 쿼리 지연시간을 정밀하게 모의하고 클러스터의 상태를 진단하는 시뮬레이터를 작성해야 합니다.

---

## 2. 아키텍처 및 상태 모델

```
 [PostgreSQL / InnoDB Buffer Pool & Checkpoint Architecture]

   [Client Queries] ──► Write Transactions (30 MB/s Dirty Pages)
                               │
                               ▼
               ┌───────────────────────────────┐
               │  Shared Buffers Pool (4 GB)   │
               │  [Clean Pages] [Dirty Pages]  │
               └───────────────┬───────────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        ▼                      ▼                      ▼
  [Checkpointer]          [Bgwriter]          [Backend Processes]
  Spread over 90%        Cleans Ahead         FORCED Sync Writes!
  (Fuzzy Target=0.9)     for Free Buffers     (If Clean Pool Empty!)
        │                      │                      │
        └──────────────────────┼──────────────────────┘
                               ▼
                 [Disk Storage (250 MB/s Bandwidth)]
                 - Sharp Flush:  100% Saturation (4.5s Freeze!)
                 - Fuzzy Spread: 25% Smooth Rate (5ms Stable!)
```

### 시뮬레이션 동작 규격

1. **스토리지 엔진 파라미터 설정**:
   - `checkpoint_type`: `"SHARP"` 또는 `"FUZZY"`
   - `checkpoint_timeout_sec`: 체크포인트 시간 주기 (기본 300초)
   - `checkpoint_completion_target`: 체크포인트 플러시 분산 목표 비율 (0.05 ~ 0.9)
   - `max_wal_size_mb`: 체크포인트를 유발하는 최대 WAL 용량 한도 (MB)
   - `shared_buffers_mb`: 데이터베이스 공유 메모리 버퍼 풀 크기 (MB)
   - `disk_max_write_bandwidth_mbps`: 디스크 최대 지속 쓰기 대역폭 (MB/s)
   - `bgwriter_enabled`: 백그라운드 라이터 활성화 여부 (bool)
   - `bgwriter_lru_rate_mbps`: 백그라운드 라이터가 비동기로 청소하는 속도 (MB/s)

2. **체크포인트 트리거 및 주기 계산**:
   - WAL 발생 속도(`wal_generation_rate_mbps`)에 의해 `max_wal_size_mb`에 도달하는 시간: $t_{\text{wal}} = \text{max\_wal\_size\_mb} / \text{wal\_rate}$
   - 실제 체크포인트 간격: $T_{\text{interval}} = \min(\text{checkpoint\_timeout\_sec}, t_{\text{wal}})$
   - $t_{\text{wal}} < \text{checkpoint\_timeout\_sec}$ 이면 WAL 초과에 의해 조기 격발된 체크포인트(`is_wal_driven = true`)입니다.

3. **체크포인트 플러시 및 디스크 점유율 계산**:
   - **`SHARP` 모드 (또는 `checkpoint_completion_target <= 0.2`)**:
     - 디스크 한계 속도로 일시에 덤프하므로 피크 디스크 사용률: $\text{peak\_disk\_utilization} = 1.0$ (100%).
     - 쿼리 P99 지연시간은 극심한 I/O 경합으로 4500.0ms로 폭증합니다.
     - 백엔드 동기 쓰기는 발생하기 전에 체크포인트가 조기 종료되므로 0.0MB입니다.
   - **`FUZZY` 모드 (`checkpoint_completion_target > 0.2`)**:
     - 분산 목표 시간: $T_{\text{target}} = \max(1.0, T_{\text{interval}} \times \text{checkpoint\_completion\_target})$
     - 주기 동안 누적된 더티 페이지: $\text{dirty\_accumulated} = \text{dirty\_rate} \times T_{\text{interval}}$
     - 목표 체크포인트 플러시 속도: $\text{chkp\_rate} = \min(\text{disk\_max\_bw}, \text{dirty\_accumulated} / T_{\text{target}})$
     - 총 백그라운드 정리 속도: $\text{total\_clean\_rate} = \min(\text{disk\_max\_bw}, \text{chkp\_rate} + \text{bgwriter\_rate})$
     - 피크 디스크 사용률: $\text{peak\_disk\_utilization} = \min(1.0, \text{total\_clean\_rate} / \text{disk\_max\_bw})$
     - **버퍼 풀 고갈 및 백엔드 동기 쓰기(Backend Writes)**:
       - 가용 클린 버퍼 마진: $\text{clean\_margin} = \text{shared\_buffers\_mb} \times 0.35$
       - 만약 $\text{dirty\_rate} > \text{total\_clean\_rate}$ 라면 더티 페이지가 순증합니다:
         - 고갈 도달 시간: $t_{\text{exhaust}} = \text{clean\_margin} / (\text{dirty\_rate} - \text{total\_clean\_rate})$
         - $t_{\text{exhaust}} < T_{\text{interval}}$ 이면 잔여 시간 동안 유입되는 초과 더티 페이지는 유저 백엔드 프로세스가 직접 동기 쓰기합니다:
           $$\text{backend\_writes\_mb} = (\text{dirty\_rate} - \text{total\_clean\_rate}) \times (T_{\text{interval}} - t_{\text{exhaust}})$$
           $$\text{p99\_query\_latency\_ms} = 1850.0\text{ms}$$
       - 고갈되지 않는 정상 환경:
         $$\text{backend\_writes\_mb} = 0.0, \quad \text{p99\_query\_latency\_ms} = 3.5 + (\text{peak\_disk\_utilization} \times 6.0)$$

4. **장애 판정 및 최종 Verdict 규칙**:
   - `peak_disk_utilization >= 0.98` 및 (`checkpoint_type == "SHARP"` 또는 `completion_target <= 0.2`):
     - `status = "FAILED"`, `verdict = "SHARP_CHECKPOINT_IO_SPIKE_STALL"`
   - `backend_writes_mb > 0.0`:
     - `status = "FAILED"`, `verdict = "BACKEND_SYNC_FLUSH_THRASHING"`
   - `is_wal_driven == true` 이고 $T_{\text{interval}} < 45.0\text{초}$:
     - `status = "FAILED"`, `verdict = "WAL_DRIVEN_UNSCHEDULED_CHECKPOINT_BURST"`
   - `checkpoint_type == "FUZZY"`, `completion_target >= 0.8`, `backend_writes_mb == 0.0`, `peak_disk_utilization <= 0.65`:
     - `status = "SUCCESS"`, `verdict = "OPTIMAL_FUZZY_SPREAD_CHECKPOINT"`
   - 그 외 안정적 상태:
     - `status = "SUCCESS"`, `verdict = "NORMAL_DATABASE_STEADY_STATE"`

---

## 3. 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다.

```json
{
  "config": {
    "checkpoint_type": "FUZZY",
    "checkpoint_timeout_sec": 300.0,
    "checkpoint_completion_target": 0.9,
    "max_wal_size_mb": 16384.0,
    "shared_buffers_mb": 4096.0,
    "disk_max_write_bandwidth_mbps": 250.0,
    "bgwriter_enabled": true,
    "bgwriter_lru_rate_mbps": 20.0
  },
  "workload": {
    "duration_sec": 300.0,
    "dirty_page_generation_rate_mbps": 40.0,
    "wal_generation_rate_mbps": 20.0,
    "incoming_query_rate_qps": 2500.0
  }
}
```

---

## 4. 출력 형식

표준 출력(stdout)으로 JSON 객체를 출력합니다. 실수형 수치는 소수점 둘째 자리(비율은 넷째 자리)까지 반올림합니다.

```json
{
  "status": "SUCCESS",
  "verdict": "OPTIMAL_FUZZY_SPREAD_CHECKPOINT",
  "metrics": {
    "checkpoint_type": "FUZZY",
    "actual_checkpoint_interval_sec": 300.0,
    "is_wal_driven": false,
    "peak_disk_utilization_ratio": 0.2578,
    "backend_writes_mb": 0.0,
    "p99_query_latency_ms": 5.05
  }
}
```
