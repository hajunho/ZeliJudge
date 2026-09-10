# 문제 306: 리눅스 커널 epoll(fs/eventpoll.c) 핵심 아키텍처: LT vs ET, EPOLLEXCLUSIVE 및 이벤트 폴링 엔진 (Linux Kernel epoll Core Architecture Engine)

## 문제 배경
전통적인 유닉스 시스템 콜인 `select()`와 `poll()`은 감시 대상 파일 디스크립터(FD)의 수가 $N$개일 때, 이벤트가 발생할 때마다 전체 $N$개의 FD 배열을 유저 공간에서 커널 공간으로 복사하고 $O(N)$으로 전수 순회해야 하는 치명적인 한계를 가졌습니다. 이로 인해 동시 접속자 수가 수만 명을 넘어서는 이른바 **C10K 문제(Concurrently 10,000 connections)**를 해결할 수 없었습니다.

리눅스 커널 2.6은 이를 근본적으로 극복하기 위해 **`epoll` 서브시스템(`fs/eventpoll.c`)**을 도입했습니다. `epoll`은 다음과 같은 3대 혁신적 자료구조 설계를 통해 이벤트 폴링 비용을 $O(1)$로 단축했습니다:
1. **레드-블랙 트리 (`struct rb_root rbr`)**: 감시 대상 파일 디스크립터(`epitem`)를 $O(\log N)$에 추가, 수정, 삭제.
2. **준비 큐 이중 연결 리스트 (`struct list_head rdllist`)**: 디바이스 드라이버 및 소켓 계층에서 이벤트가 발생(`wake_up` 콜백)할 때만 해당 FD를 준비 리스트에 $O(1)$로 삽입. `epoll_wait()`는 오직 이 `rdllist`만 순회하여 유저 공간으로 반환!
3. **폴링 테이블 대기 큐 콜백 (`ep_poll_callback`)**: 소켓의 수신 버퍼에 패킷이 들어오는 즉시 하드웨어 인터럽트 컨텍스트에서 안전하게 `epitem`을 `rdllist`로 전이.

그러나 실무에서 NGINX, Redis, Netty, Envoy, Tokio와 같은 고성능 네트워크 엔진을 설계할 때 가장 핵심적인 난제는 다음과 같습니다:
- **레벨 트리거(Level-Triggered, LT)** vs **에지 트리거(Edge-Triggered, ET)** 동작의 미묘한 차이.
- **썬더링 허드(Thundering Herd)**: 멀티 워커 프로세스가 단일 수신 대기 소켓을 공유할 때, 연결 하나가 들어왔다고 모든 프로세스가 일제히 깨어나 CPU가 낭비되는 참사 방지 (`EPOLLEXCLUSIVE`).
- **멀티스레드 레이스 컨디션 방지 (`EPOLLONESHOT`)**.
- **중첩 epoll FD 간의 순환 참조 방지 (`ep_loop_check` -> `ELOOP`)**.

본 문제에서는 리눅스 커널 `fs/eventpoll.c`의 핵심 이벤트 디스패칭 및 상태 전이 로직을 정밀하게 시뮬레이션하는 커널 레벨 epoll 엔진을 구현해야 합니다.

---

## 시스템 동작 규칙 및 엔진 명세

### 1. epoll 인스턴스 및 FD 상태 관리
- 각 epoll 인스턴스는 고유한 `epfd`를 가지며, 내부적으로 감시 대상 트리를 구성하는 `rbr`(Red-Black Tree)과 준비 큐 `rdllist`를 유지합니다.
- 파일 디스크립터는 `unread_bytes`(읽지 않은 수신 버퍼 크기), `writable`(송신 가능 여부), `hup`(연결 단절 여부) 상태를 가집니다.

### 2. 제어 연산 (Control Operations)
1. **`EPOLL_CREATE`**: 새로운 epoll 인스턴스를 생성합니다.
2. **`EPOLL_CTL_ADD`**:
   - `target_fd`를 `epfd`의 감시 목록에 등록합니다.
   - **중첩 루프 검사 (`ep_loop_check`)**: 만약 `target_fd`가 다른 epoll 인스턴스이고, 이를 추가함으로써 epoll 간의 순환 의존성(Cycle)이 발생한다면 에러 `"ELOOP"`를 기록하고 등록을 거부합니다.
   - 등록 시점에 이미 조건이 만족되어 있다면(예: `unread_bytes > 0`), 즉시 `rdllist`에 삽입합니다.
3. **`EPOLL_CTL_MOD`**: 감시 이벤트 플래그를 수정하고, `EPOLLONESHOT`으로 비활성화되었던 항목을 다시 활성화(Re-arm)합니다.
4. **`EPOLL_CTL_DEL`**: `target_fd`를 감시 목록과 `rdllist`에서 완전히 제거합니다.

