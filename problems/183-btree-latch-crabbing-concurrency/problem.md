# 문제 183: B+Tree 동시성 제어: 래치 크래빙(Latch Crabbing)과 안전 노드 조기 언락

## 문제 배경
현대 고성능 데이터베이스 스토리지 엔진(MySQL InnoDB, SQLite WAL, WiredTiger, PostgreSQL 등)은 수백~수천 개의 워커 스레드가 단일 B+Tree 인덱스를 동시에 탐색(`SEARCH`)하고 갱신(`INSERT`/`DELETE`)합니다.

인덱스의 물리적 무결성을 보장하기 위해 동시성 제어(Concurrency Control)가 필수적입니다. 그러나 동시성 제어 방식에 따라 데이터베이스 시스템의 성능과 안정성은 극단적인 차이를 보입니다:

1. **전역 트리 래치 (Global Tree Latch, Coarse-Grained Locking)**:
   - 트리 루트 또는 전체 B+Tree를 하나의 거대한 뮤텍스(Global Mutex)로 보호합니다.
   - 구현은 단순하지만, 모든 동시 탐색 및 삽입 요청이 직렬화(`GLOBAL_LATCH_SERIALIZATION_BOTTLENECK`)되어 멀티코어 CPU 환경에서 처리량이 1스레드 수준으로 급락합니다.
2. **비동기화 접근 (Unsynchronized, No Latching)**:
   - 락이나 래치 없이 직접 노드를 읽고 씁니다.
   - 한 스레드가 노드 오버플로우로 인해 노드를 분할(`Split`)하고 키를 우측 형제 노드로 이동시키는 도중, 다른 스레드가 해당 노드를 탐색하면 찢어진 포인터(Torn Pointer)를 참조하거나 존재하는 키를 찾지 못하는 데이터 레이스 참사(`UNSYNCHRONIZED_DATA_RACE_CORRUPTION`)가 발생합니다.
3. **래치 크래빙 프로토콜 (Latch Crabbing / Lock Coupling)**:
   - 트리를 위에서 아래로 한 단계씩 이동할 때, 마치 게(Crab)가 집게발을 번갈아 딛듯이 부모 노드의 래치를 잡은 상태에서 자식 노드의 래치를 획득한 후 부모 래치를 해제하는 기법입니다.
   - **탐색 경로 (S-Latch Crabbing)**:
     - 루트에 공유 래치(S-Latch)를 획득합니다.
     - 하위 단계로 이동할 때마다 자식 노드에 S-Latch를 획득하고, 직후 부모 노드의 S-Latch를 즉시 해제합니다.
     - 리프 노드에 도달하여 키를 읽은 후 리프 S-Latch를 해제합니다. 여러 탐색 스레드가 동일한 경로를 비차단(Non-blocking)으로 동시에 통과할 수 있습니다.
   - **삽입 경로 (X-Latch Crabbing & Safe Node 조기 언락 최적화)**:
     - 루트에 배타 래치(X-Latch)를 획득하고 조상 래치 스택(`held_latches`)에 보관합니다.
     - 하위 단계로 이동할 때 자식 노드에 X-Latch를 획득하고 `held_latches`에 추가합니다.
     - **안전 노드(Safe Node) 검증**:
       - 삽입 연산에서 노드의 키 개수가 `max_keys` 미만(`len(keys) < max_keys`)이면 해당 노드는 **안전 노드(Safe Node)**입니다.
       - 안전 노드는 하위에서 분할이 발생하더라도 현재 노드에서 분할이 멈추므로, 그 상위 조상 노드로는 분할이 결코 전파되지 않습니다!
       - 따라서 자식 노드가 안전 노드라면, **현재까지 보유하고 있던 모든 조상 노드들의 X-Latch를 즉시 일괄 해제(Early Ancestor Unlock)**합니다!
       - 반대로 자식 노드가 안전하지 않다면(`len(keys) >= max_keys`), 최악의 경우 루트까지 분할이 전파될 수 있으므로 조상 래치들을 계속 유지합니다.
     - 리프 노드에 도달하여 삽입을 수행하고, 분할 발생 시 안전하게 승격 키를 부모로 전파합니다. 루트 분할 시 새로운 루트를 생성합니다(`ROOT_NODE_SPLIT_SAFE_UPGRADE`).

당신은 데이터베이스 엔진 코어 개발자로서, 입력된 동시성 제어 모드와 스레드 작업 시퀀스를 기반으로 B+Tree 래치 크래빙 시뮬레이터를 구현해야 합니다.

