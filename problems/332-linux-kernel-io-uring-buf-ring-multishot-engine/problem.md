# Linux Kernel io_uring Provided Buffer Ring (io_uring_buf_ring), Multishot Recv & Zero-Copy Send 엔진

## 문제 설명

수십만 동시 연결을 처리하는 고성능 네트워크 서버(예: Nginx, Envoy, Redis)에서 메모리 소비와 시스템 콜 오버헤드는 서비스 확장성을 가로막는 치명적인 장벽입니다.

기존의 `epoll` 기반 아키텍처에서는 각 소켓 연결마다 미리 고정 크기(예: 64KB)의 수신 버퍼를 할당해야 했습니다. 연결 수가 10만 개에 달하면 실제 패킷이 오가지 않는 유휴(Idle) 상태임에도 불구하고 수 기가바이트(GB) 이상의 RAM이 낭비되는 메모리 블로트(Memory Bloat)가 발생했습니다.

리눅스 커널 5.19 및 6.x에서 젠스 악스보(Jens Axboe)는 이를 근본적으로 해결하기 위해 **Provided Buffer Ring (`io_uring_buf_ring`)**, **멀티샷 수신 (`IORING_RECV_MULTISHOT`)**, 그리고 **제로카피 송신 (`IORING_OP_SEND_ZC`)**을 도입했습니다:

1. **공유 메모리 제공 버퍼 링 (`io_uring_buf_ring`)**:
   - 유저 공간과 커널 공간이 단일 링 버퍼(`struct io_uring_buf_ring`)를 공유합니다.
   - 유저 공간은 풀(Pool)에서 가용한 버퍼 구조체(`struct io_uring_buf { addr, len, bid }`)를 채워 넣고 `tail`을 전진시킵니다.
   - 커널은 소켓에 패킷이 도착했을 때만 링의 `head`에서 버퍼 1개를 꺼내어 데이터를 복사하므로, 10만 개 연결이 있더라도 활성 패킷 수만큼만 버퍼를 소비하는 **제로-메모리 낭비(Zero Memory Waste)**를 달성합니다.
2. **멀티샷 수신 (`IORING_RECV_MULTISHOT`)**:
   - 단 한 번의 SQE 제출로 소켓 수신 요청이 영구히 유지됩니다.
   - 패킷이 수신될 때마다 커널은 `buf_ring`에서 버퍼를 꺼내 채우고, `IORING_CQE_F_MORE` 플래그가 설정된 완료 이벤트(CQE)를 연속으로 방출합니다.
   - 더 이상 매번 패킷을 받을 때마다 새로운 시스템 콜이나 SQE를 재제출할 필요가 없습니다.
3. **버퍼 고갈 방어 (`-ENOBUFS / -105`)**:
   - 만약 커널이 패킷을 수신하려 할 때 `head == tail`(버퍼 링이 빔) 상태라면, 즉시 `res = -ENOBUFS (-105)` 오류 CQE를 발생시키고 해당 멀티샷 수신 요청을 비활성화하여 시스템 폭주를 방어합니다.
4. **제로카피 네트워크 송신 (`IORING_OP_SEND_ZC`) 2단계 완료**:
   - 호스트 메모리에서 네트워크 인터페이스 카드(NIC)로 데이터를 직접 전송(DMA)합니다.
   - **1단계**: 커널이 패킷 송신 큐에 등록 완료 시 송신 바이트 수와 함께 `IORING_CQE_F_MORE`가 켜진 CQE를 방출합니다.
   - **2단계**: NIC 하드웨어가 물리적 전송을 끝내고 DMA 버퍼를 해제하면, 알림 CQE(`res = 0`, `IORING_CQE_F_NOTIF`)를 방출하여 유저 공간에 버퍼 재사용/해제가 안전함을 알립니다.

당신은 고성능 리눅스 시스템 프로그래머로서, **리눅스 커널 6.x `io_uring/kbuf.c` 및 `io_uring/net.c`의 `io_uring_buf_ring`, 멀티샷 수신 및 제로카피 송신 상태 머신 엔진**을 완벽하게 구현해야 합니다.

