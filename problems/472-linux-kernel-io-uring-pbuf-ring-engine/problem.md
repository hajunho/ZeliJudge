# 리눅스 커널 io_uring 등록 버퍼 링(Provided Buffer Ring) 및 제로카피 네트워크 수신 엔진

## 1. 개요 및 배경

리눅스 고성능 네트워크 I/O 프레임워크인 `io_uring`은 수십만 개의 동시 접속(C1000K) 소켓을 처리할 때 시스템 콜 및 컨텍스트 스위칭 오버헤드를 극적으로 줄입니다.
과거 전통적인 소켓 I/O 모델에서는 각 연결마다 수신 버퍼를 사전 할당하거나, 고정된 크기의 버퍼 풀을 유지해야 하므로 수 기가바이트의 메모리가 유휴 상태로 낭비되었습니다.

초기 `io_uring`이 도입한 버퍼 그룹(`IORING_OP_PROVIDE_BUFFERS`)은 유저 공간이 커널로 버퍼를 공급할 때마다 SQE를 제출하고 CQE를 수신해야 하는 큐 오버헤드가 발생했습니다.
이를 완전히 해결하기 위해 **리눅스 5.19 커널**은 **등록 버퍼 링(Provided Buffer Ring, `IORING_REGISTER_PBUF_RING`)** 아키텍처를 도입했습니다.

`IORING_REGISTER_PBUF_RING`의 핵심 아키텍처 원리:
1. **유저-커널 공유 락리스 링버퍼 (`struct io_uring_buf_ring`)**:
   - 유저 공간과 커널이 단일 메모리 페이지(또는 mmap 매핑 영역)를 직접 공유합니다.
   - 버퍼 디스크립터 구조체 `struct io_uring_buf`는 메모리 주소(`addr`), 버퍼 크기(`len`), 버퍼 식별자(`bid`)를 담습니다.
   - 유저는 링의 `tail` 포인터를 원자적으로 전진시키며 버퍼를 링에 등록하고, 커널은 네트워크 패킷 도착 시 내부 `head` 포인터를 전진시키며 버퍼를 즉각 인출하여 패킷을 제로카피(Zero-Copy)로 복사/수신합니다.
2. **멀티샷 수신(Multishot Receive, `IORING_RECV_MULTISHOT`)**:
   - 단 한 번의 SQE 제출로 소켓에 수신 요청을 걸어두면, 커널은 데이터가 도착할 때마다 버퍼 링에서 새 버퍼를 자동 인출하여 CQE를 연속 발행합니다.
   - CQE 플래그에 `IORING_CQE_F_MORE` 비트(0x02)가 켜져 있는 한 SQE는 커널에 상주하며 계속 수신을 수행합니다.
   - CQE 상위 16비트(`flags >> 16`)에는 패킷이 담긴 버퍼의 `bid`가 인코딩되며, `IORING_CQE_F_BUFFER`(0x01) 비트가 함께 설정됩니다.
3. **버퍼 고갈 방어 및 에러 시맨틱 (`-ENOBUFS`)**:
   - 패킷이 도착했으나 공유 링의 버퍼가 고갈(`head == tail`)된 경우, 커널은 즉각 `-ENOBUFS`(-105) 에러 CQE를 발행하고 해당 멀티샷 SQE를 자동 해제(Cancel)합니다.
4. **소켓 종료(EOF / FIN) 및 명시적 취소(`CANCEL_RECV`)**:
   - TCP 연결이 정상 종료(FIN)되면 `res = 0` 및 `flags = 0`을 가진 종료 CQE를 발행하고 SQE를 정리합니다.
   - 사용자가 소켓 취소를 요청하면 `-ECANCELED`(-125) 에러 CQE를 발행합니다.

본 과제에서는 리눅스 커널 `io_uring/kbuf.c` 및 `io_uring/net.c`의 등록 버퍼 링 메커니즘을 완벽히 모사하는 고성능 비동기 수신 엔진을 구현합니다.

---

## 2. 아키텍처 다이어그램

