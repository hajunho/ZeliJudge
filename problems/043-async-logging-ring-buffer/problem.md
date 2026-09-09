# #043 로그를 많이 남겼더니 서버가 멈췄어요?!: 동기식 로깅 vs 비동기 링 버퍼(Disruptor Ring Buffer)

---

## 1. 현실 세계 비유: 고속도로 수동 톨게이트 장부 vs 하이패스 자동 촬영

고속도로 톨게이트를 상상해 보세요.

```text
❌ 수동 톨게이트 (동기식 파일 로깅, Sync Logging):
   자동차가 톨게이트에 도착할 때마다, 직원이 두꺼운 종이 장부(하드디스크 파일)를 꺼내
   펜으로 차량 번호를 적고, 인주를 묻혀 도장을 쾅 찍고, 캐비닛에 철한 뒤에야 비로소 차단기를 올려줍니다.
   평소 차량이 드물 때는 문제가 없지만, 주말 귀성길에 초당 1,000대의 차량이 몰려오면?
   톨게이트 앞 수십 킬로미터까지 차들이 꼼짝없이 멈춰 서서 엔진이 과열되어 도로 전체가 마비됩니다!

✅ 하이패스 & 백그라운드 일꾼 (비동기 링 버퍼, Async Ring Buffer):
   차량이 지나갈 때 고속 카메라가 번호판 사진(로그 이벤트)을 찰칵 찍어서
   고속 원형 컨베이어 벨트(링 버퍼, Ring Buffer)에 툭 던져두고 0.001초 만에 차단기를 열어줍니다.
   차량(HTTP 요청 스레드)은 1ms의 지연도 없이 쌩쌩 통과합니다.
   뒤편 사무실에 있는 백그라운드 전담 일꾼(Worker Thread)이 컨베이어 벨트에서
   사진을 100장씩 묶음(Batch)으로 꺼내어 여유롭게 장부에 기록합니다.
```

수많은 주니어 개발자와 AI 바이브 코더들이 "디버깅을 꼼꼼히 하겠다"며 코드 곳곳에 `logger.info(...)`를 남발합니다.  
그리고 배포 첫날 트래픽이 몰리자마자 **비즈니스 로직은 10ms 만에 끝났는데, 디스크에 로그 파일 쓰느라 스레드가 멈춰서 서버가 폭사**하는 기현상을 겪습니다.  
하드디스크/SSD의 쓰기 속도(I/O Latency)는 CPU 메모리 연산보다 수만~수십만 배 느리기 때문입니다!

---

## 2. 문제 개요

당신은 대규모 결제 시스템의 백엔드 성능 최적화를 맡은 엔지니어입니다.  
초당 수만 건의 로그가 쏟아지는 환경에서, 기존의 **동기식 로거(SYNC_LOGGING)**와 Logback / LMAX Disruptor 스타일의 **비동기 링 버퍼 로거(ASYNC_RING_BUFFER)**를 시뮬레이션하고,  
디스크 I/O 작업 횟수를 얼마나 절감할 수 있는지 정밀 계측하세요.

### 시뮬레이션 모델 상세 규칙

#### 1. 공통 설정
- `BUFFER_CAPACITY <capacity>`: 비동기 링 버퍼의 최대 수용 슬롯 수 ($1 \le capacity \le 10,000$).
- `DISCARD_THRESHOLD_PERCENT <percent>`: 잔여 슬롯 기준 드롭 임계 퍼센트 ($0 \le percent \le 100$).
  - 버퍼의 잔여 여유 공간 $remain = capacity - len(buffer)$.
  - 드롭 한계치 $discard\_limit = \lfloor capacity \times \frac{percent}{100} \rfloor$.
- `BATCH_SIZE <batch_size>`: 백그라운드 워커가 1회 `FLUSH` 시 디스크에 한 번에 쓸 수 있는 최대 로그 수.

#### 2. 동기식 로깅 모델 (SYNC_LOGGING)
- `LOG` 이벤트가 발생할 때마다 메인 스레드가 즉시 디스크 I/O를 1회 실행합니다 (`SYNC:WRITTEN_IMMEDIATE`).
- 동기식 디스크 I/O 발생 횟수(`SYNC_DISK_IO_OPS`)가 `1` 증가합니다.