```
+-------------------------------------------------------------------------+
|      Linux Kernel io_uring_buf_ring & Multishot Network Engine          |
+-------------------------------------------------------------------------+
| [User-Space Buffer Pool]                                                |
|   - struct io_uring_buf_ring { struct io_uring_buf bufs[size]; tail; }  |
|   - Lockless tail advancement by userspace (io_uring_buf_ring_advance)  |
+------------------------------------+------------------------------------+
                                     | (Zero-Syscall Shared Ring)
                                     v
+-------------------------------------------------------------------------+
| [Kernel Network Ingress: Multishot Recv]                                |
|   - Packet Arrives on Socket fd -> Atomically Pop buf from head         |
|   - Buffer Shift CQE Flag: (bid << 16) | IORING_CQE_F_BUFFER            |
|   - Continuous Emission: IORING_CQE_F_MORE (Until EOF or Error)         |
|   - Buffer Exhaustion Defense: -ENOBUFS (-105)                          |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
| [Kernel Network Egress: Zero-Copy Send (IORING_OP_SEND_ZC)]             |
|   - Phase 1: Immediate Send CQE (res = len, flags = IORING_CQE_F_MORE)  |
|   - Phase 2: Hardware NIC DMA Complete -> Notification CQE (NOTIF)      |
+-------------------------------------------------------------------------+
```

---

## 엔진 규격 및 수리적 모델링

### 1. 상수 정의
- `IORING_CQE_F_BUFFER` = `0x0001` (버퍼 ID 포함 플래그)
- `IORING_CQE_F_MORE` = `0x0002` (추가 CQE 대기 플래그)
- `IORING_CQE_F_NOTIF` = `0x0004` (제로카피 하드웨어 완료 알림 플래그)
- `IORING_CQE_BUFFER_SHIFT` = 16 (CQE flags 상위 16비트에 `bid` 수납)
- `ENOBUFS` = `-105` (버퍼 고갈 에러 코드)

### 2. 버퍼 링 등록 (`REGISTER_BUF_RING`)
- 입력: `bgid` (Buffer Group ID, 정수), `ring_size` (버퍼 링 크기, 2의 거듭제곱)
- 상태:
  - `ring`: 크기 `ring_size`의 배열 (`bid`, `addr`, `len`)
  - `head = 0` (커널 소비 인덱스), `tail = 0` (유저 공급 인덱스)

### 3. 버퍼 추가 (`ADD_BUFFERS`)
- 입력: `bgid`, `buffers` (리스트: `[{"bid": int, "addr": int, "len": int}, ...]`)
- 절차:
  - 각 버퍼를 `tail % ring_size` 슬롯에 기록 후 `tail += 1`.
  - 가용 버퍼 수 `available_buffers = tail - head`.

### 4. 수신 요청 등록 (`SUBMIT_RECV`)
- 입력: `user_data` (정수 식별자), `fd` (소켓 디스크립터), `bgid` (버퍼 그룹 ID), `multishot` (불리언, 기본값 true)
- 소켓 `fd`에 대한 활성 수신 요청 생성 (`active = true`).

### 5. 인커밍 패킷 수신 (`INCOMING_PACKET`)
- 입력: `fd`, `payload_len`, `is_eof` (기본값 false), `is_error` (기본값 false)
- 처리 로직:
  1. `fd`에 매핑된 활성 수신 요청 검색. 없으면 `NO_MATCHING_RECV_REQ` 반환.
  2. 해당 요청의 `bgid` 버퍼 링 확인:
     - 만약 `head == tail` (버퍼 고갈!):
       - `starvation_count += 1`, 요청 비활성화 (`active = false`).
       - CQE 방출: `user_data`, `res = ENOBUFS (-105)`, `flags = 0`, `bid = null`.
     - 가용 버퍼가 있는 경우:
       - `head % ring_size` 슬롯에서 버퍼 획득, `head += 1`.
       - 복사 바이트 수: `bytes = min(payload_len, buf.len)`.
       - CQE 플래그: `flags = IORING_CQE_F_BUFFER | (buf.bid << 16)`.
       - 만약 `multishot == true` 이고 `is_eof == false` 이고 `is_error == false` 이면:
         - `flags |= IORING_CQE_F_MORE`.
       - 그렇지 않으면 요청 종료 (`active = false`).
       - CQE 방출: `user_data`, `res = bytes`, `flags = flags`, `bid = buf.bid`.

