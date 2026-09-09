# #160 Redis Cluster 슬롯 마이그레이션 중 왜 전체 서버가 멈춰요?!: MOVED vs ASK 리다이렉트 핑퐁 참사와 클라이언트 라우팅 캐시 스톰 (Redis Cluster Slot Migration: MOVED vs ASK Redirection Storm)

## 1. 실무 장애 시나리오: "온라인 슬롯 리샤딩 버튼 하나 눌렀을 뿐인데, 초당 수만 건의 500 에러와 커넥션 풀 폭발?!"

글로벌 실시간 게임 및 이커머스 서비스를 운영하는 '젤리플랫폼'의 인프라 데이터팀은 분산 캐시 티어로 **Redis Cluster (16,384개 해시 슬롯, 3개 마스터 노드)**를 운용하고 있었습니다.

블랙 프라이데이 트래픽 급증에 대비하여 신규 마스터 노드(`node-4`)를 클러스터에 합류시킨 후, 기존 `node-1`의 핫스팟 슬롯(슬롯 `1649`)을 무중단 온라인 리샤딩(Online Resharding) 방식으로 `node-4`로 마이그레이션하는 배치 작업을 실행했습니다:

```bash
# 슬롯 1649 마이그레이션 착수
node-4> CLUSTER SETSLOT 1649 IMPORTING node-1
node-1> CLUSTER SETSLOT 1649 MIGRATING node-4
```

```
                        [ Client / Microservices ]
                                     │
                             GET {user:1000}:orders
                                     ▼
                ┌──────────────────────────────────────────┐
                │ 1. Client sends query to node-1          │
                │    (Client Slot Cache: 1649 -> node-1)   │
                └────────────────────┬─────────────────────┘
                                     │
                                     ▼
                      ┌──────────────────────────────┐
                      │ node-1 (MIGRATING to node-4) │
                      │ Key already migrated!        │
                      │ Returns: -ASK 1649 node-4    │
                      └──────────────┬───────────────┘
                                     │
      ┌──────────────────────────────┴──────────────────────────────┐
      │                                                             │
      ▼ [ BUGGY / NAIVE CLIENT ]                                    ▼ [ SMART CLIENT (RFC) ]
┌─────────────────────────────────────────┐          ┌─────────────────────────────────────────┐
│ 2. Erroneously updates local slot cache:│          │ 2. Keeps slot cache unchanged (node-1)! │
│    slot_cache[1649] = node-4            │          │    Sends 1-shot ASKING to node-4!       │
│ 3. Forgets ASKING flag, queries node-4! │          │ 3. node-4 serves request successfully!  │
└────────────────────┬────────────────────┘          └─────────────────────────────────────────┘
                     │
                     ▼
      ┌──────────────────────────────┐
      │ node-4 (IMPORTING from node-1│
      │ No ASKING flag received!     │
      │ Returns: -MOVED 1649 node-1  │
      └──────────────┬───────────────┘
                     │
                     ▼
┌─────────────────────────────────────────┐
│ 4. Receives MOVED, updates cache back!  │
│    slot_cache[1649] = node-1            │
│ 5. Queries node-1 -> Returns -ASK!      │
│    Queries node-4 -> Returns -MOVED!    │
│    ==> INFINITE PING-PONG STORM!        │
│    ==> TOO_MANY_REDIRECTS EXCEPTION!    │
└─────────────────────────────────────────┘
```

그러자 서비스 전역에서 믿을 수 없는 대참사가 벌어졌습니다:
1. **커넥션 풀 고갈과 레이턴시 폭발**:
   - 마이그레이션 중인 슬롯 `1649`로 유입된 요청들이 `node-1`과 `node-4` 사이에서 초당 수십만 번의 `-ASK` $\leftrightarrow$ `-MOVED` 핑퐁 리다이렉트를 일으켰습니다.
   - 각 노드의 클라이언트 연결 수가 상한선(`maxclients: 10000`)에 도달하며 커넥션 풀이 마비되었고, 응답 시간이 0.5ms에서 수 초 단위로 치솟았습니다.