```
+-----------------------------------------------------------------------------------------+
|                                    Userspace                                            |
|                                                                                         |
|   1. Register PBUF Ring: bgid=1, size=2^N, watermark=K                                  |
|   2. USER_ADD_BUFFERS / RETURN_BUFFERS:                                                |
|      * Write [bid, addr, len] into bufs[tail & mask]                                    |
|      * Advance tail pointer: tail = (tail + 1) & 0xFFFF                                 |
+-----------------------------------------------------------------------------------------+
                                         |
                                         | Shared Memory Ring (`struct io_uring_buf_ring`)
                                         v
+-----------------------------------------------------------------------------------------+
|                             Linux Kernel (io_uring)                                     |
|                                                                                         |
|   [ Ring Buffer Group (bgid=1) ]                                                        |
|   +-------------------+-------------------+-------------------+-------------------+     |
|   | bufs[0]: bid=10   | bufs[1]: bid=11   | bufs[2]: bid=12   | bufs[3]: (empty)  | ... |
|   +-------------------+-------------------+-------------------+-------------------+     |
|            ^                                           ^                                |
|            |                                           |                                |
|       kernel head (Consumer)                      user tail (Producer)                  |
|                                                                                         |
|   3. Incoming Packet arrives on Socket (fd):                                            |
|      - Check available buffers: (tail - head) & 0xFFFF                                  |
|      - If avail == 0: Emit CQE with res = -ENOBUFS (-105), Terminate Multishot          |
|      - If avail > 0:                                                                    |
|          * Fetch bufs[head & mask], advance head = (head + 1) & 0xFFFF                  |
|          * Read min(rx_data, buf.len) into userspace buffer                             |
|          * Emit CQE: flags = (bid << 16) | IORING_CQE_F_BUFFER | IORING_CQE_F_MORE      |
+-----------------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------------+
|                               Completion Queue (CQE)                                    |
|   [ CQE: sqe_id="sqe_1", res=1024, bid=10, flags=0x000A0003, multishot_active=true ]   |
+-----------------------------------------------------------------------------------------+
```

---

## 3. 핵심 규칙 및 상태 전이 사양

### 3.1 버퍼 링 등록 및 인덱싱 규칙
- `REGISTER_PBUF_RING`:
  - `bgid`: 버퍼 그룹 식별자.
  - `ring_entries`: 링 버퍼 크기 ($2^n$ 거듭제곱수, 예: 4, 8, 16). `mask = ring_entries - 1`.
  - `watermark`: 저버퍼 임계치. 남은 유효 버퍼 `(tail - head) & 0xFFFF < watermark`이면 `low_buffer_warning: true` 플래그 활성화.
- `USER_ADD_BUFFERS` / `RETURN_BUFFERS`:
  - 버퍼 디스크립터(`bid`, `addr`, `len`)를 `bufs[tail & mask]`에 기록하고 `tail = (tail + 1) & 0xFFFF`로 전진.

### 3.2 수신 요청 제출 (`SUBMIT_RECV`)
- `sqe_id`: SQE 요청 식별자.
- `fd`: 소켓 파일 디스크립터.
- `bgid`: 버퍼를 인출할 버퍼 그룹 ID.
- `multishot`: 불리언 (true이면 멀티샷 수신).
- `socket_type`: `"TCP"`(기본값, 스트림) 또는 `"UDP"`(데이터그램).
- 제출 시점에 해당 소켓의 수신 큐(`rx_queue`)에 미처리 데이터가 남아있다면 즉시 소켓 드레인(`_drain_socket`)을 수행.

### 3.3 패킷 도착 처리 (`RX_PACKET_ARRIVAL`)
1. 소켓 수신 큐에 패킷 바이트 적재 (`payload_bytes > 0`).
2. 소켓에 활성 SQE가 존재하는 경우 즉시 버퍼 인출 및 CQE 발행:
   - **버퍼 고갈 (`avail == 0`)**:
     - CQE 발행: `res = -105` (`-ENOBUFS`), `flags = 0`, `bid = null`, `status = "ENOBUFS"`.
     - 멀티샷 여부와 관계없이 해당 SQE는 커널 활성 테이블에서 즉각 제거(종료)됨. 남은 데이터는 소켓 큐에 잔류.
   - **버퍼 확보 성공**:
     - `head & mask` 위치의 버퍼를 취득하고 `head = (head + 1) & 0xFFFF`.
     - **TCP 스트림**: `bytes_read = min(payload, buf.len)`. 남은 데이터는 소켓 수신 큐에 유지되어 다음 버퍼로 연속 인출.
     - **UDP 데이터그램**: 하나의 버퍼가 하나의 데이터그램을 수신. 만약 `datagram > buf.len`이면 `bytes_read = buf.len`, `truncated = true`, `truncated_bytes = datagram - buf.len`이며 초과분은 폐기(Discard)됨.
     - CQE 플래그 계산:
       - 기본: `flags = (bid << 16) | 0x01` (`IORING_CQE_F_BUFFER`).
       - 멀티샷이 활성화된 경우: `flags |= 0x02` (`IORING_CQE_F_MORE`).
     - 싱글샷(`multishot == false`)인 경우 1회 수신 후 즉각 SQE 종료.