#### 3. 비동기 링 버퍼 모델 (ASYNC_RING_BUFFER)
메인 스레드는 디스크를 직접 건드리지 않고 메모리 버퍼(큐)에 로그를 밀어 넣습니다.
- **`LOG <timestamp> <level> <message_id>` 처리**:
  - `remain = capacity - len(buffer)` 계산
  - **드롭 임계치 검사**:
    - 만약 $remain \le discard\_limit$ 이고 로그 레벨이 `DEBUG` 또는 `INFO` 라면:
      - 과감히 로그를 폐기합니다: `ASYNC:DROPPED_THRESHOLD`
      - 드롭 카운트 `async_dropped` `1` 증가 (버퍼에 넣지 않음).
  - **버퍼 완전 포화 검사**:
    - 위 조건에 해당하지 않지만 $remain == 0$ 이라면 (즉, 버퍼가 100% 꽉 차서 `WARN`/`ERROR`조차 넣을 자리가 없음):
      - 어쩔 수 없이 로그를 유실합니다: `ASYNC:DROPPED_FULL`
      - 드롭 카운트 `async_dropped` `1` 증가.
  - **정상 버퍼링**:
    - 위 두 경우에 해당하지 않으면 버퍼의 맨 뒤에 인큐(Enqueue)합니다: `ASYNC:BUFFERED`
- **`FLUSH <timestamp>` 처리**:
  - 백그라운드 워커가 버퍼에서 최대 `batch_size`개의 로그를 꺼내 디스크에 단 1번의 배치 쓰기로 기록합니다.
  - 꺼낸 로그 개수 $pop\_count = \min(len(buffer), batch\_size)$.
  - 만약 $pop\_count > 0$ 이라면:
    - 비동기 디스크 I/O 작업 횟수(`ASYNC_DISK_IO_OPS`)가 `1` 증가합니다.
    - 기록된 총 로그 수(`LOGS_WRITTEN`)가 $pop\_count$만큼 증가합니다.
    - 버퍼에서 $pop\_count$개의 로그를 제거합니다.
  - 만약 버퍼가 비어있다면 ($pop\_count == 0$):
    - 디스크 작업 횟수는 증가하지 않습니다.

---

## 3. 입력 형식

```text
BUFFER_CAPACITY <capacity>
DISCARD_THRESHOLD_PERCENT <percent>
BATCH_SIZE <batch_size>
EVENTS <E>
LOG <timestamp> <level> <message_id>
FLUSH <timestamp>
... (총 E개의 줄)
```

- `capacity`: 버퍼 용량 (정수, $1 \le capacity \le 10,000$)
- `percent`: 드롭 임계 퍼센트 (정수, $0 \le percent \le 100$)
- `batch_size`: 배치 플러시 크기 (정수, $1 \le batch\_size \le 1,000$)
- `E`: 총 이벤트 줄 수 ($1 \le E \le 30,000$)
- 각 명령:
  - `LOG <timestamp> <level> <message_id>`: 로그 발생 이벤트
    - `<level>`: `DEBUG`, `INFO`, `WARN`, `ERROR` 중 하나
    - `<message_id>`: 고유 식별자 문자열
  - `FLUSH <timestamp>`: 백그라운드 디스크 배치 플러시 틱

---

## 4. 출력 형식

각 이벤트마다 다음 형식으로 한 줄씩 출력합니다:

- `LOG` 이벤트:
  ```text
  LOG <timestamp> LEVEL:<level> MSG:<message_id> SYNC:WRITTEN_IMMEDIATE ASYNC:<async_status> QUEUE:<current_len>/<capacity>
  ```
  - `<async_status>`: `BUFFERED`, `DROPPED_THRESHOLD`, `DROPPED_FULL`

- `FLUSH` 이벤트:
  ```text
  FLUSH <timestamp> BATCH_WRITTEN:<pop_count> QUEUE:<remaining_len>/<capacity>
  ```