2. **`TooManyRedirectsException` 연쇄 발생**:
   - 클라이언트의 최대 재시도 횟수(`max_redirects: 5`)를 단숨에 소진하며 `TooManyRedirectsException`이 쏟아져 나와 결제 및 장바구니 서비스가 완전 마비되었습니다.
3. **캐시 스래싱(Cache Thrashing)**:
   - 일부 정상적으로 `ASKING`을 보내는 라이브러리조차 `-ASK`를 수신할 때마다 로컬 슬롯 라우팅 캐시를 `node-4`로 덮어썼습니다.
   - 그 결과, 아직 원본 노드에 남아있는 키(`{user:1000}:profile`)를 조회할 때마다 매번 `node-4`로 헛걸음했다가 `-MOVED`를 맞고 돌아오는 왕복 지연 오버헤드가 발생했습니다.

---

## 2. 장애 원인 분석: `-MOVED`와 `-ASK`의 결정적 차이

Redis Cluster 명세(RFC)에서 두 리다이렉트 응답은 완전히 다른 의미와 처리 규칙을 가집니다:

| 항목 | `-MOVED <slot> <target>` | `-ASK <slot> <target>` |
| :--- | :--- | :--- |
| **의미** | 슬롯의 영구적 소유권 이전 (Permanent Migration) | 슬롯 마이그레이션 중의 일시적 포워딩 (Transient Migration) |
| **클라이언트 슬롯 캐시 갱신** | **반드시 갱신** (`slot_cache[slot] = target`) | **절대로 갱신 금지!** (기존 슬롯 소유자 유지) |
| **타깃 노드 접속 시 규칙** | 일반 명령 그대로 전송 | **`ASKING` 명령 선행 전송 필수** (1회성 플래그 소비) |
| **미준수 시 대가** | 지속적인 1-hop 불필요한 리다이렉트 발생 | **`-ASK` $\leftrightarrow$ `-MOVED` 무한 핑퐁 리다이렉트 스톰 폭사** |

---

## 3. 구현 요구사항

본 문제에서는 Redis Cluster 환경과 3가지 클라이언트 동작 모드를 시뮬레이션하는 `RedisClusterEngine`을 구현해야 합니다.

### (1) CRC-16/XMODEM 해시 슬롯 및 해시 태그 계산
- 슬롯 개수: `0` ~ `16,383` (총 16,384개 슬롯).
- 다항식(Polynomial): `0x1021` (XMODEM/CCITT 표준, 초기값 `0x0000`).
- 해시 태그 규칙:
  - 키 문자열 내 첫 번째 `{`와 그 이후의 첫 번째 `}`를 탐색.
  - `{`와 `}` 사이에 1글자 이상의 문자열이 존재하면 해당 부분 문자열만 CRC16 해싱.
  - 빈 중괄호(`{}`), `}`가 없는 경우(`{foo`), 중괄호가 없는 경우 전체 키 문자열을 해싱.
  - 복수 중괄호(`item:{first}:{second}`)인 경우 첫 번째 온전한 `{first}` 내부만 해싱.

### (2) 클러스터 및 슬롯 마이그레이션 상태
- **노드 및 슬롯 소유권**: 각 노드는 배정된 슬롯 범위(`slots: [[s, e], ...]`)를 공식 소유합니다.
- **슬롯 마이그레이션 상태**:
  - `source` 노드는 `MIGRATING`, `target` 노드는 `IMPORTING` 상태입니다.
  - 슬롯 소유권은 `FINALIZE_SLOT` 전까지 여전히 `source` 노드에게 있습니다.
- **노드의 요청 처리 규칙**:
  1. 공식 소유자 노드가 요청을 받았을 때:
     - 슬롯이 마이그레이션 중이 아니면 로컬 스토리지에서 즉시 실행.
     - 슬롯이 마이그레이션 중일 때:
       - 해당 키가 로컬 스토리지에 존재하면 즉시 실행.
       - 해당 키가 로컬 스토리지에 존재하지 않으면 `-ASK <slot> <target_endpoint>` 응답!
  2. 타깃 노드(`target`, IMPORTING 상태)가 요청을 받았을 때:
     - 클라이언트로부터 선행 `ASKING` 플래그를 전달받았다면 요청을 정상 실행 (`GET` 시 없으면 `null`, `SET` 시 신규 생성 및 저장).
     - **`ASKING` 플래그가 전달되지 않았다면**, 자신이 정식 소유자가 아니므로 `-MOVED <slot> <official_owner_endpoint>` 응답!
  3. 무관한 제3의 노드가 요청을 받았을 때:
     - `-MOVED <slot> <official_owner_endpoint>` 응답!

