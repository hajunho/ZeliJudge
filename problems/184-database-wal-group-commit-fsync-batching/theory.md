# 데이터베이스 WAL Group Commit과 fsync() 디스크 플러시 병목 아키텍처

## 1. 개요: ACID 지속성(Durability)과 물리적 디스크의 한계

관계형 데이터베이스(RDBMS)의 핵심 가치는 ACID 속성을 보장하는 것입니다. 그중 **D (Durability, 지속성)**는 트랜잭션이 성공적으로 커밋(Commit)되었다면, 그 직후 전원 차단이나 운영체제 크래시가 발생하더라도 기록된 데이터가 절대로 유실되지 않음을 보장해야 합니다.

현대 DBMS는 이를 위해 **Write-Ahead Logging (WAL, 또는 InnoDB의 Redo Log)** 기법을 사용합니다:
- 데이터 파일(Table Data Pages, 8KB/16KB)을 매 트랜잭션마다 디스크의 무작위 위치에 직접 쓰는 것은 엄청난 랜덤 I/O 비용을 유발합니다.
- 대신 모든 변경 내역을 순차적인 추가 전용(Append-Only) 로그 파일인 WAL에 먼저 기록하고, 나중에 체크포인트(Checkpoint)를 통해 데이터 파일에 일괄 반영합니다.

문제는 **트랜잭션 커밋 완료 응답을 클라이언트에게 반환하기 전에, WAL 레코드가 물리적 비휘발성 저장 장치(SSD/HDD)에 완전히 안착했는가**입니다.

---

## 2. `fsync()` 시스템 콜과 하드웨어 플러시 배리어(Flush Barrier)

운영체제에서 `write()` 시스템 콜을 호출하면 데이터는 즉시 물리 디스크에 기록되는 것이 아니라, OS의 **페이지 캐시(Page Cache)**에 더티 페이지로 임시 적재됩니다.
전원 차단 시 데이터 유실을 방지하려면 커널과 스토리지 컨트롤러에게 캐시를 즉시 비우도록 명령하는 **`fsync()` 또는 `fdatasync()`** 시스템 콜을 실행해야 합니다.

```
[User App: DB Process]
       |  write(wal_fd, buf, len)
       v
[OS Kernel Page Cache] (RAM - 비휘발성 보장 안 됨)
       |  fsync(wal_fd)
       v
[Storage Controller Write Cache] (NVMe/SATA 컨트롤러 내부 RAM)
       |  하드웨어 플러시 배리어 명령 (NVMe Flush / ATA FLUSH CACHE)
       v
[NAND Flash Memory / Magnetic Disk] (영구 보존 비휘발성 매체)
```

### 물리적 속도의 절대적 한계
- 아무리 빠른 최신 엔터프라이즈 NVMe SSD라 할지라도, 컨트롤러 캐시의 데이터를 낸드 플래시 블록에 플러시하고 완료 신호(Completion Queue Interrupt)를 호스트 CPU로 반환하는 데는 **최소 $100\,\mu\text{s} \sim 300\,\mu\text{s}$의 물리적 시간**이 소요됩니다.
- 만약 1회의 `fsync()` 처리에 $200\,\mu\text{s}$가 걸린다면:
  $$\text{최대 물리적 fsync 횟수} = \frac{1\,\text{초}}{200\,\mu\text{s}} = 5,000\,\text{fsyncs/sec}$$
- 즉, **단일 스토리지 장치에서 트랜잭션마다 독립적으로 `fsync()`를 호출하면 초당 처리량(TPS)은 5,000건을 절대로 넘을 수 없습니다.**

---

## 3. 개별 동기화의 비극: 락 콘보이(Lock Convoy)와 스레드 고갈

초당 5만 건의 결제 트랜잭션이 유입되는 대규모 시스템에서 `NAIVE_INDIVIDUAL_FSYNC` 방식을 사용하면 다음과 같은 대참사가 발생합니다:

```
[Client Threads] (500개 동시 커밋 시도)
       |
       v
[WAL Mutex Lock] (단 1개 스레드만 진입 가능)
       |
       +---> [Thread 1]: write() -> fsync() 실행 (200us 동안 락 점유)
       |         |
       |         v  (대기 중인 499개 스레드는 D-state로 잠듦)
       |
       +---> [Thread 2]: Thread 1 완료 후 락 획득 -> fsync() (200us 추가 대기)
       |
       +---> [Thread 3]: Thread 2 완료 후 락 획득 -> fsync() (200us 추가 대기)
       ...
       +---> [Thread 500]: 앞선 499개의 fsync가 끝날 때까지 100,000us (100ms) 동안 강제 대기!
```

1. **락 콘보이 (Lock Convoy)**:
   - 느린 I/O 연산(`fsync`)을 전역 뮤텍스 안에서 동기적으로 실행하면서 대기 큐가 기하급수적으로 길어집니다.
2. **CPU 기아 및 D-상태 프로세스 폭발**:
   - 수백 개의 스레드가 디스크 I/O 완료를 기다리며 `TASK_UNINTERRUPTIBLE` 상태로 잠들고, 커넥션 풀이 완전히 고갈되어 신규 연결에 대해 504 Gateway Timeout이 발생합니다.
