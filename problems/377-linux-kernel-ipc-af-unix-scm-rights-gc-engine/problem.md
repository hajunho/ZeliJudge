# #377 - 리눅스 커널 UNIX 도메인 소켓 (AF_UNIX / SCM_RIGHTS): 파일 디스크립터 전달, 순환 참조 누수 탐지 및 unix_gc 가비지 컬렉션 엔진

## 📖 문제 배경과 역사적 맥락

> *"UNIX 도메인 소켓(AF_UNIX)은 `sendmsg()`와 보조 제어 메시지(`SCM_RIGHTS`)를 통해 프로세스 간에 열린 파일 디스크립터(File Descriptor)를 직접 전달하는 강력한 IPC 메커니즘을 제공한다. 그러나 전달되는 파일 디스크립터 자체가 또 다른 UNIX 도메인 소켓일 경우, 소켓 A의 수신 버퍼가 소켓 B를 참조하고 소켓 B의 수신 버퍼가 소켓 A를 참조하는 '순환 참조(Circular In-flight Reference)' 고리가 형성될 수 있다. 유저스페이스에서 소켓을 모두 닫더라도 커널 `sk_buff` 내부 참조로 인해 파일이 영구히 해제되지 않는 치명적 자원 고갈이 발생하며, 이를 해결하기 위해 리눅스 커널은 전용 가비지 컬렉터인 `unix_gc()`를 구동한다."*  
> — **Linux Kernel IPC Subsystem (`net/unix/af_unix.c`, `net/unix/garbage.c`)**

리눅스 시스템에서 프로세스 간 통신(IPC)의 중추인 **UNIX 도메인 소켓(AF_UNIX)**은 단일 호스트 내부에서 네트워크 스택(IP/TCP 오버헤드)을 거치지 않고 최고 속도의 메모리 복사 및 자격 증명 교환을 수행합니다. systemd, Wayland 디스플레이 서버, Docker 컨테이너 런타임, Chrome 샌드박스 등 모든 현대적 리눅스 기반 서비스가 AF_UNIX 소켓에 의존합니다.

그중에서도 가장 독보적인 기능은 **`SCM_RIGHTS`**입니다:
- 부모 프로세스가 권한이 필요한 파일(`struct file *`)을 연 뒤, 자식 또는 격리된 샌드박스 프로세스에게 소켓 보조 데이터(`struct cmsghdr`)를 통해 파일 디스크립터를 안전하게 인계할 수 있습니다.

```
       [Process 1]                                      [Process 2]
            │                                                │
       open file fd=3                                        │
            │                                                │
   sendmsg(sock_A,                                           │
     cmsg: SCM_RIGHTS, fd=3)                                 │
            │                                                │
            ▼                                                │
   ┌──────────────────────┐                                  │
   │  sock_B's rcv_queue  │                                  │
   │  ┌────────────────┐  │                                  │
   │  │ sk_buff:       │  │                                  │
   │  │ hold file fd=3 │  │                                  │
   │  └────────────────┘  │                                  │
   └──────────────────────┘                                  │
            │                                                ▼
            │ ───────────────────────────────────────> recvmsg(sock_B)
            │                                          install new fd=7
```

### 순환 참조(Circular Reference)의 함정과 `unix_gc()`의 필연성
하지만 `SCM_RIGHTS`로 전달되는 파일이 **또 다른 UNIX 도메인 소켓**일 때 커널 메모리 모델에 치명적인 맹점이 발생합니다:
1. 소켓 $S_1$이 소켓 $S_2$의 파일 디스크립터를 메시지에 실어 $S_1$ 자신(또는 $S_3$)의 수신 큐에 넣습니다.
2. 소켓 $S_2$는 소켓 $S_1$의 파일 디스크립터를 자신의 수신 큐에 넣습니다.
3. 두 프로세스가 사용자 공간에서 $S_1$과 $S_2$의 파일 디스크립터를 `close()`합니다.
4. **결과**: 사용자 공간의 참조 횟수(`external_refs`)는 0이 되었지만, 커널 내부 수신 버퍼의 `sk_buff`가 서로의 소켓을 물고 있어 `inflight_refs`가 1로 유지됩니다.
5. 표준 `fput()` 참조 카운터는 0이 되지 않으므로 소켓 구조체와 버퍼 메모리가 영구히 해제되지 않아, 악의적 공격자가 시스템의 모든 파일 디스크립터와 RAM을 순식간에 고갈시킬 수 있습니다.

