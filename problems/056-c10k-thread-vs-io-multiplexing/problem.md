# #056 동시 접속자 1만 명이 들어왔더니 서버가 숨도 못 쉬어요?!: C10K 문제와 Thread-per-Client vs I/O Multiplexing (Epoll / Reactor)

---

## 1. 현실 세계 비유: 손님 1명당 전담 웨이터 1명 vs 무전기 찬 총괄 매니저 1명

손님 1,000명이 동시에 찾는 초대형 패밀리 레스토랑을 상상해 보세요.

```text
❌ 전통적인 스레드 할당 모델 (손님 1명당 웨이터 1명 고용하기):
   식당 주인이 "손님이 1명 올 때마다 전담 웨이터 1명을 뽑아 테이블 옆에 세워두자!"고 결정했습니다.
   하지만 손님들은 30분 동안 메뉴판만 보며 잡담을 나눕니다 (네트워크 I/O 대기).
   웨이터 1,000명은 손님 옆에서 아무 일도 안 하고 멀뚱멀뚱 서서 월급(스레드 1MB 스택 메모리)을 축냅니다.
   1,000명의 웨이터가 좁은 주방 통로를 뛰어다니며 서로 부딪히고 길을 비켜주느라
   정작 주문은 하나도 처리 못 하고 탈진합니다 (컨텍스트 스위칭 오버헤드 & 메모리 OOM 파산!).

✅ I/O 다중화 & Reactor 패턴 (무전기 찬 총괄 매니저 1명):
   식당 주인이 웨이터 1,000명을 전부 해고하고, 모든 테이블에 '호출 벨(Socket FD)'을 설치했습니다.
   총괄 매니저(단일 이벤트 루프 스레드)는 카운터에 앉아있다가,
   어떤 손님이 벨을 띵동!(I/O Ready 이벤트) 누를 때만 번개같이 달려가 0.1초 만에 주문을 받아옵니다.
   매니저 단 1명이 10,000개의 테이블을 완벽하게 서빙하며, 식당 메모리는 40MB도 채 쓰지 않습니다!
```

1999년 댄 케겔(Dan Kegel)이 제기한 **C10K 문제 (동시 접속자 10,000개 처리의 한계)**는  
컴퓨터 과학과 분산 시스템 역사상 가장 거대한 패러다임의 전환을 불러온 사건입니다.

전통적인 **Apache 웹 서버나 초기 톰캣(Tomcat)의 블로킹 스레드 모델(Thread-per-Connection)**이  
왜 동시 접속자 수천 명 수준에서 메모리 고갈(OOM)과 CPU 포화로 쓰러지는지,  
그리고 **Nginx, Node.js, Netty, Redis가 채택한 리눅스 epoll 기반 I/O Multiplexing (Reactor 패턴)**이  
어떻게 적은 자원으로 수십만 개의 연결을 동시 처리하는지 시뮬레이션을 통해 체득해 봅시다.

---

## 2. 문제 개요

당신은 초대형 실시간 채팅 및 알림 푸시 게이트웨이의 시스템 소프트웨어 엔지니어입니다.  
수천~수만 대의 클라이언트가 동시 접속하여 유휴(Idle) 상태로 연결을 유지하는 환경에서,  
기존의 **클라이언트당 스레드 할당 모델(THREAD_PER_CONN)**과  
**논블로킹 epoll 기반 I/O 다중화 모델(IO_MULTIPLEXING)**을 시뮬레이션하고,  
피크 메모리 절감률(`MEMORY_SAVINGS`)과 연결 수용률 우위(`CONNECTION_CAPACITY_ADVANTAGE`)를 정밀 계측하세요.

### 시뮬레이션 상세 규칙

#### 1. 인프라 파라미터
- `MAX_SERVER_MEMORY_MB <max_mem_mb>`: 서버에 할당된 최대 가용 메모리 (MB, $1 \le max\_mem\_mb \le 100,000$).
- `THREAD_STACK_KB <stack_kb>`: 스레드 1개 생성 시 소비되는 OS 스레드 스택 메모리 (KB, $64 \le stack\_kb \le 8,192$, 통상 1,024KB = 1MB).
- `FD_BUFFER_KB <fd_kb>`: epoll 소켓 FD 1개당 소비되는 커널 버퍼/제어 블록 메모리 (KB, $1 \le fd\_kb \le 64$, 통상 8KB).
- `MAX_ACTIVE_THREADS <max_threads>`: OS가 허용하는 최대 동시 활성 스레드 한계 ($1 \le max\_threads \le 10,000$).