### (3) 클라이언트 동작 모드 (`client_type`)
- **`SMART` (표준 준수)**:
  - `-MOVED` 수신: 로컬 슬롯 캐시를 갱신하고 대상 노드로 재시도.
  - `-ASK` 수신: **로컬 슬롯 캐시를 절대로 갱신하지 않음!** 타깃 노드로 재시도할 때 1회성 `ASKING` 플래그를 함께 전달.
- **`NAIVE_NO_ASKING` (버그 재현)**:
  - `-ASK` 수신 시 `-MOVED`처럼 취급하여 로컬 슬롯 캐시를 오염시키고, `ASKING` 플래그도 전송하지 않음 $	o$ 리다이렉트 스톰 유발.
- **`NAIVE_CACHE_MUTATE` (캐시 스래싱 재현)**:
  - `-ASK` 수신 시 `ASKING` 플래그는 전송하지만, 로컬 슬롯 캐시를 타깃 노드로 오염시킴 $	o$ 후속 미이전 키 조회 시 캐시 핑퐁 유발.

### (4) 최대 리다이렉트 제한 (`max_redirects`)
- 단일 클라이언트 명령당 허용되는 최대 홉(hop) 수는 `max_redirects`입니다.
- 홉 수가 `max_redirects`에 도달할 때까지 명령이 성공하지 못하면 `status = "TOO_MANY_REDIRECTS"`로 실패 처리합니다.

---

## 4. 입출력 형식

### 입력 형식 (JSON on `sys.stdin`)
```json
{
  "cluster_config": {
    "nodes": {
      "node-1": { "endpoint": "10.0.0.1:6379", "slots": [[0, 5460]] },
      "node-2": { "endpoint": "10.0.0.2:6379", "slots": [[5461, 10922]] },
      "node-3": { "endpoint": "10.0.0.3:6379", "slots": [[10923, 16383]] },
      "node-4": { "endpoint": "10.0.0.4:6379", "slots": [] }
    },
    "migrations": [
      { "slot": 1649, "source": "node-1", "target": "node-4" }
    ],
    "initial_storage": {
      "node-1": { "{user:1000}:profile": "AliceProfile" },
      "node-4": { "{user:1000}:orders": "AliceOrders" }
    }
  },
  "client_config": {
    "client_type": "SMART",
    "max_redirects": 5,
    "initial_cache": { "1649": "node-1" }
  },
  "commands": [
    { "type": "CLIENT", "cmd": "GET", "key": "{user:1000}:orders" },
    { "type": "CLIENT", "cmd": "GET", "key": "{user:1000}:profile" },
    { "type": "ADMIN", "action": "FINALIZE_SLOT", "slot": 1649 }
  ]
}
```

### 출력 형식 (JSON on `sys.stdout`)
```json
{
  "summary": {
    "total_client_commands": 2,
    "successful_commands": 2,
    "failed_commands": 0,
    "total_hops": 3,
    "total_moved_redirects": 0,
    "total_ask_redirects": 1
  },
  "final_client_cache": {
    "1649": "node-1"
  },
  "results": [
    {
      "type": "CLIENT",
      "cmd": "GET",
      "key": "{user:1000}:orders",
      "slot": 1649,
      "status": "SUCCESS",
      "hops": 2,
      "redirects": [
        "ASK 1649 10.0.0.4:6379"
      ],
      "result": "AliceOrders",
      "routed_node": "node-4"
    },
    {
      "type": "CLIENT",
      "cmd": "GET",
      "key": "{user:1000}:profile",
      "slot": 1649,
      "status": "SUCCESS",
      "hops": 1,
      "redirects": [],
      "result": "AliceProfile",
      "routed_node": "node-1"
    },
    {
      "type": "ADMIN",
      "action": "FINALIZE_SLOT",
      "slot": 1649,
      "status": "FINALIZED",
      "new_owner": "node-4"
    }
  ]
}
```