### 6. 제로카피 송신 (`SUBMIT_SEND_ZC`)
- 입력: `user_data`, `fd`, `addr`, `len`
- 처리 로직:
  - 1단계 송신 완료 CQE 즉시 방출: `user_data`, `res = len`, `flags = IORING_CQE_F_MORE`.
  - 해당 요청에 대해 `notif_pending = true`로 추적.

### 7. NIC 송신 DMA 완료 (`NIC_TX_COMPLETE`)
- 입력: `user_data`
- 처리 로직:
  - 보류 중인 제로카피 요청에 대해 2단계 알림 CQE 방출: `user_data`, `res = 0`, `flags = IORING_CQE_F_NOTIF`.
  - 요청 추적 종료.

### 8. CQE 회수 (`HARVEST_CQES`)
- 입력: `max_cqes` (기본값 16)
- 대기 중인 CQE 큐에서 최대 `max_cqes`개 꺼내어 반환.

### 9. 상태 검사 (`INSPECT`)
- 버퍼 링별 `head`, `tail`, `available`, 활성 수신 요청 목록, 보류 중인 제로카피 송신 목록, 누적 통계 반환.

---

## 입력 형식

표준 입력(stdin)으로 JSON 배열 형태의 명령어 목록이 주어집니다.

```json
[
  {"op": "REGISTER_BUF_RING", "bgid": 1, "ring_size": 8},
  {
    "op": "ADD_BUFFERS",
    "bgid": 1,
    "buffers": [
      {"bid": 0, "addr": 65536, "len": 1024},
      {"bid": 1, "addr": 66560, "len": 1024}
    ]
  },
  {"op": "SUBMIT_RECV", "user_data": 1001, "fd": 10, "bgid": 1, "multishot": true},
  {"op": "INCOMING_PACKET", "fd": 10, "payload_len": 512},
  {"op": "HARVEST_CQES", "max_cqes": 1},
  {"op": "INSPECT"}
]
```

---

## 출력 형식

표준 출력(stdout)으로 각 명령어의 실행 결과를 담은 JSON 배열을 공백 없이 한 줄로 출력합니다.

```json
[{"op":"REGISTER_BUF_RING","result":{"status":"BUF_RING_REGISTERED","bgid":1,"ring_size":8}},{"op":"ADD_BUFFERS","result":{"status":"BUFFERS_ADDED","bgid":1,"added_count":2,"tail":2,"head":0,"available_buffers":2}},{"op":"SUBMIT_RECV","result":{"status":"RECV_SUBMITTED","user_data":1001,"fd":10,"bgid":1,"multishot":true}},{"op":"INCOMING_PACKET","result":{"status":"PACKET_PROCESSED","user_data":1001,"consumed_bid":0,"bytes_transferred":512,"remaining_buffers":1,"cqe_emitted":{"user_data":1001,"res":512,"flags":3,"bid":0,"is_notif":false}}},{"op":"HARVEST_CQES","result":{"status":"CQES_HARVESTED","count":1,"cqes":[{"user_data":1001,"res":512,"flags":3,"bid":0,"is_notif":false}],"remaining_cqes":0}},{"op":"INSPECT","result":{"buf_rings":{"1":{"size":8,"head":1,"tail":2,"available":1}},"active_recv_requests":[1001],"pending_zc_notifs":[],"queued_cqe_count":0,"stats":{"total_buffers_consumed":1,"total_packets_received":1,"total_bytes_received":512,"total_bytes_sent_zc":0,"starvation_count":0}}}]
```

---

## 제약 사항

- 버퍼 링 크기 $B \in \{4, 8, 16, 32, 64, 128, 256, 512, 1024\}$
- 버퍼 그룹 수 $\le 16$
- 명령어 수 $M \le 10,000$
- 시간 제한: 5.0초
- 메모리 제한: 512MB
