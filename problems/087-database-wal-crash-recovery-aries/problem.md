# Problem #087: 전원이 갑자기 꺼졌는데 결제 내역이 왜 살아있죠?!: 데이터베이스 Write-Ahead Logging (WAL)과 ARIES 장애 복구

## 1. 문제 설명
글로벌 핀테크 결제 플랫폼의 데이터베이스 엔지니어인 당신은 데이터센터 전원 공급 장치에 벼락이 떨어져 DB 서버가 불시에 강제 셧다운(`CRASH`)되는 사고를 겪었습니다.

관계형 데이터베이스(MySQL InnoDB, PostgreSQL, SQLite)는 초당 수만 건의 결제를 고속으로 처리하기 위해 데이터 변경사항을 디스크에 즉시 쓰지 않고 메모리(Buffer Pool)에만 반영하는 `No-Force` 정책을 사용합니다.  
그럼에도 불구하고 정전 발생 시 단 1건의 커밋된 데이터도 유실되지 않고, 미완료된 불완전 트랜잭션은 안전하게 취소될 수 있는 비결은 **순차 로그 우선 기록(WAL, Write-Ahead Logging)** 과 교과서적인 **ARIES 3단계 장애 복구 알고리즘** 덕분입니다.

당신은 WAL 레코드와 체크포인트를 추적하고, 크래시 발생 시 **Analysis $\to$ Redo $\to$ Undo**의 3단계 ARIES 복구 엔진을 정밀하게 시뮬레이션하는 시스템을 구축해야 합니다.

---

## 2. 시스템 동작 규칙

### (1) 데이터 모델 및 WAL 구조
- 데이터베이스는 영구 디스크(Disk)와 고속 메모리(Buffer Pool)를 가집니다.
- `INITIAL_DATA`를 통해 초기 디스크 상태가 주어집니다 (`A:100 B:200 ...`).
- 모든 트랜잭션의 변경사항은 디스크에 플러시되기 전에 **WAL(Write-Ahead Log)** 에 단조 증가하는 일련번호(`LSN: 1, 2, 3, ...`)와 함께 선행 기록됩니다.

---

### (2) 액션 명세

1. `START <tx_id>`:
   - 트랜잭션이 시작됩니다.
   - 활성 트랜잭션 목록에 추가되고 WAL에 기록됩니다:
     `ACT <idx> LSN:<lsn> START <tx_id>`

2. `UPDATE <tx_id> <key> <new_val>`:
   - `<key>`의 현재 값(버퍼 풀 우선, 없으면 디스크)을 `old_val`로 확인합니다. 만약 키가 존재하지 않았다면 `NONE`입니다.
   - 버퍼 풀에 `<key> = <new_val>`을 반영합니다.
   - WAL에 기록됩니다:
     `ACT <idx> LSN:<lsn> UPDATE <tx_id> KEY:<key> OLD:<old_val> NEW:<new_val>`

3. `COMMIT <tx_id>`:
   - 트랜잭션이 성공적으로 커밋됩니다.
   - 활성 목록에서 제거되고 커밋 완료 상태가 됩니다.
   - WAL에 커밋 레코드가 기록됩니다:
     `ACT <idx> LSN:<lsn> COMMIT <tx_id>`

4. `ABORT <tx_id>`:
   - 트랜잭션이 명시적으로 롤백(취소)됩니다.
   - 해당 트랜잭션이 수행한 모든 `UPDATE`를 역순으로 되돌립니다(`old_val`로 복원, `NONE`이면 키 삭제).
   - 활성 목록에서 제거되고 WAL에 기록됩니다:
     `ACT <idx> LSN:<lsn> ABORT <tx_id>`

5. `CHECKPOINT`:
   - 버퍼 풀의 모든 변경사항을 디스크로 일괄 동기화(Flush)합니다.
   - 현재 시점의 활성 트랜잭션 목록(`ACTIVE_TXS`)을 알파벳 오름차순으로 WAL에 기록합니다:
     `ACT <idx> LSN:<lsn> CHECKPOINT ACTIVE_TXS:[<tx1>,<tx2>...]`

6. `CRASH`:
   - 서버 전원이 차단되는 불시의 크래시가 발생합니다.
   - **휘발성 메모리(Buffer Pool)의 모든 데이터가 완전히 증발**합니다.
   - 디스크에는 마지막 동기화(체크포인트 또는 초기 상태) 시점의 내용만 남아있으며, WAL 파일은 영구 디스크에 온전히 보존됩니다.
   - 출력:
     `ACT <idx> CRASH VOLATILE_RAM_LOST`