3. **선형적으로 누적되는 대기 지연**:
   - $N$번째 트랜잭션의 커밋 지연시간은 앞선 $N-1$개의 fsync 시간의 합이 되며, 평균 지연시간이 수십~수백 배로 폭증합니다.

---

## 4. 그룹 커밋(Group Commit)의 발전사

### 4.1 고전적 접근: 정적 딜레이 그룹 커밋 (Static Delay Group Commit)
초기 PostgreSQL 등에서 도입된 방식으로, `commit_delay`와 `commit_siblings` 설정 변수를 사용했습니다:
- 리더 트랜잭션이 커밋하려고 할 때, 현재 활성화된 동시 트랜잭션 수(형제 수)가 `commit_siblings` 이상이면 의도적으로 `commit_delay`($100\sim500\,\mu\text{s}$) 동안 CPU를 양보하거나 `usleep()`을 호출하여 대기합니다.
- 대기하는 동안 다른 트랜잭션들이 큐에 쌓이기를 기대하고, 잠에서 깬 뒤 모인 트랜잭션들을 한 번의 `fsync()`로 묶어 처리합니다.

#### 정적 딜레이의 한계
- **지연시간 인플레이션(Latency Inflation)**: 트래픽이 많을 때는 배칭 효과가 있지만, 각 그룹마다 인위적인 수면 시간이 추가되어 p99 지연시간이 늘어납니다.
- **예측 불가능한 워크로드에서의 비효율**: 트래픽이 일시적으로 줄어들면 기준 형제 수를 채우지 못해 개별 fsync로 폴백되고, 경계값 부근에서 심한 지연 변동성(Jitter)이 발생합니다.

---

### 4.2 현대적 표준: 리더-팔로워 파이프라인 그룹 커밋 (Pipelined Group Commit)
MySQL 5.6+ Binary Log Group Commit (BLGC) 및 PostgreSQL 9.3+부터 현대 분산 데이터베이스(CockroachDB, TiKV)와 합의 엔진(Raft, etcd)은 **슬립 없는 락-프리 파이프라인 그룹 커밋** 아키텍처를 채택했습니다.

```
[Client Tx 1] (최초 도착) ----> [Group Leader] 선정!
                                      |
[Client Tx 2] (동시 도착) ----> [Queue Enqueue] (Follower 1)
[Client Tx 3] (동시 도착) ----> [Queue Enqueue] (Follower 2)
[Client Tx 4] (동시 도착) ----> [Queue Enqueue] (Follower 3)
                                      |
                                      v
1. Leader가 Registration Queue를 원자적으로 동결 및 일괄 인출
2. Leader가 Tx 1, 2, 3, 4의 WAL 데이터를 단 1회의 순차 write()로 기록
3. Leader가 단 1회의 fsync() 호출
4. fsync 완료 후, Leader가 Tx 2, 3, 4에게 완료 신호(Broadcast Notification) 전송!
                                      |
                     +----------------+----------------+
                     v                                 v
          [Follower 2, 3, 4 기상]              [Leader 완료 응답]
          (디스크 I/O 0회로 커밋 완료!)
```

### 파이프라인 그룹 커밋의 핵심 장점
1. **0초 대기 (Zero Artificial Delay)**: 인위적인 수면 시간 없이, 리더가 준비되는 즉시 현재 대기 큐에 있는 모든 트랜잭션을 쓸어 담습니다.
2. **동시성 기반 자연 배칭 (Self-Regulating Batching)**:
   - 트래픽이 적을 때(1개 요청): 리더는 대기 없이 즉시 플러시하므로 지연시간이 최소화됩니다.
   - 트래픽이 폭주할 때(수천 개 요청): 리더가 1번 `fsync()`($200\,\mu\text{s}$)를 수행하는 동안 수십~수백 개의 후행 트랜잭션이 큐에 쌓이므로, 그룹 크기가 자동으로 커집니다.
3. **디스크 I/O 증폭률 역전**:
   - 트래픽이 10배 증가해도 `fsync()` 호출 횟수는 거의 증가하지 않으며, 그룹 크기만 10배로 커집니다.
   - 물리적 플러시 횟수를 90%~99% 절감하여 스토리지 하드웨어 수명을 보호하고 처리량을 10배 이상 끌어올립니다.

---

## 5. 프로덕션 데이터베이스 실무 설정 가이드

### PostgreSQL
- `synchronous_commit = on`: 트랜잭션 커밋 시 WAL 디스크 플러시를 보장 (기본값).
- `commit_delay`: 그룹 커밋을 위해 대기할 마이크로초(기본값 0 - 비활성).
- `commit_siblings`: `commit_delay`를 적용하기 위한 최소 활성 트랜잭션 수 (기본값 5).
- `wal_sync_method = fdatasync`: 메타데이터 갱신을 제외하고 순수 데이터만 동기화하여 지연시간 단축.

### MySQL (InnoDB)
- `innodb_flush_log_at_trx_commit = 1`: ACID 완벽 준수 (커밋마다 Redo Log 플러시).
- `sync_binlog = 1`: 바이너리 로그 완벽 동기화.
- `binlog_group_commit_sync_delay`: 바이너리 로그 fsync 전 추가 대기 마이크로초.
- `binlog_group_commit_sync_no_delay_count`: 해당 개수의 트랜잭션이 모이면 딜레이 없이 즉시 fsync 실행.
