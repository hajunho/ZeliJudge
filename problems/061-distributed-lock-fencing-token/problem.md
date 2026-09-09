# Problem 061: 분산 락의 덫과 펜싱 토큰 (Distributed Lock STW Pause & Martin Kleppmann's Fencing Token)

## 문제 설명

대규모 분산 이커머스 시스템을 운영 중인 당신의 팀에서 기괴한 버그가 보고되었습니다:
> "분명히 Redis 분산 락을 걸어서 재고를 1개로 제한해 두었는데,  
> 어떻게 두 명의 사용자가 동시에 같은 한정판 아이템을 구매하고 결제 완료된 거죠?!"

로그를 분석한 결과, 원인은 분산 시스템의 고질병인 **Stop-The-World (STW) GC 일시정지**와 **타임아웃(TTL) 만료**였습니다!
1. 서버 A가 락(TTL 1,000ms)을 획득함.
2. 서버 A에 1,200ms 동안 JVM Full GC가 발생하여 프로세스가 멈춤.
3. 그 사이 Redis에서는 1,000ms가 지나 락이 자동 만료됨.
4. 서버 B가 락을 정상 획득하고 DB에 최신 재고(`val="ITEM_B"`)를 씀.
5. 뒤늦게 깨어난 서버 A는 자기가 방금 락을 얻었다고 착각하고 DB에 과거 재고(`val="ITEM_A"`)를 덮어써서 데이터를 파괴함!
6. 심지어 서버 A가 작업을 마치고 `RELEASE`를 호출하자, 서버 B가 쥐고 있던 락까지 무단 삭제해버림!

당신은 분산 시스템 석학 **마틴 클레프만(Martin Kleppmann)**의 논문에 따라, 단조 증가하는 **펜싱 토큰(Fencing Token)** 시스템을 구현하여 이 치명적인 버그를 원천 차단해야 합니다.

동일한 명령 시퀀스에 대해 **Naive 분산 락**과 **Safe 펜싱 토큰 분산 락**을 동시에 시뮬레이션하고, 그 차이를 비교 분석하는 프로그램을 작성하세요.

---

## 시스템 요구사항 및 동작 규칙

### 1. 전역 설정
- `LOCK_TTL_MS <ttl_ms>`: 락의 유효 시간 (밀리초).
- 락 획득 시점 `ts`로부터 `ts + ttl_ms` 시점이 되면 락은 만료됩니다. 즉, 현재 시각 `now >= expires_at` 이면 만료 상태입니다.

### 2. Naive 분산 락 (결함 있는 기존 모델)
- **LOCK**:
  - 만약 락이 만료되었거나 비어있으면 락 획득 성공 (`LOCK_ACQUIRED`), 클라이언트의 로컬 락 보유 플래그 `has_lock = True`.
  - 이미 다른 클라이언트(또는 유효한 락)가 잡고 있으면 실패 (`LOCK_BUSY`).
- **WRITE**:
  - 클라이언트가 로컬 락을 보유하지 않은 경우 (`has_lock == False`): `WRITE_FAIL_NO_LOCK`.
  - 클라이언트가 로컬 락을 보유한 경우: 스토리지에 무조건 값을 씁니다 (`storage_val = val`).
    - 이때 실제 락 서버 상태가 유효하고 소유자가 본인이면: `WRITE_OK`.
    - 만약 락이 만료되었거나 다른 사람에게 넘어갔는데 쓴 것이라면: `WRITE_CORRUPTED` (오염 쓰기 카운트 +1).
- **RELEASE**:
  - 클라이언트의 `has_lock == False`인 경우: `RELEASE_FAIL_NO_LOCK`.
  - 클라이언트의 `has_lock == True`인 경우: `has_lock = False`로 변경하고 락 서버에 무조건 삭제 명령을 보냅니다.
    - 락이 이미 만료되어 비어있으면: `RELEASE_FAIL_NO_LOCK`.
    - 현재 락 소유자가 본인이면: 정상 해제 `RELEASE_OK`, 락 반환.
    - 현재 락 소유자가 **다른 클라이언트**라면: **남의 락을 날려버림!** (`RELEASE_OK_HIJACKED`, 하이재킹 카운트 +1, 락은 빈 상태가 됨).

### 3. Safe 분산 락 (마틴 클레프만의 펜싱 토큰 모델)
- **전역 토큰 카운터**: 시스템 시작 시 `global_token = 0`.
- **스토리지 펜싱**: 지금까지 관측된 최고 토큰 `highest_token_seen = 0`.
- **LOCK**:
  - 만약 락이 만료되었거나 비어있으면:
    - `global_token += 1`
    - 발급된 토큰 `current_token = global_token`
    - 락 획득 성공 (`LOCK_ACQUIRED(token=<current_token>)`), 클라이언트의 `has_lock = True`, 클라이언트에게 토큰 전달.
  - 이미 누군가 유효한 락을 쥐고 있으면 실패 (`LOCK_BUSY`).