리눅스 커널은 이 문제를 해결하기 위해 `net/unix/garbage.c`에 **`unix_gc()` 가비지 컬렉터**를 탑재했습니다:
- 사용자 공간의 유효한 파일 디스크립터(`external_refs > 0`)를 루트(Root) 노드로 지정하고 도달 가능성(Reachability) BFS 탐색을 수행합니다.
- 어떠한 살아있는 루트 소켓에서도 도달할 수 없는 고립된 순환 소켓 클러스터를 감지하여, 수신 큐의 메시지를 강제 파기하고 순환 소켓들을 일괄 회수(`free_socket`)합니다.

본 과제에서는 리눅스 커널의 AF_UNIX 소켓 버퍼 관리 및 `unix_gc()` 순환 참조 탐지 알고리즘을 완벽히 모델링하는 시뮬레이션 엔진을 구현합니다.

---

## 📥 입력 형식 (Input Specification)

입력은 표준 입력(Standard Input)으로 단일 JSON 객체가 주어집니다:

```json
{
  "config": {
    "default_rcvbuf": 65536
  },
  "initial_state": {
    "sockets": ["s1", "s2", "s3"]
  },
  "events": [
    {
      "type": "SEND_MSG_SCM_RIGHTS",
      "params": {
        "src_socket": "s1",
        "dst_socket": "s1",
        "data_bytes": 100,
        "passed_fds": ["s2"],
        "msg_id": "m1"
      }
    },
    {
      "type": "SEND_MSG_SCM_RIGHTS",
      "params": {
        "src_socket": "s2",
        "dst_socket": "s2",
        "data_bytes": 100,
        "passed_fds": ["s1"],
        "msg_id": "m2"
      }
    },
    {
      "type": "CLOSE_FD",
      "params": {
        "socket_id": "s1"
      }
    },
    {
      "type": "CLOSE_FD",
      "params": {
        "socket_id": "s2"
      }
    },
    {
      "type": "RUN_UNIX_GC",
      "params": {}
    }
  ]
}
```

### 제약조건 및 파라미터 규칙:
1. `config`:
   - `default_rcvbuf`: 각 소켓의 최대 수신 버퍼 크기 (바이트 단위 정수, 기본값 `65536`).
2. `initial_state`:
   - `sockets`: 초기 생성할 소켓 식별자 문자열 목록. 초기화 시 각 소켓은 `external_refs = 1`, `inflight_refs = 0`, `rcv_buf_used = 0`, `alive = true`로 생성됩니다.