3. **EOF (TCP FIN, `eof == true`)**:
   - 소켓의 모든 수신 데이터가 드레인된 후 소켓이 EOF 상태이면:
     - `res = 0`, `flags = 0`, `bid = null`, `status = "EOF"`, `multishot_active = false`인 최종 CQE를 발행하고 SQE 종료.

### 3.4 명시적 요청 취소 (`CANCEL_RECV`)
- `sqe_id`에 해당하는 활성 SQE를 취소.
- `res = -125` (`-ECANCELED`), `flags = 0`, `status = "ECANCELED"`인 CQE 발행 및 활성 목록 제거.

---

## 4. 입출력 규격

### 입력 JSON 구조
```json
{
  "config": {},
  "operations": [
    {"type": "REGISTER_PBUF_RING", "bgid": 1, "ring_entries": 8, "watermark": 2},
    {"type": "USER_ADD_BUFFERS", "bgid": 1, "buffers": [
      {"bid": 10, "addr": "0x1000", "len": 1024},
      {"bid": 11, "addr": "0x1400", "len": 1024}
    ]},
    {"type": "SUBMIT_RECV", "sqe_id": "sqe_1", "fd": 4, "bgid": 1, "multishot": true, "socket_type": "TCP"},
    {"type": "RX_PACKET_ARRIVAL", "fd": 4, "payload_bytes": 1500, "data_tag": "stream_chunk", "eof": false},
    {"type": "QUERY_RING_STATE", "bgid": 1}
  ]
}
```

### 출력 JSON 구조
```json
{
  "operation_results": [
    {
      "op_index": 0,
      "type": "REGISTER_PBUF_RING",
      "bgid": 1,
      "ring_entries": 8,
      "status": "REGISTERED"
    },
    {
      "op_index": 1,
      "type": "USER_ADD_BUFFERS",
      "bgid": 1,
      "count_added": 2,
      "tail": 2,
      "available_buffers": 2,
      "low_buffer_warning": false
    },
    {
      "op_index": 2,
      "type": "SUBMIT_RECV",
      "sqe_id": "sqe_1",
      "fd": 4,
      "bgid": 1,
      "multishot": true,
      "cqes_generated": 0
    },
    {
      "op_index": 3,
      "type": "RX_PACKET_ARRIVAL",
      "fd": 4,
      "payload_bytes": 1500,
      "data_tag": "stream_chunk",
      "eof": false,
      "cqes_generated": 2
    },
    {
      "op_index": 4,
      "type": "QUERY_RING_STATE",
      "bgid": 1,
      "head": 2,
      "tail": 2,
      "available_buffers": 0,
      "capacity": 8,
      "low_buffer_warning": true
    }
  ],
  "cqe_log": [
    {
      "sqe_id": "sqe_1",
      "fd": 4,
      "res": 1024,
      "flags": 655363,
      "bid": 10,
      "buf_addr": "0x1000",
      "bytes_read": 1024,
      "truncated": false,
      "truncated_bytes": 0,
      "multishot_active": true,
      "status": "SUCCESS"
    },
    {
      "sqe_id": "sqe_1",
      "fd": 4,
      "res": 476,
      "flags": 720899,
      "bid": 11,
      "buf_addr": "0x1400",
      "bytes_read": 476,
      "truncated": false,
      "truncated_bytes": 0,
      "multishot_active": true,
      "status": "SUCCESS"
    }
  ],
  "summary": {
    "total_operations": 5,
    "rings": {
      "1": {
        "head": 2,
        "tail": 2,
        "available_buffers": 0,
        "capacity": 8,
        "low_buffer_warning": true
      }
    },
    "active_sqes": [4],
    "stats": {
      "total_cqes": 2,
      "total_bytes_received": 1500,
      "total_enobufs_errors": 0,
      "total_canceled_requests": 0,
      "total_truncated_packets": 0,
      "total_buffers_added": 2,
      "total_buffers_consumed": 2
    }
  }
}
```
