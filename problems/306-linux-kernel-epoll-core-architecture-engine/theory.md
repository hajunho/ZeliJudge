# 기술 이론: 리눅스 커널 epoll(fs/eventpoll.c) 내부 아키텍처 및 고성능 I/O 다중화

## 1. 전통적 I/O 다중화의 한계와 C10K 문제
리눅스 초기 I/O 다중화 시스템 콜인 `select()`와 `poll()`은 매 호출마다 다음과 같은 치명적 비효율을 가졌습니다:
- 유저 공간 $\leftrightarrow$ 커널 공간 간 FD 세트 전체 메모리 복사 ($O(N)$).
- 커널 내부에서 어떤 소켓에 데이터가 도착했는지 알 수 없으므로 전체 $N$개 소켓을 매번 순회 ($O(N)$).
- 파일 디스크립터가 10,000개를 넘어가는 순간, 99.9%의 소켓이 유휴(Idle) 상태임에도 불구하고 CPU는 무의미한 폴링 순회에 100% 소진됩니다.

리눅스 커널 2.6에 도입된 `epoll`은 관심 소켓을 커널 내부에 미리 등록해 두고, **이벤트가 실제로 발생한 소켓만 커널이 역으로 수집하여 반환하는 이벤트 드리븐(Event-Driven)** 모델을 완성했습니다.

```
 [ 유저 애플리케이션 (NGINX, Redis, Tokio) ]
                    │
            epoll_wait(epfd)
                    │
 ┌──────────────────▼───────────────────────────────────┐
 │ 리눅스 커널 fs/eventpoll.c                           │
 │                                                      │
 │   ┌──────────────────────┐   ┌───────────────────┐   │
 │   │  rbr (Red-Black Tree)│   │  rdllist (Ready)  │   │
 │   │  전체 감시 대상 소켓 │   │  이벤트 발생 소켓 │   │
 │   └──────────┬───────────┘   └─────────▲─────────┘   │
 └──────────────┼─────────────────────────┼─────────────┘
                │                         │
      ep_ptable_queue_proc()       ep_poll_callback()
                │                         │
 ┌──────────────▼─────────────────────────┴─────────────┐
 │  하부 네트워크 스택 (net/ipv4, tcp_input.c)          │
 │  NIC RX 패킷 수신 인터럽트 -> sk_data_ready()        │
 └──────────────────────────────────────────────────────┘
```

---

## 2. 핵심 자료구조: `struct eventpoll`과 `struct epitem`

리눅스 커널 `fs/eventpoll.c`의 중심 구조체는 다음과 같습니다:

```c
struct eventpoll {
    struct mutex mtx;
    wait_queue_head_t wq;            // epoll_wait()로 대기 중인 스레드 큐
    struct list_head rdllist;        // 준비된 소켓들의 이중 연결 리스트
    struct rb_root_cached rbr;       // 감시 중인 epitem들을 관리하는 RB-Tree
    struct epitem *ovflist;          // 락 경합 시 임시 보관 오버플로우 리스트
};

struct epitem {
    struct rb_node rbn;              // rbr 트리에 삽입되는 노드
    struct list_head rdllink;        // rdllist에 연결되는 링크
    struct epoll_filefd ffd;         // 대상 파일 구조체 및 FD 번호
    struct eventpoll *ep;            // 자신이 속한 eventpoll 인스턴스
    __poll_t events;                 // 관심 이벤트 마스크 (EPOLLIN, EPOLLET 등)
};
```

---

## 3. Level-Triggered (LT) vs Edge-Triggered (ET)

| 특성 | 레벨 트리거 (LT, Level-Triggered) | 에지 트리거 (ET, Edge-Triggered) |
| :--- | :--- | :--- |
| **기본값 여부** | 리눅스 epoll 기본 동작 모드 | `EPOLLET` 플래그 명시 필요 |
| **트리거 조건** | 조건이 참인 동안 (예: `buffer > 0`) 지속적으로 통지 | 상태가 거짓에서 참으로 전이되는 순간(에지) 1회만 통지 |
| **부분 읽기 동작** | 버퍼에 1바이트라도 남아 있으면 다음 wait에서 즉시 반환 | 남은 데이터가 있어도 새로운 패킷이 오기 전까지 절대 통지 안 함 |
| **소켓 모드 요건** | 블로킹 / 넌블로킹 모두 가능 | **반드시 넌블로킹(O_NONBLOCK)** 필수! |
| **사용자 처리 패턴** | 단일 read/write 호출 가능 | 루프를 돌며 `EAGAIN` 또는 `EWOULDBLOCK`이 뜰 때까지 전부 읽어야 함 |
| **성능 및 복잡도** | 구현이 단순하고 안전함 | 시스템 콜 횟수를 줄일 수 있으나 기아(Starvation) 및 누락 위험 |

---

## 4. 썬더링 허드와 `EPOLLEXCLUSIVE` (Linux 4.5+)

멀티코어 환경에서 고성능 웹 서버(NGINX)는 여러 워커 프로세스가 동일한 수신 대기 소켓(`listen_fd`)을 자신의 epoll에 각각 등록하고 동시에 `epoll_wait`를 호출합니다.

1. **기존 문제**: 새 클라이언트 연결 1개가 들어오면, 커널 대기 큐의 모든 워커가 일제히 깨어납니다(Thundering Herd). 오직 1개 워커만 `accept()`에 성공하고 나머지 $K-1$개 워커는 `EAGAIN`을 받으며 엄청난 컨텍스트 스위칭 오버헤드가 발생합니다.
2. **`EPOLLEXCLUSIVE` 해결책**: 커널 대기 큐 항목에 `WQ_FLAG_EXCLUSIVE` 플래그를 설정하여, 이벤트 발생 시 대기 중인 워커 중 **오직 1개 워커만** 깨우고 즉시 순회를 종료합니다. 이를 통해 컨텍스트 스위칭을 0으로 억제하고 CPU 효율을 극대화합니다.