#### 2. 모델 A: 클라이언트당 스레드 할당 (THREAD_PER_CONN)
- 연결된 각 활성 클라이언트(`active_clients`)마다 정확히 1개의 OS 스레드가 배정됩니다.
- 현재 사용 중인 총 메모리(KB):
  $$mem_{thread} = \text{len}(active\_clients) \times THREAD\_STACK\_KB$$
- `CONNECT <client_id> <t>`:
  - 만약 현재 활성 스레드 수가 `MAX_ACTIVE_THREADS`에 도달했거나,  
    새 스레드를 추가할 경우 총 메모리가 `MAX_SERVER_MEMORY_MB`를 초과한다면:
    - $\to$ `REJECTED` (스레드 고갈 또는 OOM).
  - 여유가 있다면:
    - $\to$ `SUCCESS`. 해당 클라이언트의 스레드 할당.
- `DATA <client_id> <bytes> <t>`:
  - 해당 클라이언트가 활성 연결 상태라면 $\to$ `PROCESSED`.
  - 연결이 거부되었거나 없으면 $\to$ `DROPPED`.
- `DISCONNECT <client_id> <t>`:
  - 연결 해제 및 스레드 스택 메모리 즉시 반환 $\to$ `DISCONNECTED`.

#### 3. 모델 B: 논블로킹 I/O 다중화 (IO_MULTIPLEXING / epoll)
- Nginx/Netty/Node.js처럼 **고정된 4개의 작업자 스레드(Worker Threads)**만 유지하며,  
  수만 개의 소켓을 OS 커널 `epoll` 이벤트 루프에 등록하여 논블로킹으로 다중화합니다.
- 현재 사용 중인 총 메모리(KB):
  $$mem_{epoll} = (4 \times THREAD\_STACK\_KB) + (\text{len}(active\_sockets) \times FD\_BUFFER\_KB)$$
- `CONNECT <client_id> <t>`:
  - 새 소켓 FD를 추가할 경우 총 메모리가 `MAX_SERVER_MEMORY_MB`를 초과한다면:
    - $\to$ `REJECTED` (메모리 고갈).
  - 초과하지 않는다면:
    - $\to$ `SUCCESS`. epoll 관심 목록에 소켓 등록. (스레드 개수 한계의 영향을 받지 않음!)
- `DATA <client_id> <bytes> <t>`:
  - 소켓이 연결 상태라면 $\to$ `PROCESSED`. 없으면 $\to$ `DROPPED`.
- `DISCONNECT <client_id> <t>`:
  - epoll 목록에서 소켓 제거 및 메모리 반환 $\to$ `DISCONNECTED`.

---

## 3. 입력 형식

```text
MAX_SERVER_MEMORY_MB <max_mem_mb>
THREAD_STACK_KB <stack_kb>
FD_BUFFER_KB <fd_kb>
MAX_ACTIVE_THREADS <max_threads>
EVENTS <E>
... (총 E개의 이벤트 줄)
```

이벤트 줄의 종류:
1. `CONNECT <client_id> <timestamp>`
2. `DATA <client_id> <bytes> <timestamp>`
3. `DISCONNECT <client_id> <timestamp>`

- 동일한 `timestamp`에 여러 이벤트가 발생할 경우, 다음 순서로 처리됩니다:
  1. `DISCONNECT` (연결 해제 및 자원 반환 우선)
  2. `DATA` (데이터 송수신 처리)
  3. `CONNECT` (신규 연결 수립)

---

## 4. 출력 형식

각 이벤트마다 한 줄씩 두 모델의 처리 상태를 출력합니다:
- `CONNECT`:
  ```text
  CONNECT <client_id> THREAD:<status>,MEM:<mem>MB EPOLL:<status>,MEM:<mem>MB
  ```