모든 이벤트 처리가 끝난 후, 마지막 줄에 통계 요약을 출력합니다:
```text
SUMMARY TOTAL_LOGS:<total_logs> SYNC_DISK_IO_OPS:<sync_ops> ASYNC_DISK_IO_OPS:<async_ops> LOGS_WRITTEN:<written> LOGS_DROPPED:<dropped> IO_REDUCTION_RATE:<reduction_rate>%
```
- `<reduction_rate>`: 디스크 I/O 작업 횟수 절감율 $\frac{sync\_ops - async\_ops}{sync\_ops} \times 100$ (소수점 첫째 자리까지 반올림 표기, 예: `66.7%`, `0.0%`). 만약 `sync_ops == 0`이면 `0.0%`.

---

## 5. 입출력 예시

### 예시 입력 1
```text
BUFFER_CAPACITY 5
DISCARD_THRESHOLD_PERCENT 40
BATCH_SIZE 3
EVENTS 10
LOG 1001 INFO req_01
LOG 1002 INFO req_02
LOG 1003 DEBUG req_03
LOG 1004 ERROR req_04
LOG 1005 WARN req_05
FLUSH 1010
LOG 1011 DEBUG req_06
LOG 1012 INFO req_07
FLUSH 1020
FLUSH 1030
```

### 예시 출력 1
```text
LOG 1001 LEVEL:INFO MSG:req_01 SYNC:WRITTEN_IMMEDIATE ASYNC:BUFFERED QUEUE:1/5
LOG 1002 LEVEL:INFO MSG:req_02 SYNC:WRITTEN_IMMEDIATE ASYNC:BUFFERED QUEUE:2/5
LOG 1003 LEVEL:DEBUG MSG:req_03 SYNC:WRITTEN_IMMEDIATE ASYNC:DROPPED_THRESHOLD QUEUE:2/5
LOG 1004 LEVEL:ERROR MSG:req_04 SYNC:WRITTEN_IMMEDIATE ASYNC:BUFFERED QUEUE:3/5
LOG 1005 LEVEL:WARN MSG:req_05 SYNC:WRITTEN_IMMEDIATE ASYNC:BUFFERED QUEUE:4/5
FLUSH 1010 BATCH_WRITTEN:3 QUEUE:1/5
LOG 1011 LEVEL:DEBUG MSG:req_06 SYNC:WRITTEN_IMMEDIATE ASYNC:BUFFERED QUEUE:2/5
LOG 1012 LEVEL:INFO MSG:req_07 SYNC:WRITTEN_IMMEDIATE ASYNC:BUFFERED QUEUE:3/5
FLUSH 1020 BATCH_WRITTEN:3 QUEUE:0/5
FLUSH 1030 BATCH_WRITTEN:0 QUEUE:0/5
SUMMARY TOTAL_LOGS:7 SYNC_DISK_IO_OPS:7 ASYNC_DISK_IO_OPS:2 LOGS_WRITTEN:6 LOGS_DROPPED:1 IO_REDUCTION_RATE:71.4%
```

### 설명
- `BUFFER_CAPACITY = 5`, `DISCARD_THRESHOLD_PERCENT = 40` 이므로 $discard\_limit = 5 \times 0.4 = 2$ 입니다. 즉, 남은 슬롯이 2개 이하가 되면 `DEBUG`/`INFO` 로그를 드롭하기 시작합니다.
- **1001 ~ 1002**: `INFO` 2건 인큐 완료 (현재 큐 길이 2, 남은 슬롯 3개).
- **1003**: `DEBUG` 로그 도착. 인큐 전 남은 슬롯이 3개에서 1개 더 들어가면 2개가 되므로 남은 슬롯 $\le 2$ 조건에 걸려 `DROPPED_THRESHOLD`로 폐기됩니다.
- **1004 ~ 1005**: `ERROR`와 `WARN`은 중요한 로그이므로 버퍼가 완전히 찰 때까지 계속 인큐되어 큐 길이가 4가 됩니다.
- **1010**: 백그라운드 워커가 `BATCH_SIZE = 3`만큼 한 번의 디스크 쓰기로 묶어 기록합니다. 큐 길이는 1로 줄어듭니다.
- **최종 요약**:
  - 동기 로거는 7번의 디스크 I/O를 일으켰지만, 비동기 로거는 단 2번의 배치 디스크 쓰기(`ASYNC_DISK_IO_OPS: 2`)로 처리하여 **디스크 I/O 작업을 71.4% 절감**했습니다!