3. `events`: 다음 5가지 커널 IPC 이벤트가 순서대로 발생합니다:
   - `CREATE_SOCKET`:
     - 파라미터: `socket_id`.
     - 새 소켓을 생성 (`external_refs = 1`, `inflight_refs = 0`, `alive = true`).
     - 상태: `SOCKET_CREATED`.
   - `SEND_MSG_SCM_RIGHTS`:
     - 파라미터: `src_socket`, `dst_socket`, `data_bytes`, `passed_fds` (소켓 ID 배열), `msg_id`.
     - 동작:
       1. `dst_socket`이 존재하지 않거나 죽어있으면 상태: `DESTINATION_DEAD`.
       2. `dst_socket`의 `rcv_buf_used + data_bytes > default_rcvbuf`이면 수신 버퍼 고갈로 패킷 드롭, `total_overflow_drops += 1`, 상태: `BUFFER_OVERFLOW_DROPPED`.
       3. 정상 전송 시: 메시지를 `dst_socket`의 `rcv_queue`에 큐잉하고, `rcv_buf_used += data_bytes`. `passed_fds`에 포함된 각 소켓의 `inflight_refs`를 1씩 증가. 상태: `MSG_SENT`.
   - `RECV_MSG`:
     - 파라미터: `socket_id`.
     - 동작: 해당 소켓의 `rcv_queue`에서 가장 오래된 메시지를 꺼냄. `rcv_buf_used` 차감. 전달되었던 각 소켓의 `inflight_refs`를 1 감소시키고, 사용자 공간 FD로 수신되었으므로 `external_refs`를 1 증가. 상태: `MSG_RECEIVED`. 큐가 비어있으면 `QUEUE_EMPTY`.
   - `CLOSE_FD`:
     - 파라미터: `socket_id`.
     - 동작:
       1. `external_refs`를 1 감소시킴.
       2. 만약 `external_refs == 0`이고 `inflight_refs == 0`: 즉시 해제(`free_socket`). 수신 큐에 남아있던 메시지들을 모두 폐기하며, 그 메시지들이 품고 있던 FD의 `inflight_refs`도 연쇄 차감(연쇄 차감으로 0이 된 소켓도 재귀 해제). 상태: `SOCKET_FREED`.
       3. 만약 `external_refs == 0`이지만 `inflight_refs > 0`: 사용자 공간에서는 닫혔으나 큐 내부에서 비행 중이므로 대기. 상태: `ORPHANED_IN_FLIGHT`.
       4. `external_refs > 0`으로 남아있으면 상태: `FD_CLOSED`.
   - `RUN_UNIX_GC`:
     - 파라미터: 없음.
     - 동작 (리눅스 커널 `unix_gc` 알고리즘):
       1. 살아있는 모든 소켓 중 사용자 공간 참조가 살아있는 소켓(`external_refs > 0`)을 탐색의 시작 루트(Root) 집합으로 지정.
       2. 루트 소켓들의 수신 큐에 들어있는 `passed_fds`를 따라 BFS로 도달 가능한 모든 소켓을 `reachable` 집합에 추가.
       3. 살아있는 소켓 중 `reachable` 집합에 속하지 못한 소켓들은 **외부에서 결코 접근할 수 없는 죽은 순환 참조 고리(Dead Cycle Garbage)**로 확정!
       4. 죽은 소켓 목록을 사전순 정렬 후 각각 `free_socket`을 호출하여 강제 회수하고 `total_gc_purged` 증가. 상태: `GC_RUN_COMPLETED`.

---

## 📤 출력 형식 (Output Specification)

시뮬레이션 완료 후 최종 커널 소켓 테이블 상태를 압축 JSON 문자열(`separators=(',', ':')`, `ensure_ascii=False`)로 표준 출력에 인쇄합니다:

```json
{
  "alive_socket_count": 1,
  "total_gc_purged": 2,
  "total_overflow_drops": 0,
  "sockets": {
    "s1": {
      "alive": false,
      "external_refs": 0,
      "inflight_refs": 0,
      "rcv_buf_used": 0,
      "queue_len": 0
    },
    "s2": {
      "alive": false,
      "external_refs": 0,
      "inflight_refs": 0,
      "rcv_buf_used": 0,
      "queue_len": 0
    },
    "s3": {
      "alive": true,
      "external_refs": 1,
      "inflight_refs": 0,
      "rcv_buf_used": 0,
      "queue_len": 0
    }
  },
  "history": [
    {
      "epoch": 1,
      "event": "SEND_MSG_SCM_RIGHTS",
      "status": "MSG_SENT",
      "alive_socket_count": 3,
      "purged_sockets": [],
      "detail": "Sent msg m1 to s1 with FDs ['s2']."
    }
  ]
}
```

---

## 🎯 채점 기준 및 제약 조건

1. 정확성 100%: 8개 모든 테스트케이스의 수치 및 소켓 생존 여부, `unix_gc` 회수 결과가 완벽히 일치해야 합니다.
2. 루트 기반 BFS 도달성 분석을 통해 유효한 소켓과 순환 참조 고립 가비지를 정확히 판별해야 합니다.
3. Windows 환경에서의 UTF-8 입출력을 준수해야 합니다.
