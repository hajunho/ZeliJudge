# Problem 064: 물리 삭제의 위험과 소프트 딜리트 & CDC 툼스톤 (Hard Delete vs Soft Delete & CDC Tombstone)

## 문제 설명

대규모 이커머스 플랫폼을 운영 중인 당신의 회사에서 대형 회계 및 데이터 참사가 발생했습니다:
> "한 사용자가 회원 탈퇴 버튼을 눌렀을 뿐인데,  
> DB 외래키에 걸려 있던 `ON DELETE CASCADE` 제약조건 때문에 그 회원의 5년간 주문/결제 내역 100건이 영구 소각되었습니다!  
> 국세청 세무조사에서 수천만 원의 매출 증빙이 누락되었고, 탈퇴한 회원이 다시 가입하려 해도 과거 내역이 영구 복구 불가능합니다!  
> 게다가 메인 검색엔진(Elasticsearch)과 Redis 캐시에는 삭제 소식이 전파되지 않아 검색창에 이미 탈퇴한 회원의 프로필이 유령처럼 계속 노출되고 있습니다!"

원인은 데이터베이스에서 흔히 저지르는 **물리 삭제(Hard Delete)** 안티패턴이었습니다.
- 물리 삭제(`DELETE FROM users`)는 연관된 결제/주문 감사 데이터를 연쇄 소각시키며,
- 분산 이벤트 파이프라인(CDC / Kafka)에 명시적인 삭제 신호를 전달하지 못해 다운스트림 캐시에 유령 데이터가 영구 잔류하게 만듭니다.

당신은 엔터프라이즈의 표준인 **소프트 딜리트(Soft Delete / 논리 삭제)**와 **CDC 툼스톤(Tombstone)** 아키텍처를 구현해야 합니다.
- 유저 삭제 시 레코드를 물리적으로 지우지 않고 논리적 삭제 마커(`deleted_at`)를 기록하여, 과거 주문/회계 데이터를 100% 안전하게 보존합니다.
- 삭제 발생 시 다운스트림 분산 캐시/검색엔진에 **툼스톤(Tombstone: 값 없는 삭제 마커)**을 즉시 전파하여 유령 데이터를 완벽하게 축출(`Evict`)합니다.
- 언제든 관리자 권한으로 원클릭 복구(`RESTORE`)가 가능하도록 만듭니다.

동일한 액션 시퀀스에 대해 **Hard Delete 모델**과 **Soft Delete & CDC Tombstone 모델**을 동시에 시뮬레이션하고 비교하는 프로그램을 작성하세요.

---

## 시스템 요구사항 및 동작 규칙

### 1. 두 모델의 동작 비교

#### 1) Hard Delete 모델 (결함 있는 기존 모델)
- `INSERT_USER <id> <name>`: 유저를 DB에 추가하고, 캐시에도 동기화합니다.
- `INSERT_ORDER <order_id> <user_id> <amount>`: 유저가 DB에 존재하면 주문을 추가합니다 (`OK`). 존재하지 않으면 `FAIL_USER_NOT_FOUND`.
- `DELETE_USER <id>`:
  - DB에서 유저 레코드를 물리 삭제합니다.
  - **`ON DELETE CASCADE` 발동**: 해당 유저의 모든 과거 주문 레코드가 영구 소각됩니다 (`USER_DELETED_CASCADE(<cnt>)`).
  - 다운스트림 캐시에는 삭제 툼스톤이 전파되지 않아 캐시에 유저 데이터가 그대로 잔류합니다.
- `RESTORE_USER <id>`: 물리 삭제되었으므로 복구할 수 없습니다 (`RESTORE_FAIL_NOT_FOUND`).
- `QUERY_ACTIVE_USERS`: 현재 DB에 물리적으로 존재하는 유저 목록을 사전순으로 반환합니다.
- `QUERY_AUDIT_ORDERS <user_id>`: 해당 유저의 주문 수량과 총 금액을 집계합니다. 유저가 삭제되었다면 주문도 함께 증발하여 `ORDERS=0,TOTAL=0`이 됩니다.
- `QUERY_CACHE <id>`:
  - 캐시에 데이터가 남아있는데 DB에는 없는 상태라면 **유령 캐시 히트(`GHOST_CACHE_HIT`)**로 판정합니다.

#### 2) Soft Delete & CDC Tombstone 모델 (안전한 엔터프라이즈 모델)
- `INSERT_USER <id> <name>`: 유저를 DB에 추가하고(`deleted = False`), 캐시에도 동기화합니다.
- `INSERT_ORDER <order_id> <user_id> <amount>`:
  - 유저가 존재하지 않으면 `FAIL_USER_NOT_FOUND`.
  - 유저가 이미 논리 삭제(`deleted == True`) 상태라면 주문을 거절합니다 (`FAIL_USER_DELETED`).
  - 활성 유저라면 정상 주문을 등록합니다 (`OK`).
- `DELETE_USER <id>`:
  - 유저의 논리 삭제 플래그를 참으로 설정합니다 (`deleted = True`).
  - **주문 데이터는 영구 보존**됩니다!
  - **CDC Tombstone 발행**: 다운스트림 캐시에 툼스톤을 전송하여 캐시에서 해당 유저를 즉시 제거합니다 (`USER_SOFT_DELETED_TOMBSTONE_SENT`).
