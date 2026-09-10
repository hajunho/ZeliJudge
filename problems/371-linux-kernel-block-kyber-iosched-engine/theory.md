# Linux Kernel Block Layer Kyber I/O Scheduler 심층 아키텍처 및 자가 튜닝 제어 이론 분석

## 1. 개요: 초고속 플래시와 I/O 스케줄러의 패러다임 변화

과거 하드 디스크 드라이브(HDD) 시대의 I/O 스케줄러(CFQ, Deadline, AS)는 물리적 헤드의 기계적 이동(Seek Time)을 최소화하기 위해 엘리베이터 정렬(Elevator Sorting)과 연속 섹터 병합(Request Merging)에 집중했습니다.

그러나 초당 100만 IOPS와 수십 마이크로초의 지연 시간을 갖는 NVMe SSD 및 ZNS 환경에서는:
1. 기계적 탐색 시간이 존재하지 않으므로 복잡한 섹터 정렬 알고리즘은 불필요합니다.
2. 멀티 하드웨어 디스패치 큐(`blk-mq`) 구조에서 전역 락(Global Lock)이나 무거운 RB-Tree 탐색은 코어 확장성을 파괴합니다.
3. 가장 중요한 문제는 **"동기식 읽기(Read)의 지연 시간 보장"**입니다. 백그라운드에서 대량의 더티 페이지 라이트백(Dirty Page Writeback)이나 컴팩션/트림 작업이 하드웨어 큐를 꽉 채우면, 웹 서버나 데이터베이스의 사용자 읽기 쿼리가 큐 뒤에 갇혀 P99 테일 레이턴시가 수백 배 치솟습니다.

---

## 2. 카이버(Kyber)의 설계 철학과 도메인 분리

페이스북의 엔지니어들은 복잡한 공정 큐잉(Fair Queueing) 대신, 단순하고 가벼운 **토큰 버킷 기반 자가 튜닝 피드백 루프(Self-Tuning Feedback Loop)**를 구현했습니다:

```c
struct kyber_queue_data {
    struct request_queue *q;
    unsigned int async_depth;       /* 동적 조절되는 비동기 큐 깊이 */
    uint64_t read_lat_nsec;         /* 읽기 목표 지연 시간 (기본 2ms) */
    uint64_t sync_write_lat_nsec;   /* 동기 쓰기 목표 지연 시간 (기본 10ms) */
    struct kyber_stat stat[KYBER_NUM_DOMAINS];
};
```

### 2.1 3대 I/O 도메인
- `KYBER_READ`: 동기 읽기. 시스템 응답성에 직결되므로 스케줄러 수준에서 제한 없이 즉시 디스패치.
- `KYBER_SYNC_WRITE`: O_SYNC / fsync 동기 쓰기. 별도의 상한 목표(10ms)를 적용.
- `KYBER_ASYNC`: 비동기 버퍼드 쓰기 및 가비지 컬렉션. 읽기 지연 시간에 따라 큐 깊이가 적극적으로 조절(Throttling)되는 제어 대상.

---

## 3. 피드백 제어 알고리즘 (AIMD의 변형)

카이버의 자가 튜닝 메커니즘은 TCP 혼잡 제어의 AIMD(Additive Increase Multiplicative Decrease)와 유사한 피드백 루프를 따릅니다:

1. **샘플링 윈도우**:
   - 매 $N$개의 요청 완료마다 윈도우 내 요청들의 완료 지연 시간 통계를 집계합니다.
   - 평균값이 아닌 **P99(99th Percentile) 지연 시간**을 측정함으로써 극단적인 꼬리 지연(Tail Latency) 스파이크를 즉각 감지합니다.

2. **승수적 감소 (Multiplicative Decrease / Scale Down)**:
   - 읽기 P99가 `target_read_lat_us`를 초과하면, 디바이스 컨트롤러가 비동기 쓰기 처리로 인해 과포화 상태에 빠진 것입니다.
   - 즉시 비동기 큐 깊이를 **절반($\div 2$)**으로 축소하여 비동기 디스패치를 급격히 제한하고 읽기 트래픽에 큐 슬롯을 양보합니다.

3. **가산적 증가 (Additive Increase / Scale Up)**:
   - 읽기 P99가 목표치 이하로 안정되면, 스토리지의 남는 대역폭을 비동기 쓰기가 활용할 수 있도록 큐 깊이를 **$+1$씩 점진적으로 확장**합니다.

---

## 4. 실무 운영 평가

- **BFQ vs Kyber**: BFQ는 정교한 대역폭/지연시간 비례 보장을 제공하지만 CPU 소모량이 커서 고성능 NVMe에서는 병목이 됩니다. Kyber는 단 2~3개의 원자적 카운터 조작만으로 동작하여 높은 IOPS 환경에서 탁월한 효율을 발휘합니다.
- **클라우드 및 대규모 DB**: RocksDB, MySQL, Cassandra 등 LSM-Tree 및 WAL 기반 시스템에서 플러시 쓰기가 사용자 읽기 트랜잭션을 방해하지 않도록 보호하는 데 가장 널리 권장되는 기본 스케줄러입니다.