- **WRITE**:
  - 클라이언트의 `has_lock == False`인 경우: `WRITE_FAIL_NO_LOCK`.
  - 클라이언트의 `has_lock == True`인 경우: 스토리지에 `(token, val)` 전송.
    - 만약 `token > highest_token_seen` 이면:
      - 정상 수락! `highest_token_seen = token`, `storage_val = val`
      - 상태: `WRITE_OK(token=<token>)`.
    - 만약 `token <= highest_token_seen` 이면:
      - **오래된 유령 토큰 차단!** (스토리지 오염 방지 카운트 +1, 스토리지 값은 변경되지 않음)
      - 상태: `WRITE_REJECTED_STALE(token=<token>,highest=<highest_token_seen>)`.
- **RELEASE**:
  - 클라이언트의 `has_lock == False`인 경우: `RELEASE_FAIL_NO_LOCK`.
  - 클라이언트의 `has_lock == True`인 경우: `has_lock = False`로 변경하고 `(client_id, token)`과 함께 해제 요청.
    - 락이 이미 만료되어 비어있으면: `RELEASE_IGNORED_EXPIRED(token=<token>)`.
    - 현재 락 소유자가 본인이고 발급된 토큰과 일치하면: 정상 해제 `RELEASE_OK(token=<token>)`, 락 반환.
    - 현재 락을 **다른 클라이언트가 쥐고 있거나 토큰이 불일치**하면:
      - **남의 락 보존!** (무단 해제 차단 카운트 +1, 현재 락은 안전하게 유지됨)
      - 상태: `RELEASE_REJECTED_STALE(token=<token>,holder=<current_holder>)`.

---

## 입력 형식

```text
LOCK_TTL_MS <ttl_ms>
ACTIONS
<COMMAND> <client_id> [value] <timestamp>
...
```

- 첫 번째 줄: `LOCK_TTL_MS <ttl_ms>` (락 유효 시간, 1 이상 정수)
- 두 번째 줄: `ACTIONS`
- 이후 줄들: 다음 세 가지 명령 중 하나 (타임스탬프는 밀리초 단위 정수, 단조 증가 순서):
  1. `LOCK <client_id> <timestamp>`
  2. `WRITE <client_id> <value> <timestamp>`
  3. `RELEASE <client_id> <timestamp>`

---

## 출력 형식

각 액션마다 1줄씩 다음 형식으로 출력합니다 (인덱스는 1부터 시작):
```text
ACT <idx> <COMMAND> <client_id> NAIVE:<naive_status> SAFE:<safe_status>
```

모든 액션 처리가 끝난 후, 최종 요약 3줄을 출력합니다:
```text
SUMMARY NAIVE FINAL_VAL:<val> CORRUPTED_WRITES:<cnt> HIJACKED_RELEASES:<cnt>
SUMMARY SAFE FINAL_VAL:<val> STALE_WRITES_REJECTED:<cnt> STALE_RELEASES_REJECTED:<cnt>
SUMMARY ANOMALIES_PREVENTED:<cnt>
```
- 만약 스토리지가 한 번도 쓰이지 않았다면 `FINAL_VAL:NONE` 입니다.
- `ANOMALIES_PREVENTED`는 차단된 구버전 쓰기 횟수와 무단 해제 차단 횟수의 합입니다.

---

## 입출력 예시

### 예시 1: 마틴 클레프만의 고전적 딜레마 (STW Pause와 쓰기 오염 방어)

**입력:**
```text
LOCK_TTL_MS 1000
ACTIONS
LOCK client-A 100
LOCK client-B 1200
WRITE client-B DATA_B 1250
RELEASE client-B 1300
WRITE client-A DATA_A 1400
RELEASE client-A 1450
```

**출력:**
```text
ACT 1 LOCK client-A NAIVE:LOCK_ACQUIRED SAFE:LOCK_ACQUIRED(token=1)
ACT 2 LOCK client-B NAIVE:LOCK_ACQUIRED SAFE:LOCK_ACQUIRED(token=2)
ACT 3 WRITE client-B NAIVE:WRITE_OK SAFE:WRITE_OK(token=2)
ACT 4 RELEASE client-B NAIVE:RELEASE_OK SAFE:RELEASE_OK(token=2)
ACT 5 WRITE client-A NAIVE:WRITE_CORRUPTED SAFE:WRITE_REJECTED_STALE(token=1,highest=2)
ACT 6 RELEASE client-A NAIVE:RELEASE_FAIL_NO_LOCK SAFE:RELEASE_IGNORED_EXPIRED(token=1)
SUMMARY NAIVE FINAL_VAL:DATA_A CORRUPTED_WRITES:1 HIJACKED_RELEASES:0
SUMMARY SAFE FINAL_VAL:DATA_B STALE_WRITES_REJECTED:1 STALE_RELEASES_REJECTED:0
SUMMARY ANOMALIES_PREVENTED:1
```

**설명:**
- `client-A`가 100ms에 락을 얻었으나 1,200ms 동안 멈췄습니다. (만료 시각은 1,100ms)
- 1,200ms에 `client-B`가 새 락(token=2)을 얻고 `DATA_B`를 쓴 뒤 1,300ms에 정상 해제했습니다.
- 1,400ms에 깨어난 `client-A`가 과거의 데이터 `DATA_A`를 쓰려 할 때:
  - Naive는 그대로 덮어써서 `FINAL_VAL:DATA_A`로 DB가 오염되었습니다.
  - Safe는 `token=1 <= highest=2`를 감지하고 `WRITE_REJECTED_STALE`로 차단하여 `FINAL_VAL:DATA_B`를 안전하게 보존했습니다!