- `RESTORE_USER <id>`:
  - 논리 삭제된 유저를 활성 상태로 원복합니다 (`deleted = False`).
  - 캐시에 유저 데이터를 다시 재워밍(`Rewarm`)합니다 (`RESTORE_OK`).
- `QUERY_ACTIVE_USERS`: 논리 삭제되지 않은(`deleted == False`) 활성 유저 목록만 사전순으로 반환합니다.
- `QUERY_AUDIT_ORDERS <user_id>`: 유저의 삭제 여부와 무관하게, 과거 모든 주문 수량과 총 결제 금액을 100% 온전하게 집계합니다 (`ORDERS=<cnt>,TOTAL=<total>`).
- `QUERY_CACHE <id>`:
  - 논리 삭제된 유저의 경우 툼스톤으로 이미 캐시에서 축출되었으므로 유령 히트 없이 깨끗한 미스(`CACHE_CLEAN_MISS(TOMBSTONE_EVICTED)`)가 발생합니다.

---

## 입력 형식

```text
ACTIONS
<COMMAND> [args...]
...
```

지원 명령어:
- `INSERT_USER <id> <name>`
- `INSERT_ORDER <order_id> <user_id> <amount>`
- `DELETE_USER <id>`
- `RESTORE_USER <id>`
- `QUERY_ACTIVE_USERS`
- `QUERY_AUDIT_ORDERS <user_id>`
- `QUERY_CACHE <id>`

---

## 출력 형식

각 액션마다 1줄씩 다음 형식으로 출력합니다 (인덱스는 1부터 시작):
```text
ACT <idx> <COMMAND> <target_id> HARD:<hard_status> SOFT:<soft_status>
```

모든 액션 처리가 끝난 후, 최종 요약 3줄을 출력합니다:
```text
SUMMARY HARD REMAINING_ORDERS:<cnt> LOST_ORDERS:<lost> GHOST_CACHE_HITS:<ghost> RESTORE_SUCCESSES:0
SUMMARY SOFT REMAINING_ORDERS:<cnt> LOST_ORDERS:0 GHOST_CACHE_HITS:0 RESTORE_SUCCESSES:<restored>
SUMMARY DATA_RETENTION_RATE HARD:<hard_rate>% SOFT:<soft_rate>%
```

---

## 입출력 예시

### 예시 1: 외래키 CASCADE 연쇄 소각과 유령 캐시 방어

**입력:**
```text
ACTIONS
INSERT_USER user-1 Alice
INSERT_ORDER ord-101 user-1 20000
INSERT_ORDER ord-102 user-1 30000
INSERT_USER user-2 Bob
INSERT_ORDER ord-201 user-2 45000
DELETE_USER user-1
QUERY_ACTIVE_USERS
QUERY_AUDIT_ORDERS user-1
QUERY_CACHE user-1
RESTORE_USER user-1
QUERY_CACHE user-1
QUERY_ACTIVE_USERS
```

**출력:**
```text
ACT 1 INSERT_USER user-1 HARD:OK SOFT:OK
ACT 2 INSERT_ORDER ord-101 HARD:OK SOFT:OK
ACT 3 INSERT_ORDER ord-102 HARD:OK SOFT:OK
ACT 4 INSERT_USER user-2 HARD:OK SOFT:OK
ACT 5 INSERT_ORDER ord-201 HARD:OK SOFT:OK
ACT 6 DELETE_USER user-1 HARD:USER_DELETED_CASCADE(2) SOFT:USER_SOFT_DELETED_TOMBSTONE_SENT
ACT 7 QUERY_ACTIVE_USERS HARD:COUNT=1,USERS=[user-2] SOFT:COUNT=1,USERS=[user-2]
ACT 8 QUERY_AUDIT_ORDERS user-1 HARD:ORDERS=0,TOTAL=0 SOFT:ORDERS=2,TOTAL=50000
ACT 9 QUERY_CACHE user-1 HARD:GHOST_CACHE_HIT(name=Alice) SOFT:CACHE_CLEAN_MISS(TOMBSTONE_EVICTED)
ACT 10 RESTORE_USER user-1 HARD:RESTORE_FAIL_NOT_FOUND SOFT:RESTORE_OK
ACT 11 QUERY_CACHE user-1 HARD:GHOST_CACHE_HIT(name=Alice) SOFT:CACHE_HIT(name=Alice)
ACT 12 QUERY_ACTIVE_USERS HARD:COUNT=1,USERS=[user-2] SOFT:COUNT=2,USERS=[user-1,user-2]
SUMMARY HARD REMAINING_ORDERS:1 LOST_ORDERS:2 GHOST_CACHE_HITS:2 RESTORE_SUCCESSES:0
SUMMARY SOFT REMAINING_ORDERS:3 LOST_ORDERS:0 GHOST_CACHE_HITS:0 RESTORE_SUCCESSES:1
SUMMARY DATA_RETENTION_RATE HARD:33.33% SOFT:100.00%
```

**설명:**
- `user-1`을 삭제했을 때:
  - Hard Delete는 `ord-101`, `ord-102` 주문 2건을 영구 소각(`LOST_ORDERS:2`)했고, 캐시에는 `Alice`가 유령 데이터로 잔류하여 `GHOST_CACHE_HIT`을 일으켰습니다. 또한 복구도 불가능했습니다.
  - Soft Delete는 주문 2건을 온전히 보존(`DATA_RETENTION_RATE: 100.00%`)했고, CDC 툼스톤을 통해 캐시를 안전하게 무효화했으며, 1초 만에 완벽하게 복구되었습니다!
