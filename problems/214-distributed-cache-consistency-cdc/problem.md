# Problem 214: DB는 업데이트됐는데 레디스에는 옛날 데이터가 영원히 남아있다고요?!: 분산 캐시 일관성(Distributed Cache Consistency)과 Cache-Aside 이중 쓰기(Dual-Write) 동시성 레이스: 지연된 이중 삭제(Delayed Double Delete) vs 트랜잭셔널 CDC(Debezium/Kafka) 캐시 무효화 (Distributed Cache Consistency: Cache-Aside Dual-Write Race Conditions, Delayed Double Delete vs Transactional CDC Invalidation)

## 문제 배경 및 개요

대규모 전자상거래(E-Commerce) 및 핀테크 결제 플랫폼을 운영하는 분산 백엔드 엔지니어링 팀은 블랙 프라이데이 타임세일 이벤트 도중 충격적인 **"분산 캐시 영구 불일치(Distributed Cache Inconsistency) 및 유령 가격 참사"**를 겪었습니다:

> "DB 관리자가 긴급하게 상품 가격을 2,000,000원에서 1,500,000원으로 인하 업데이트를 완료했습니다.  
> 그런데 수천 명의 사용자가 장바구니에 담을 때마다 여전히 2,000,000원으로 결제창이 뜨고 있습니다!  
> 확인해 보니 MySQL DB에는 분명히 150만원으로 저장되어 있는데, Redis 캐시에는 옛날 가격 200만원이 영원히 사라지지 않고 박혀 있었습니다!"

전 세계 수많은 백엔드 시스템이 성능 향상을 위해 MySQL/PostgreSQL 앞단에 Redis를 두고 **Cache-Aside(Lazy Loading)** 패턴을 사용합니다:
- **읽기**: 캐시 조회 $\to$ 적중(HIT) 시 반환. 미적중(MISS) 시 DB 조회 $\to$ 캐시 적재 $\to$ 반환.
- **쓰기**: DB 갱신 $\to$ 캐시 삭제(`redis.delete(key)`).

그러나 동시성 트래픽이 몰아치는 분산 환경에서 단순한 Cache-Aside 패턴은 치명적인 **동시성 레이스 컨디션(Race Condition)**과 **이중 쓰기 실패(Dual-Write Network Failure)**에 무방비로 노출됩니다:

```
[참사 1: 캐시 미스 읽기와 동시 쓰기 트랜잭션의 순서 역전 레이스]
Client A (읽기)                       Client B (쓰기: 150만원 갱신)
      │                                             │
1. Cache MISS 발생!                                │
   DB 조회 시작 (옛날 값 200만원 읽음)              │
      │                                             │
      │ (DB 읽기가 20ms 지연되는 틈에!)               ▼
      │                                  2. DB에 150만원 UPDATE & COMMIT!
      │                                  3. Redis 캐시 삭제 시도 (이미 비어있음)
      ▼                                             │
4. Client A의 DB 읽기 완료!                         │
   옛날 값 200만원을 캐시에 덮어씀 (SET item 200만)!│
      │                                             │
===> 결과: DB에는 최신값 150만원, Redis 캐시에는 옛날값 200만원 영구 잔류!
     이후 수만 건의 읽기 요청이 캐시 적중(HIT)을 일으키며 옛날 가격으로 결제되는 대형 사고 발생!
```

```
[참사 2: 이중 쓰기 네트워크 장애 (Dual-Write Network Failure)]
Application ─── 1. DB UPDATE 성공 (Commit) ───► MySQL (최신 데이터 반영 완료)
Application ─── 2. redis.delete() 시도 ───────► Redis (네트워크 타임아웃 / 소켓 끊김 에러 발생!)
===> 결과: 캐시 삭제가 누락되어 캐시의 옛날 데이터가 무한정 남아있게 됨!
```

이 고질적인 분산 캐시 불일치를 해결하기 위해 업계에서는 **지연된 이중 삭제(Delayed Double Delete)**와 넷플릭스·메타·우버의 표준인 **트랜잭셔널 CDC(Change Data Capture) 기반 캐시 무효화** 아키텍처를 도입했습니다.

당신은 분산 아키텍트로서, 나이브한 Cache-Aside 방식의 레이스 컨디션을 재현하고, 지연된 이중 삭제의 한계와 트랜잭셔널 CDC 기반 캐시 무효화의 완벽한 일관성 메커니즘을 검증하는 시뮬레이션 엔진을 구현해야 합니다.

---

## 3대 캐시 일관성 처리 모드 명세

### 1. `NAIVE_CACHE_ASIDE_UPDATE` (나이브 캐시 어사이드 모드)
- DB 갱신 후 애플리케이션 레벨에서 캐시를 단순 삭제합니다.
- 캐시 미스 읽기와 쓰기 트랜잭션이 겹치면, 지연된 읽기 결과가 최신 DB 갱신을 덮어써 캐시가 영구 오염됩니다.
- 캐시 삭제 네트워크 실패(`simulate_delete_failure: true`) 발생 시 캐시가 영구히 갱신되지 않습니다.
- 평가 판정: 캐시와 DB 값 불일치가 남거나 과거 데이터 조회가 발생하면 `CACHE_INCONSISTENCY_STALE_DATA_DETECTED` (`status: FAILED`).

