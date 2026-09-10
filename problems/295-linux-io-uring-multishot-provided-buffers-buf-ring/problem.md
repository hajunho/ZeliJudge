# Problem #295: Linux io_uring Multishot Receive & Provided Buffer Ring (io_uring_buf_ring)

## 1. 개요 및 배경 (Overview & Background)

리눅스 고성능 비동기 I/O 프레임워크인 **io_uring**은 시스템 콜(Syscall) 오버헤드를 0으로 줄여 네트워크 서버의 성능을 비약적으로 향상시켰습니다. 그러나 초기 io_uring 수신(`IORING_OP_RECV`) 모델에는 치명적인 메모리 비효율이 존재했습니다:
- 수만 개의 유휴(Idle) TCP 연결이 데이터 유입을 대기할 때, 각 소켓마다 개별 SQE(Submission Queue Entry)에 고정 크기 메모리 버퍼(예: 64KB)를 미리 바인딩하여 제출해야 했습니다.
- 이로 인해 실제로 패킷이 오지 않는 연결들로 인해 수 기가바이트(GB)의 소중한 DRAM이 커널-유저 공간에 낭비되었습니다.

이를 해결하기 위해 리눅스 5.19 커널에서 **제공된 버퍼 링(Provided Buffer Ring: `struct io_uring_buf_ring`)**과 **멀티샷 수신(Multishot Receive: `IORING_RECV_MULTISHOT` / `IOSQE_BUFFER_SELECT`)**이 도입되었습니다.

```
+-------------------------------------------------------------------------------+
|             Linux io_uring Multishot Receive & Provided Buffer Ring           |
+-------------------------------------------------------------------------------+
  [ Userspace Application ]                      [ Linux Kernel io_uring ]
            |                                               |
  1. Register Buffer Ring (bgid=1) ------------------------>|  Shared Mmap Ring
     (Add buffers: bid 101, 102...)                         |  (io_uring_buf_ring)
            |                                               |
  2. Single SQE: IORING_RECV_MULTISHOT -------------------->|  ARMED in kernel!
     (fd=5, bgid=1, user_data=100)                          |  (Zero per-packet SQE)
                                                            |
                          [ Network Packet Arrives on fd=5 ]|
                                                            |
                                                   [ Check Buffer Ring ]
                                                            |
                                        +-------------------+-------------------+
                                        | Buffer Available                      | Buffer Starved (Empty)
                                        v                                       v
                                [ Pop Buffer (bid 101) ]               [ Disarm Multishot ]
                                [ Copy Rx Payload ]                    [ CQE: res = -ENOBUFS ]
                                [ CQE: res=Len, MORE=1, bid=101 ]      [ flags = 0 ]
                                        |                                       |
  3. Read CQE (bid=101) <---------------+                                       v
     Process Payload & Replenish bid 101                                 [ Starvation Alert ]
```

### 핵심 아키텍처 원리
1. **단일 멀티샷 SQE 등록**: 단 한 번의 SQE 제출로 소켓이 닫히거나 에러가 발생할 때까지 커널에서 수신 대기를 영구적으로 유지합니다.
2. **동적 버퍼 선택 (`IOSQE_BUFFER_SELECT`)**: 패킷이 실제 네트워크 카드로부터 도착하는 순간에만 커널이 공유 버퍼 링(`bgid`)에서 사용 가능한 버퍼(`bid`)를 꺼내어 페이로드를 담습니다.
3. **CQE 연쇄 발행 및 `IORING_CQE_F_MORE`**: 각 수신마다 완성 큐(CQ)로 CQE를 발행하며, `flags`에 `IORING_CQE_F_MORE` 비트를 설정하여 멀티샷이 활성 상태임을 알립니다.
4. **버퍼 고갈과 `-ENOBUFS`**: 버퍼 링이 비어있으면 커널은 `res = -ENOBUFS` (-105) CQE를 발행하고 멀티샷 요청을 즉시 해제(Disarm)합니다.

이 문제에서는 최신 리눅스 커널의 io_uring 멀티샷 및 제공된 버퍼 링 엔진을 정밀 시뮬레이션하여, 제로 할당 수신, 동적 버퍼 보충, EOF 정상 종료, 취소(`ASYNC_CANCEL`), 버퍼 고갈 방어 상태 머신을 구현합니다.

---

## 2. 입출력 규격 (Input & Output Specification)

### 입력 형식 (Standard Input)
표준 입력(stdin)으로 JSON 객체가 주어집니다.
```json
{
  "config": {
    "sq_depth": 128,
    "cq_depth": 256
  },
  "initial_buffers": [
    {
      "bgid": 1,
      "buffers": [
        {"bid": 101, "len": 4096},
        {"bid": 102, "len": 4096}
      ]
    }
  ],
  "events": [
    {
      "type": "SUBMIT_MULTISHOT",
      "time_us": 0.0,
      "user_data": 1001,
      "fd": 5,
      "bgid": 1
    },
    {
      "type": "SOCKET_DATA",
      "time_us": 10.0,
      "fd": 5,
      "data_len": 1460
    }
  ]
}
```

