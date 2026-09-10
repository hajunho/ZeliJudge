# [이론 및 배경] RocksDB WriteThread와 동시성 LSM-Tree 쓰기 파이프라인

## 1. LSM-Tree 쓰기 경로의 치명적 동시성 병목

전통적인 LevelDB 및 초기 RocksDB에서는 데이터 쓰기 과정이 단일 전역 뮤텍스(`db_mutex`)로 직렬화(Serialize)되어 있었습니다:

```
Thread 1: [Lock Mutex] ──> [Append WAL] ──> [fsync] ──> [Insert MemTable] ──> [Unlock]
Thread 2: (Waiting...)
Thread 3: (Waiting...)
```

이 구조에서는 아무리 빠른 고성능 NVMe SSD와 64코어 CPU를 탑재하더라도 다음과 같은 3대 병목에 직면합니다:
1. **fsync 직렬화 지연**: `fdatasync()`는 NVMe 기준 30~80µs가 소요되며, 100개 스레드가 순차 실행 시 초당 쓰기 처리량이 $1,000\text{ IOPS}$ 미만으로 제한됩니다.
2. **뮤텍스 락 핑퐁(Lock Cache-Line Bouncing)**: 수많은 코어가 동일한 뮤텍스 캐시 라인을 수정하려 경쟁하면서 CPU 캐시 일관성 프로토콜(MESI) 트래픽이 폭증합니다.
3. **스킵리스트 직렬 삽입**: CPU 연산인 멤테이블(Concurrent SkipList) 삽입 작업조차 단일 스레드에 의해 순차적으로 수행되어 멀티코어를 전혀 활용하지 못합니다.

---

## 2. WriteThread 락리스 리더-팔로워(Leader-Follower) 아키텍처

Meta(구 Facebook) 엔지니어들은 이 문제를 해결하기 위해 `WriteThread`라는 전용 락리스 큐 기반 배치 병합 기법을 도입했습니다 (`db/write_thread.h`, `db/write_thread.cc`).

1. **원자적 등록(Atomic CAS Enqueue)**:
   - 각 스레드는 `WriteThread::Writer` 노드를 생성하고 원자적 교환(Atomic Exchange)으로 최신 대기 큐(`newest_writer`)의 헤드에 자신을 등록합니다.
2. **리더 선출**:
   - 큐에 진입했을 때 자신이 첫 번째 쓰기 작업자라면 즉시 **리더(Leader)**가 됩니다.
   - 이후에 도착한 스레드들은 **팔로워(Follower)**로 지정되어 자신의 상태 플래그(`STATE_GROUP_LEADER`, `STATE_COMPLETED` 등)를 스핀-웨이트(Spin-wait)하거나 조건 변수로 대기합니다.
3. **배치 병합(`JoinBatchGroup`)**:
   - 리더는 대기 큐를 한 번에 인출(Batch Extraction)하여 연결 리스트를 순회하며, 허용된 최대 바이트 수(`max_batch_group_bytes`) 및 최대 스레드 수(`max_batch_group_count`) 한도 내에서 팔로워들의 `WriteBatch`를 하나의 연속된 배치로 묶어냅니다.

---

## 3. 동기화 비용 분산 상각(Amortized fsync)

배치 그룹핑의 가장 강력한 경제적 효과는 **I/O 및 fsync의 분산 상각**입니다:
- 그룹 내 10개의 스레드 중 단 1개 스레드만 `WriteOptions.sync = true`를 요구하더라도, 리더는 전체 10개 스레드의 병합 배치를 단 1회의 디스크 I/O와 1회의 `fsync`로 디스크에 커밋합니다.
- 결과적으로 50µs의 디스크 지연시간을 10개 스레드가 나누어 가지게 되므로, 개별 스레드당 실효 fsync 비용은 5µs로 10배 절감됩니다.

---

## 4. 파이프라인 쓰기(Pipelined Write)와 동시성 멤테이블(Concurrent MemTable)

기존 배치 그룹핑에서는 리더가 WAL을 쓴 후, 팔로워들의 멤테이블 삽입까지 리더 혼자서 도맡아 처리했습니다. 이는 CPU가 많은 서버에서 리더가 연산 병목이 되는 2차 문제를 낳았습니다.

이를 극복한 최신 기술이 **파이프라인 쓰기(Pipelined Write, `enable_pipelined_write=true`)**입니다:

```
[Timeline]
WAL Pipeline Stage   : ───[ Leader Writes Merged WAL ]───>
MemTable Stage (Core 1):                                   [ Thread 1 Inserts Its Batch ]
MemTable Stage (Core 2):                                   [ Thread 2 Inserts Its Batch ]
MemTable Stage (Core 3):                                   [ Thread 3 Inserts Its Batch ]
```

1. **시퀀스 번호 사전 분배**: 리더는 WAL 기록 전/후에 그룹 내 모든 키에 대한 단조 증가 시퀀스 번호 구간을 계산하여 각 팔로워에게 사전 할당합니다.
2. **동시성 멤테이블 분산 삽입 (`allow_concurrent_memtable_write=true`)**:
   - WAL 기록이 끝나자마자 리더는 대기 중인 모든 팔로워에게 즉시 신호를 보냅니다.
   - 각 스레드는 자신이 할당받은 시퀀스 번호를 가지고 인라인 락리스 동시성 스킵리스트(Concurrent SkipList with Memory Barrier)에 독립적으로 동시 삽입을 수행합니다.
   - 모든 CPU 코어가 동시에 멤테이블 삽입 연산에 참여하므로, 초대형 배치에서도 쓰기 처리량이 CPU 코어 수에 비례하여 선형적으로 스케일아웃(Scale-out)됩니다.
