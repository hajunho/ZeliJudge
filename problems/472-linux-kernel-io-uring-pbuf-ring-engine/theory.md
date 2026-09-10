# 리눅스 커널 io_uring 등록 버퍼 링(PBUF Ring) 및 제로카피 수신 이론

## 1. 전통적인 소켓 수신 모델의 한계

전통적인 Linux 네트워크 프로그래밍 모델(epoll + non-blocking socket)은 다음과 같은 근본적인 성능 병목을 안고 있습니다:
1. **버퍼 선할당의 메모리 낭비**: 수십만 개의 TCP 연결이 유지될 때, 각 연결마다 64KB 수신 버퍼를 미리 할당하면 수십 GB의 메모리가 소모됩니다.
2. **시스템 콜 컨텍스트 스위칭**: `epoll_wait`로 읽기 가능 이벤트를 감지한 뒤, 각 소켓마다 `read()` 또는 `recv()` 시스템 콜을 개별 호출해야 하므로 모드 전환(Ring 3 -> Ring 0 -> Ring 3) 오버헤드가 누적됩니다.
3. **데이터 복사(Data Copy)**: 커널 sk_buff에서 유저 공간 버퍼로 메모리 복사가 매 패킷마다 일어납니다.

---

## 2. io_uring 등록 버퍼 링 (`IORING_REGISTER_PBUF_RING`)

Linux 5.19에 도입된 **Provided Buffer Ring**은 커널과 유저 공간이 공유하는 단일 원형 버퍼 링을 통해 버퍼 공급의 모든 시스템 콜 오버헤드를 제로(0)로 만들었습니다.

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
            __u64 _pad;
            __u32 _pad2;
            __u16 _pad3;
            __u16 tail;
        };
        struct io_uring_buf bufs[0];
    };
};
```

### 2.1 동작 원리
- **유저 공간 (생산자)**:
  - `tail` 위치에 `io_uring_buf` 정보를 기입하고, `smp_store_release` 메모리 배리어를 통해 `tail` 인덱스를 전진시킵니다 (`io_uring_buf_ring_advance`).
  - 커널에 별도의 시스템 콜을 호출할 필요가 없습니다.
- **커널 공간 (소비자)**:
  - NIC 하드웨어 인터럽트 또는 NAPI 폴링 루프에서 패킷이 소켓 수신 큐에 도착하면, 커널은 `bgid`에 매핑된 버퍼 링의 `head` 위치에서 버퍼를 인출합니다.
  - 버퍼를 선택(`bid`)하고 즉시 패킷 데이터를 버퍼 메모리 주소(`addr`)로 DMA 또는 고속 복사합니다.
  - `head`를 1 증가시키고 CQE의 `flags`에 `(bid << 16) | IORING_CQE_F_BUFFER`를 설정하여 사용자에게 통지합니다.

---

## 3. 멀티샷(Multishot) 수신과 버퍼 고갈 시맨틱

### 3.1 IORING_RECV_MULTISHOT
단 한 번의 `io_uring_prep_recv_multishot()` 호출로 소켓을 감시 상태에 둡니다:
- 커널은 소켓에 데이터가 도착할 때마다 링에서 버퍼를 하나씩 꺼내 CQE를 계속 생성합니다 (`IORING_CQE_F_MORE` 플래그 유지).
- 패킷 수신마다 매번 SQE를 다시 만들어 제출할 필요가 없으므로 SQ 링 락 경합 및 큐 관리 비용이 완전히 소거됩니다.

### 3.2 ENOBUFS 및 백프레셔(Backpressure)
- 만약 유저 공간의 버퍼 처리 및 반환 속도가 네트워크 인바운드 트래픽 속도보다 느려지면 `tail == head`가 되어 링이 고갈됩니다.
- 이때 커널은 즉시 `-ENOBUFS`(-105) 에러 CQE를 발행하고, 멀티샷 수신을 즉각 종료(Cancel)합니다.
- 이는 무제한 메모리 누수를 원천 차단하는 커널 레벨의 백프레셔 메커니즘으로 동작하며, 유저는 버퍼를 충원한 후 멀티샷 SQE를 재등록해야 합니다.

---

## 4. 제로카피 및 하드웨어 가속과의 결합

최신 커널(Linux 6.x 이상)에서는 등록 버퍼 링이 **NIC 제로카피 RX(Zero-Copy RX)** 및 **Page Pool**과 결합되어, NIC 하드웨어가 패킷 헤더와 페이로드를 분리한 뒤 페이로드를 유저 공간이 제공한 물리 페이지에 직접 DMA 기록하는 초고성능 파이프라인을 완성합니다.
이 기술은 Envoy, NGINX, Cloudflare 고성능 프록시 및 대규모 금융 거래소의 핵심 통신 엔진으로 채택되고 있습니다.