- `config`:
  - `sq_depth` (int): 제출 큐 크기.
  - `cq_depth` (int): 완성 큐 크기.
- `initial_buffers`: 등록할 버퍼 그룹 목록.
  - `bgid` (int): 버퍼 그룹 ID.
  - `buffers`: 등록할 버퍼 객체 목록 (`bid`, `len`).
- `events`: 시간순 이벤트 목록.
  - `type`:
    - `"SUBMIT_MULTISHOT"`: 멀티샷 수신 등록 (`time_us`, `user_data`, `fd`, `bgid`).
    - `"SOCKET_DATA"`: 소켓 패킷 유입 (`time_us`, `fd`, `data_len`).
    - `"REPLENISH"`: 유저스페이스 버퍼 반환 및 보충 (`time_us`, `bgid`, `bid`, `len`).
    - `"CANCEL"`: 요청 취소 (`time_us`, `user_data`).

### 처리 규칙 (Processing Rules)

1. **멀티샷 수신 등록 (`SUBMIT_MULTISHOT`)**:
   - `fd`에 대해 상태를 `"ARMED"`로 등록하고 `requests_armed += 1`.
2. **소켓 데이터 유입 (`SOCKET_DATA`)**:
   - `fd`에 활성(`"ARMED"`) 상태인 멀티샷 요청이 없으면 패킷은 무시됩니다.
   - **연결 종료 (EOF)**: `data_len == 0`인 경우:
     - `res = 0`, `flags = 0`, `multishot_active = false`인 CQE를 발행하고 멀티샷 등록을 해제합니다. (`requests_terminated_eof += 1`)
   - **버퍼 고갈 (ENOBUFS)**: 해당 버퍼 그룹(`bgid`)에 남은 버퍼가 없는 경우:
     - `res = -105` (`-ENOBUFS`), `flags = 0`, `multishot_active = false`인 CQE를 발행하고 멀티샷 등록을 해제합니다. (`enobufs_starvation_count += 1`)
   - **정상 수신**: 버퍼 링에서 버퍼를 꺼내어 `transferred = min(data_len, buf.length)` 바이트 복사:
     - `res = transferred`, `flags = IORING_CQE_F_MORE | IORING_CQE_F_BUFFER` (값 3), `buffer_id = buf.bid`, `multishot_active = true`인 CQE를 발행합니다.
     - `multishot_recvs_completed += 1`, `total_bytes_received += transferred`.
3. **버퍼 보충 (`REPLENISH`)**:
   - 지정된 버퍼 그룹(`bgid`)의 버퍼 링 끝에 새 버퍼(`bid`, `len`)를 추가합니다.
4. **요청 취소 (`CANCEL`)**:
   - 해당 `user_data`를 가진 멀티샷 요청이 등록되어 있다면 해제하고 `res = -125` (`-ECANCELED`), `flags = 0`, `multishot_active = false`인 CQE를 발행합니다. (`requests_cancelled += 1`)
5. **진단 및 상태 판정**:
   - `enobufs_starvation_count > 0`: `"BUFFER_RING_STARVATION_DETECTED"`, 이상 항목에 `"BUFFER_RING_EXHAUSTION_DISARM"` 추가.
   - 정상: `"OPTIMAL_ZERO_ALLOC_MULTISHOT"`.

### 출력 형식 (Standard Output)
단일 행의 표준 JSON 형식으로 출력합니다.
```json
{
  "metrics": {
    "multishot_recvs_completed": 1,
    "total_bytes_received": 1460,
    "enobufs_starvation_count": 0,
    "requests_armed": 1,
    "requests_terminated_eof": 0,
    "requests_cancelled": 0
  },
  "buf_group_status": {
    "bgid_1": {
      "available_buffers": 1,
      "head_buffer_id": 102
    }
  },
  "diagnostics": {
    "status": "OPTIMAL_ZERO_ALLOC_MULTISHOT",
    "anomalies": []
  },
  "cqe_sample": [
    {
      "time_us": 10.0,
      "user_data": 1001,
      "res": 1460,
      "flags": 3,
      "buffer_id": 101,
      "multishot_active": true
    }
  ]
}
```

---

## 3. 제약 사항 (Constraints)
- `events` 길이: $1 \le N \le 10,000$
- 버퍼 그룹당 버퍼 수: $1 \le B \le 1,024$
- `sq_depth` $\le 4096$, `cq_depth` $\le 8192$
- Python 3 표준 라이브러리만 사용합니다 (`json`, `sys`, `collections`).