### 2. `DELAYED_DOUBLE_DELETE` (지연된 이중 삭제 모드)
- 쓰기 시점에 1차 캐시 삭제 $\to$ DB 갱신 $\to$ 비동기 타이머(`delayed_delete_wait_ms`, 예: 100ms) 후 2차 캐시 삭제를 수행합니다.
- 1차 삭제와 DB 갱신 사이에 침투한 읽기 요청이 옛날 값을 캐시에 채우더라도, 100ms 후 실행되는 2차 삭제가 오염된 캐시를 날려버려 최종 일관성(Eventual Consistency)을 달성합니다.
- **취약점**: 100ms 대기 윈도우 동안 일시적 과거 데이터 조회가 발생할 수 있으며, DB 슬로우 쿼리(예: 150ms)로 인해 2차 삭제보다 늦게 캐시 적재가 끝나면 여전히 오염될 수 있습니다.
- 평가 판정: 2차 삭제로 최종 일치에 도달하면 `DELAYED_DOUBLE_DELETE_EVENTUAL_CONSISTENCY` (`status: SUCCESS`), 윈도우 초과로 오염되면 `CACHE_INCONSISTENCY_STALE_DATA_DETECTED` (`status: FAILED`).

### 3. `TRANSACTIONAL_CDC_CACHE_INVALIDATION` (트랜잭셔널 CDC 캐시 무효화 모드)
- 애플리케이션은 **오직 데이터베이스만 갱신**합니다 (Dual-Write 원천 제거!).
- MySQL Binlog / PostgreSQL WAL을 Debezium 등 CDC 엔진이 감지하여 Kafka 토픽으로 발행하고, 캐시 무효화 컨슈머가 이를 수신하여 캐시를 무효화합니다.
- 버전 번호(Version / LSN) 추적을 통해, DB 버전보다 낮은 과거 읽기 결과가 캐시를 역주행 덮어쓰기(Stale Backfill)하는 것을 원천 거부(Discard)합니다.
- 이중 쓰기 네트워크 실패가 원천 소멸하며, 0건의 과거 데이터 조회와 100% 무결성을 보장합니다.
- 평가 판정: 완벽한 무결성을 달성하면 `OPTIMAL_TRANSACTIONAL_CDC_CONSISTENCY` (`status: SUCCESS`).

---

## 입력 형식

표준 입력(Standard Input)으로 단일 JSON 객체가 주어집니다:

```json
{
  "config": {
    "mode": "TRANSACTIONAL_CDC_CACHE_INVALIDATION",
    "db_read_latency_ms": 20.0,
    "delayed_delete_wait_ms": 100.0,
    "cdc_delay_ms": 10.0
  },
  "initial_db": {
    "user_101": 5000
  },
  "initial_cache": {},
  "events": [
    {"timestamp_ms": 5.0, "action": "READ", "key": "user_101"},
    {"timestamp_ms": 10.0, "action": "WRITE", "key": "user_101", "new_value": 8000},
    {"timestamp_ms": 30.0, "action": "READ", "key": "user_101"},
    {"timestamp_ms": 150.0, "action": "READ", "key": "user_101"}
  ]
}
```

---

## 출력 형식

표준 출력(Standard Output)으로 진단 시뮬레이션 결과 JSON을 들여쓰기 2칸(`indent=2`)으로 출력합니다:

```json
{
  "status": "SUCCESS",
  "verdict": "OPTIMAL_TRANSACTIONAL_CDC_CONSISTENCY",
  "mode": "TRANSACTIONAL_CDC_CACHE_INVALIDATION",
  "metrics": {
    "total_read_requests": 3,
    "cache_hits": 1,
    "cache_misses": 2,
    "total_write_requests": 1,
    "db_updates_committed": 1,
    "cache_deletions_executed": 1,
    "stale_cache_reads": 0,
    "inconsistent_keys_at_end": [],
    "cache_hit_rate_pct": 33.33,
    "consistency_rate_pct": 100.0
  }
}
```

---

## 판정 기준 (Verdict Rules)

1. **`CACHE_INCONSISTENCY_STALE_DATA_DETECTED`**: 동시성 레이스 컨디션, 이중 쓰기 실패, 또는 슬로우 쿼리로 인해 캐시와 DB 간에 데이터 불일치가 남거나 과거 데이터 조회가 발생한 경우 (`status: FAILED`).
2. **`DELAYED_DOUBLE_DELETE_EVENTUAL_CONSISTENCY`**: 지연된 이중 삭제를 통해 중간 윈도우의 일시적 불일치를 극복하고 시뮬레이션 종료 시점에 모든 키의 최종 일관성을 달성한 경우 (`status: SUCCESS`).
3. **`OPTIMAL_TRANSACTIONAL_CDC_CONSISTENCY`**: 트랜잭셔널 CDC 스트리밍과 버전 게이트를 통해 단 한 건의 과거 데이터 조회도 없이 100% 무결성을 달성한 경우 (`status: SUCCESS`).
4. **`CLEAN_CACHE_CONSISTENCY`**: 읽기 중심 워크로드에서 경합 없이 일관성이 유지된 경우 (`status: SUCCESS`).