---

## 입력 형식
입력은 표준 입력(stdin)으로 하나의 JSON 객체가 주어집니다.

```json
{
  "config": {
    "concurrency_mode": "LATCH_CRABBING",
    "max_keys": 3,
    "initial_data": [
      {"key": 10, "value": "val10"}
    ]
  },
  "operations": [
    {
      "time": 0,
      "thread_id": "T1",
      "type": "INSERT",
      "key": 15,
      "value": "val15"
    },
    {
      "time": 0,
      "thread_id": "T2",
      "type": "SEARCH",
      "key": 10
    }
  ]
}
```

### 필드 설명
- `config`:
  - `concurrency_mode` (string): 동시성 제어 모드. `"LATCH_CRABBING"`, `"GLOBAL_LATCH"`, `"UNSYNCHRONIZED"` 중 하나.
  - `max_keys` (int): 노드당 최대 키 개수 (기본값: 3). `len(keys) > max_keys` 시 분할 발생.
  - `initial_data` (선택적, list): 시뮬레이션 시작 전 트리에 순차 삽입되는 초기 레코드 목록.
- `operations`: 스레드 작업 목록 (도착 시간 `time` 오름차순).
  - `time` (int): 작업이 트리 접근을 시도하는 논리적 시각 (tick).
  - `thread_id` (string): 작업을 수행하는 스레드 식별자.
  - `type` (string): `"SEARCH"` 또는 `"INSERT"`.
  - `key` (int): 정수형 검색/삽입 키.
  - `value` (string, `type == "INSERT"`일 때): 삽입할 문자열 값.

---

## 출력 형식
표준 출력(stdout)으로 JSON 객체를 들여쓰기 2칸으로 출력합니다.

```json
{
  "status": "SUCCESS",
  "concurrency_mode": "LATCH_CRABBING",
  "metrics": {
    "total_reads": 1,
    "total_inserts": 1,
    "read_successes": 1,
    "read_failures": 0,
    "root_splits": 0,
    "early_unlocked_ancestors": 1,
    "latch_contention_events": 0,
    "data_race_corruptions": 0,
    "peak_concurrent_threads": 2,
    "total_ticks": 3,
    "verdict": "LATCH_CRABBING_CONCURRENT_SUCCESS"
  },
  "read_results": [
    {
      "op_id": 1,
      "thread_id": "T2",
      "key": 10,
      "result": "val10",
      "corrupted": false
    }
  ],
  "tree_summary": {
    "root_id": "node_0",
    "total_nodes": 1,
    "depth": 1
  }
}
```

### 메트릭 설명
- `total_reads` (int): 실행된 총 검색 연산 수.
- `total_inserts` (int): 실행된 총 삽입 연산 수.
- `read_successes` (int): 성공적으로 값을 조회한 횟수.
- `read_failures` (int): 키를 찾지 못한 횟수.
- `root_splits` (int): 루트 노드가 분할되어 트리 높이가 증가한 횟수.
- `early_unlocked_ancestors` (int): 안전 노드 발견으로 조기에 해제된 조상 X-Latch의 총 누적 개수.
- `latch_contention_events` (int): 래치 획득 충돌로 인해 스레드가 대기(stall)한 횟수.
- `data_race_corruptions` (int): 비동기화 분할 도중 발생한 읽기 데이터 손상/불일치 횟수.
- `peak_concurrent_threads` (int): 동시에 활성화된 최대 스레드 수.
- `total_ticks` (int): 모든 작업이 완료될 때까지 소요된 총 틱 수.
- `verdict` (string): 판정 결과 문자열.

### 판정(Verdict) 규칙
1. `concurrency_mode == "UNSYNCHRONIZED"`이고 `data_race_corruptions > 0`:
   - `"UNSYNCHRONIZED_DATA_RACE_CORRUPTION"`
2. `concurrency_mode == "GLOBAL_LATCH"`이고 `latch_contention_events > 0`:
   - `"GLOBAL_LATCH_SERIALIZATION_BOTTLENECK"`
3. `concurrency_mode == "LATCH_CRABBING"`이고 `root_splits > 0`:
   - `"ROOT_NODE_SPLIT_SAFE_UPGRADE"`
4. `concurrency_mode == "LATCH_CRABBING"`이고 (`early_unlocked_ancestors > 0` 또는 `peak_concurrent_threads > 1`):
   - `"LATCH_CRABBING_CONCURRENT_SUCCESS"`
5. 기타 기본 경우:
   - `"STANDARD_OPERATION"`