7. `RECOVER`:
   - 시스템 재부팅 후 **ARIES 3단계 복구 프로세스**를 수행합니다:
   - **Phase 1: 분석 (Analysis Phase)**
     - 가장 최근의 `CHECKPOINT` 레코드를 찾습니다 (체크포인트가 없다면 `NONE`).
     - 복구 시작점 당시 활성 상태였던 트랜잭션 목록으로 시작하여, WAL 끝까지 순방향 스캔합니다.
     - 스캔 도중 `COMMIT`된 트랜잭션은 **`WINNERS`**, 끝내 커밋되지 못한 채 남아있는 트랜잭션은 **`LOSERS`** 로 분류합니다 (각각 알파벳 오름차순 정렬).
     - 출력:
       `  PHASE_1_ANALYSIS LAST_CP_LSN:<lsn_or_NONE> WINNERS:[<w1>,<w2>...] LOSERS:[<l1>,<l2>...]`
   - **Phase 2: 리두 (Redo Phase - "Repeating History")**
     - 가장 최근 체크포인트 이후(체크포인트가 없으면 LSN 1부터)의 모든 `UPDATE` 로그 레코드를 순방향으로 재생합니다.
     - Winner/Loser를 가리지 않고 크래시 직전 상태를 그대로 재현하기 위해 `new_val`을 데이터베이스에 반영합니다.
     - 각 반영 시마다 한 줄씩 출력합니다:
       `  PHASE_2_REDO LSN:<lsn> TX:<tx_id> KEY:<key> VAL:<new_val>`
       (만약 재생할 UPDATE가 없다면 `  PHASE_2_REDO NONE` 한 줄 출력)
   - **Phase 3: 언두 (Undo Phase - "Rolling Back Losers")**
     - WAL의 끝에서부터 가장 최근 체크포인트(없으면 LSN 1)까지 **역방향(Backward)** 으로 스캔합니다.
     - **오직 `LOSERS`에 속한 트랜잭션의 `UPDATE` 레코드만** 찾아서 원래 값(`old_val`)으로 롤백합니다 (`old_val`이 `NONE`이면 해당 키 제거).
     - 각 롤백 시마다 한 줄씩 출력합니다:
       `  PHASE_3_UNDO LSN:<lsn> TX:<tx_id> KEY:<key> RESTORED:<old_val>`
       (만약 취소할 작업이 없다면 `  PHASE_3_UNDO NONE` 한 줄 출력)
   - **복구 완료 (Complete)**:
     - 복구가 완료된 최종 데이터베이스 상태를 키 이름 알파벳 오름차순으로 출력합니다:
       `  RECOVERY_COMPLETE FINAL_STATE:[<k1>=<v1>,<k2>=<v2>...]`
     - 복구된 데이터는 버퍼 풀 및 디스크에 정상 동기화됩니다.

---

## 3. 입력 형식

```text
SYSTEM_CONFIG
INITIAL_DATA <KEY_1>:<VAL_1> <KEY_2>:<VAL_2> ...
ACTIONS
<ACTION_1>
<ACTION_2>
...
```

- `INITIAL_DATA`: 공백으로 구분된 초기 키-값 쌍 (정수 값). 지정되지 않으면 빈 상태로 시작합니다.
- `ACTIONS` 아래 한 줄에 하나씩 액션이 주어집니다.

---

## 4. 출력 형식

각 액션마다 `ACT <act_idx> ...` 형태로 결과를 출력합니다 (`RECOVER`의 경우 하위 4개 단계가 2칸 들여쓰기로 출력됩니다).  
모든 액션 실행 후 `SUMMARY`를 출력합니다:

```text
SUMMARY TOTAL_ACTIONS:<cnt>
SUMMARY TOTAL_WAL_RECORDS:<lsn_cnt>
SUMMARY CRASH_COUNT:<cnt>
SUMMARY TOTAL_REDO_OPS:<cnt>
SUMMARY TOTAL_UNDO_OPS:<cnt>
SUMMARY FINAL_DATABASE_STATE:[<k1>=<v1>,<k2>=<v2>...]
```

- `FINAL_DATABASE_STATE`: 현재 데이터베이스의 모든 키-값 쌍을 키 기준 알파벳 오름차순으로 출력 (예: `[A=150,B=250,C=300]`, 비어있으면 `[]`).

---

## 5. 입출력 예시

### 예시 입력 1
```text
SYSTEM_CONFIG
INITIAL_DATA A:100 B:200 C:300
ACTIONS
START TX1
UPDATE TX1 A 150
COMMIT TX1
CHECKPOINT
START TX2
UPDATE TX2 B 250
START TX3
UPDATE TX3 C 350
COMMIT TX2
UPDATE TX3 C 400
CRASH
RECOVER
```

### 예시 출력 1
```text
ACT 1 LSN:1 START TX1
ACT 2 LSN:2 UPDATE TX1 KEY:A OLD:100 NEW:150
ACT 3 LSN:3 COMMIT TX1
ACT 4 LSN:4 CHECKPOINT ACTIVE_TXS:[]
ACT 5 LSN:5 START TX2
ACT 6 LSN:6 UPDATE TX2 KEY:B OLD:200 NEW:250
ACT 7 LSN:7 START TX3
ACT 8 LSN:8 UPDATE TX3 KEY:C OLD:300 NEW:350
ACT 9 LSN:9 COMMIT TX2
ACT 10 LSN:10 UPDATE TX3 KEY:C OLD:350 NEW:400
ACT 11 CRASH VOLATILE_RAM_LOST
ACT 12 RECOVER
  PHASE_1_ANALYSIS LAST_CP_LSN:4 WINNERS:[TX2] LOSERS:[TX3]
  PHASE_2_REDO LSN:6 TX:TX2 KEY:B VAL:250
  PHASE_2_REDO LSN:8 TX:TX3 KEY:C VAL:350
  PHASE_2_REDO LSN:10 TX:TX3 KEY:C VAL:400
  PHASE_3_UNDO LSN:10 TX:TX3 KEY:C RESTORED:350
  PHASE_3_UNDO LSN:8 TX:TX3 KEY:C RESTORED:300
  RECOVERY_COMPLETE FINAL_STATE:[A=150,B=250,C=300]
SUMMARY TOTAL_ACTIONS:12
SUMMARY TOTAL_WAL_RECORDS:10
SUMMARY CRASH_COUNT:1
SUMMARY TOTAL_REDO_OPS:3
SUMMARY TOTAL_UNDO_OPS:2
SUMMARY FINAL_DATABASE_STATE:[A=150,B=250,C=300]
```