### 3. 이벤트 감지 및 트리거 (LT vs ET vs EPOLLEXCLUSIVE)
데이터 도착(`FD_DATA_ARRIVE`), 데이터 소비(`FD_DATA_READ`), 송신 가능 상태 전이(`FD_WRITABLE_CHANGE`), 연결 단절(`FD_HUP`)이 발생하면:
1. **레벨 트리거 (LT, 기본값)**:
   - 조건이 만족하는 동안(예: `unread_bytes > 0` 또는 `writable == True`), 해당 FD는 계속해서 준비 상태로 간주됩니다.
   - 부분 읽기(`FD_DATA_READ`) 후에도 버퍼에 데이터가 남아 있다면, 다음 `epoll_wait`에서도 계속해서 이벤트가 반환됩니다.
2. **에지 트리거 (ET, `EPOLLET`)**:
   - 오직 **상태의 에지 변화(Edge Transition)**가 발생한 순간에만 `rdllist`에 삽입됩니다!
   - `FD_DATA_ARRIVE`로 새로운 데이터가 들어왔을 때만 트리거됩니다.
   - 데이터를 일부만 읽고(`FD_DATA_READ`) 아직 버퍼에 데이터가 남아 있더라도, 새로운 에지 이벤트가 발생하기 전까지는 **절대 재트리거되지 않습니다!** (침묵 상태).
3. **썬더링 허드 방지 (`EPOLLEXCLUSIVE`)**:
   - 동일한 타깃 FD를 여러 epoll 인스턴스(혹은 워커 스레드)가 `EPOLLEXCLUSIVE` 플래그로 감시하고 있을 때:
   - 새로운 이벤트가 발생하면, 모든 인스턴스를 깨우는 대신 **오직 1개의 인스턴스만** 라운드로빈 방식으로 선택하여 `rdllist`에 삽입합니다.

### 4. `EPOLL_WAIT` 처리 및 방출
- `epoll_wait` 호출 시, `rdllist`에서 최대 `min(max_events, max_events_per_wait)`개의 준비된 FD를 꺼내어 유저 공간으로 반환합니다.
- 반환된 각 항목에 대해:
  - **`EPOLLONESHOT`** 항목: 이벤트를 한 번 전달한 후 즉시 비활성화(`active = False`)되며, `EPOLL_CTL_MOD`로 재무장하기 전까지 더 이상 이벤트를 발생시키지 않습니다.
  - **`EPOLLET` (에지 트리거)** 항목: `rdllist`에서 완전히 제거되며, 새로운 에지가 발생할 때까지 다시 들어가지 않습니다.
  - **레벨 트리거 (LT)** 항목: 해당 시점에도 여전히 조건이 만족(예: `unread_bytes > 0`)되어 있다면, 다음 호출을 위해 `rdllist`에 다시 유지/재삽입됩니다.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "config": {
    "max_events_per_wait": 10
  },
  "file_descriptors": [
    {
      "fd": 10,
      "name": "lt_sock",
      "unread_bytes": 0,
      "writable": false,
      "hup": false
    }
  ],
  "operations": [
    {"op_id": 1, "type": "EPOLL_CREATE", "epfd": 1},
    {"op_id": 2, "type": "EPOLL_CTL_ADD", "epfd": 1, "target_fd": 10, "events": ["EPOLLIN"]},
    {"op_id": 3, "type": "FD_DATA_ARRIVE", "fd": 10, "new_bytes": 200},
    {"op_id": 4, "type": "EPOLL_WAIT", "epfd": 1, "thread_id": "worker-1", "max_events": 10},
    {"op_id": 5, "type": "FD_DATA_READ", "fd": 10, "read_bytes": 50},
    {"op_id": 6, "type": "EPOLL_WAIT", "epfd": 1, "thread_id": "worker-1", "max_events": 10}
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 JSON 객체를 단일 행으로 출력합니다:

```json
{
  "summary": {
    "total_epoll_instances": 1,
    "total_waits": 2,
    "total_events_delivered": 2,
    "total_errors": 0
  },
  "wait_results": [
    {
      "op_id": 4,
      "epfd": 1,
      "thread_id": "worker-1",
      "events_count": 1,
      "events": [
        {
          "fd": 10,
          "events": ["EPOLLIN"]
        }
      ]
    },
    {
      "op_id": 6,
      "epfd": 1,
      "thread_id": "worker-1",
      "events_count": 1,
      "events": [
        {
          "fd": 10,
          "events": ["EPOLLIN"]
        }
      ]
    }
  ],
  "errors": []
}
```

---

## 제약 사항
- `1 <= len(operations) <= 1,000`
- `1 <= max_events_per_wait <= 1,024`
- `events` 배열은 사전순(`sorted`)으로 정렬되어 반환되어야 합니다.
- `EPOLLHUP`은 감시 등록 여부와 무관하게 항상 보고될 수 있습니다.