- `DATA`:
  ```text
  DATA <client_id> THREAD:<PROCESSED|DROPPED> EPOLL:<PROCESSED|DROPPED>
  ```
- `DISCONNECT`:
  ```text
  DISCONNECT <client_id> THREAD:DISCONNECTED EPOLL:DISCONNECTED
  ```

모든 이벤트 종료 후 최종 종합 통계를 출력합니다:
```text
SUMMARY TOTAL_CONNECTS:<total_conn>
THREAD MODEL ACCEPTED:<t_acc> REJECTED:<t_rej> PEAK_MEM:<t_peak>MB
EPOLL MODEL ACCEPTED:<e_acc> REJECTED:<e_rej> PEAK_MEM:<e_peak>MB
SUMMARY MEMORY_SAVINGS:<mem_saved>% CONNECTION_CAPACITY_ADVANTAGE:<adv>%
```

- `PEAK_MEM`: 시뮬레이션 중 기록된 최대 메모리 소모량 (MB, 소수점 둘째 자리)
- `MEMORY_SAVINGS`: `((t_peak - e_peak) / t_peak) * 100.0` (소수점 둘째 자리까지 반올림, 예: `95.50%`)
- `CONNECTION_CAPACITY_ADVANTAGE`: `((e_acc - t_acc) / total_conn) * 100.0` (소수점 둘째 자리까지 반올림, 예: `25.00%`)

---

## 5. 입출력 예시

### 입력
```text
MAX_SERVER_MEMORY_MB 10
THREAD_STACK_KB 1024
FD_BUFFER_KB 8
MAX_ACTIVE_THREADS 3
EVENTS 8
CONNECT C1 10
CONNECT C2 11
CONNECT C3 12
CONNECT C4 13
DATA C4 100 14
DISCONNECT C1 15
CONNECT C5 16
DATA C5 200 17
```

### 출력
```text
CONNECT C1 THREAD:SUCCESS,MEM:1.00MB EPOLL:SUCCESS,MEM:4.01MB
CONNECT C2 THREAD:SUCCESS,MEM:2.00MB EPOLL:SUCCESS,MEM:4.02MB
CONNECT C3 THREAD:SUCCESS,MEM:3.00MB EPOLL:SUCCESS,MEM:4.02MB
CONNECT C4 THREAD:REJECTED,MEM:3.00MB EPOLL:SUCCESS,MEM:4.03MB
DATA C4 THREAD:DROPPED EPOLL:PROCESSED
DISCONNECT C1 THREAD:DISCONNECTED EPOLL:DISCONNECTED
CONNECT C5 THREAD:SUCCESS,MEM:3.00MB EPOLL:SUCCESS,MEM:4.03MB
DATA C5 THREAD:PROCESSED EPOLL:PROCESSED
SUMMARY TOTAL_CONNECTS:5
THREAD MODEL ACCEPTED:4 REJECTED:1 PEAK_MEM:3.00MB
EPOLL MODEL ACCEPTED:5 REJECTED:0 PEAK_MEM:4.03MB
SUMMARY MEMORY_SAVINGS:-34.38% CONNECTION_CAPACITY_ADVANTAGE:20.00%
```

#### 해설
- `MAX_ACTIVE_THREADS = 3` 설정으로 인해, C1, C2, C3이 연결된 상태에서 C4가 접속하려 할 때:
  - **THREAD 모델**: 스레드 한계(3개)에 걸려 `REJECTED` 처리되고, 뒤이어 전송한 데이터도 `DROPPED`됩니다.
  - **EPOLL 모델**: 스레드를 늘리지 않고 8KB 소켓 FD만 epoll에 등록하므로 C4를 정상 수용(`SUCCESS`)하고 데이터도 정상 처리합니다.
- C1이 연결을 끊자(`DISCONNECT`), 비로소 THREAD 모델의 슬롯이 1개 비어 C5를 수용할 수 있게 됩니다.
- EPOLL 모델은 스레드 한계와 무관하게 100% 연결 수용률(+20.00% 우위)을 달성했습니다.
