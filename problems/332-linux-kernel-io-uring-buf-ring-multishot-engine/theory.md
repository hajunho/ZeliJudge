# Linux Kernel io_uring Provided Buffer Ring (io_uring_buf_ring) & Zero-Copy Network Architecture 심층 이론

## 1. 개요: 고성능 네트워크 I/O의 버퍼 관리 혁신

전통적인 리눅스 네트워크 서버 아키텍처(`epoll` + Non-blocking I/O)는 C10K를 넘어 C1000K(100만 동시 연결) 시대로 접어들면서 심각한 병목에 직면했습니다:
1. **버퍼 메모리 블로트(Buffer Bloat)**:
   - 소켓에 언제 데이터가 도착할지 알 수 없으므로, 모든 연결마다 사전에 고정 크기 수신 버퍼(예: 64KB)를 할당해 두어야 합니다. 10만 연결 시 유휴 상태에서도 최소 6.4GB의 RAM이 고정됩니다.
2. **시스템 콜 및 컨텍스트 스위치 오버헤드**:
   - `epoll_wait()`로 이벤트 통지를 받은 후, 각 소켓마다 `read()` 또는 `recv()` 시스템 콜을 개별 호출해야 하므로 CPU 사이클의 상당 부분이 커널-유저 공간 전환에 소모됩니다.
3. **초기 io_uring의 한계 (`IORING_OP_PROVIDE_BUFFERS`)**:
   - io_uring 초기 버전에서는 SQE를 통해 버퍼를 커널에 등록했으나, 버퍼를 채울 때마다 SQE를 제출하고 커널 내부 락(`ctx->completion_lock`)을 잡아야 하여 확장성에 제약이 있었습니다.

리눅스 커널 5.19에서 도입된 **Provided Buffer Ring (`io_uring_buf_ring`)**과 **Multishot Recv (`IORING_RECV_MULTISHOT`)**, 6.0의 **Zero-Copy Send (`IORING_OP_SEND_ZC`)**는 이 모든 문제를 완벽히 해결했습니다.

---

## 2. io_uring_buf_ring의 락리스(Lockless) 공유 메모리 구조

`io_uring_buf_ring`은 유저 공간과 커널 공간이 1:1로 mmap하여 공유하는 링 버퍼입니다:

```c
struct io_uring_buf {
    __u64 addr;
    __u32 len;
    __u16 bid;
    __u16 resv;
};

struct io_uring_buf_ring {
    union {
        struct {
            __u64 resv1;
            __u32 resv2;
            __u16 resv3;
            __u16 tail;
        };
        struct io_uring_buf bufs[0];
    };
};
```

### 락리스 전진 메커니즘
- **유저 공간 (생산자)**:
  - 메모리 풀에서 가용한 버퍼 주소(`addr`), 길이(`len`), 버퍼 식별자(`bid`)를 `bufs[tail & mask]`에 씁니다.
  - 메모리 배리어(`smp_store_release`)와 함께 `tail`을 1 증가시킵니다:
    ```c
    io_uring_buf_ring_add(br, addr, len, bid, mask, 0);
    io_uring_buf_ring_advance(br, 1);
    ```
- **커널 공간 (소비자)**:
  - 네트워크 패킷이 도착했을 때만 원자적으로 `head` 위치의 버퍼를 읽고 `head++`를 수행합니다.
  - 별도의 시스템 콜 없이 공유 메모리 포인터 조작만으로 완벽한 제로-시스템콜 버퍼 할당이 이루어집니다.

---

## 3. 멀티샷 수신 (IORING_RECV_MULTISHOT) & CQE 플래그

단일 SQE에 `IORING_RECV_MULTISHOT` 플래그를 지정하면, 해당 SQE는 커널 내부의 소켓 대기 큐에 상주하며 다음 동작을 수행합니다:

1. **패킷 도착 시**:
   - `io_uring_buf_ring`에서 버퍼 1개를 꺼내 skb의 페이로드를 복사합니다.
   - CQE를 생성하여 CQ 링에 푸시합니다:
     - `cqe->res`: 실제 수신된 바이트 수.
     - `cqe->flags`:
       - `IORING_CQE_F_BUFFER`: 버퍼 링에서 버퍼가 선택되었음을 알림.
       - `(bid << IORING_CQE_BUFFER_SHIFT)`: 사용된 버퍼의 고유 ID(상위 16비트).
       - `IORING_CQE_F_MORE`: 이 SQE에서 후속 CQE가 계속 발생할 것임을 알림.
2. **연결 종료(EOF) 또는 에러 발생 시**:
   - 마지막 패킷 수신 또는 연결 종료 시, 커널은 `IORING_CQE_F_MORE` 플래그를 끄고 최종 CQE를 방출한 뒤 SQE를 정리합니다.
3. **버퍼 기아 방어 (Buffer Starvation Defense)**:
   - 커널이 패킷을 수신하려 했으나 `buf_ring`에 버퍼가 남아있지 않은 경우(`head == tail`), 즉시 `res = -ENOBUFS (-105)` 오류 CQE를 방출하고 멀티샷 요청을 즉시 중단합니다.

---

## 4. 제로카피 송신 (IORING_OP_SEND_ZC) 2단계 알림 구조

전통적인 `send()`는 유저 공간 버퍼를 커널 공간 skb로 복사(`copy_from_user`)한 후 NIC 드라이버로 넘깁니다. 이는 기가바이트 급 전송에서 심각한 CPU 캐시 및 메모리 대역폭 낭비를 초래합니다.

`IORING_OP_SEND_ZC`는 유저 공간 버퍼를 커널 페이지에 고정(Pin)하거나 등록된 고정 버퍼(`IORING_REGISTER_BUFFERS`)를 활용하여 DMA 컨트롤러가 직접 DRAM에서 읽어가도록 합니다:

```
[Phase 1: Send Request Queued]
User submits IORING_OP_SEND_ZC
  --> Kernel pins buffer, builds skb with zero-copy frag
  --> Emits CQE 1: res = bytes_sent, flags = IORING_CQE_F_MORE
      (Data is queued in network stack, but memory MUST NOT be modified!)

[Phase 2: Hardware DMA Completion]
NIC transmits packet onto wire -> NIC raises TX completion IRQ
  --> skb_release_data() frees skb reference
  --> io_uring emits Notification CQE 2: res = 0, flags = IORING_CQE_F_NOTIF
      (User-space can now safely reuse or free the send buffer!)
```

이 2단계 완료 프로토콜 덕분에 유저 공간은 하드웨어가 언제 메모리 읽기를 마쳤는지 마이크로초 단위로 정확히 인지할 수 있습니다.

---

## 5. 커널 소스 코드 매핑

- `io_uring/kbuf.c`:
  - `io_provide_buffers()`: 버퍼 링 등록 및 메모리 맵핑.
  - `io_ring_buffer_select()`: 커널 패킷 수신 시 `buf_ring`에서 버퍼 자동 선출.
- `io_uring/net.c`:
  - `io_recvzc()`, `io_recv()`, `io_recv_multishot()`: 멀티샷 수신 및 CQE 방출 로직.
  - `io_send_zc()`: 제로카피 네트워크 전송 및 2단계 알림 처리.
- `include/uapi/linux/io_uring.h`:
  - `struct io_uring_buf`, `struct io_uring_buf_ring`, `IORING_RECV_MULTISHOT`, `IORING_CQE_F_BUFFER`, `IORING_CQE_F_MORE`, `IORING_CQE_F_NOTIF` 매크로 정의.
