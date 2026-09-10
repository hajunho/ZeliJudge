# 문제 459: Linux Kernel VHost-VSOCK 크레딧 기반 흐름 제어 및 제로카피 통신 엔진

## 문제 설명

클라우드 네이티브 마이크로VM(AWS Firecracker, Kata Containers, Cloud Hypervisor, Android microdroid) 환경에서 호스트와 게스트 가상 머신 간의 고속 프로세스 간 통신(IPC)은 필수적입니다.

전통적인 가상 이더넷 브리지(TAP + virtio-net) 방식은 패킷 하나를 전달할 때마다 호스트와 게스트의 전체 TCP/IP 프로토콜 스택(체크섬 계산, ARP 테이블 조회, 라우팅 테이블 조회, 방화벽 iptables 규칙 평가)을 거치므로 막대한 CPU 오버헤드와 지연 시간(Latency)을 유발합니다.

이를 해결하기 위해 리눅스 커널은 소켓 계층에서 직접 가상화 큐(Virtqueue)를 통과하는 **`AF_VSOCK` 및 VHost-VSOCK 드라이버**(`drivers/vhost/vsock.c`, `net/vmw_vsock/virtio_transport.c`, `include/uapi/linux/vm_sockets.h`)를 구현하였습니다:

```
+-----------------------------------------------------------------------------------------+
|                  VHost-VSOCK Credit-Based Flow Control Architecture                     |
+-----------------------------------------------------------------------------------------+

 [Guest MicroVM: CID 3]                                    [Host Hypervisor: CID 2]
      |                                                               |
      | 1. Connect(dst: 2:8080, buf_alloc: 16KB)                      |
      +-------------------------------------------------------------->| Listen(2:8080, buf_alloc: 16KB)
      | <--- CONNECTED (Exchange buf_alloc: 16KB) --------------------+
      |                                                               |
      | 2. Send 10KB (tx_cnt = 10KB, in_flight = 10KB)                |
      +-------------------------------------------------------------->| Enqueue rx_queue (10KB)
      |    Credits remaining = 16KB - 10KB = 6KB                      |
      |                                                               |
      | 3. Send 10KB (Requested 10KB > Credits 6KB!)                  |
      |    Blocked! Return EAGAIN_CREDIT_EXHAUSTED!                   |
      |                                                               |
      |                                                               | 4. Recv 10KB from rx_queue
      |                                                               |    fwd_cnt += 10KB
      | 5. CREDIT_UPDATE (fwd_cnt = 10KB, buf_alloc = 16KB)           |
      |<--------------------------------------------------------------+
      |    Credits replenished = 16KB - (10KB - 10KB) = 16KB!         |
      |                                                               |
      | 6. Retry Send 10KB -> SUCCESS!                                |
      +-------------------------------------------------------------->|
      v                                                               v
```

### 핵심 주소 및 프로토콜 체계
1. **VSOCK 주소 체계**:
   - `CID` (Context ID): 32비트 정수 (호스트는 `CID = 2`, 게스트는 `CID = 3, 4, ...`).
   - `Port`: 32비트 포트 번호.
2. **크레딧 기반 흐름 제어 (Credit-Based Flow Control)**:
   - 양 끝단은 상대방의 수신 버퍼 할당량(`peer_buf_alloc`)과 상대방이 실제로 애플리케이션으로 소비(forward)한 누적 바이트 수(`peer_fwd_cnt`)를 추적합니다.
   - 송신자 측 가용 크레딧(Available Credits):
     $$	ext{in\_flight} = 	ext{tx\_cnt} - 	ext{peer\_fwd\_cnt}$$
     $$	ext{available\_credits} = 	ext{peer\_buf\_alloc} - 	ext{in\_flight}$$
   - 송신하려는 데이터 길이가 가용 크레딧을 초과하면 패킷 전송을 즉시 중단하고 `EAGAIN_CREDIT_EXHAUSTED`를 반환하며 `stats.flow_control_blocks`를 증가시킵니다.
3. **크레딧 업데이트 (`CREDIT_UPDATE`)**:
   - 수신자 애플리케이션이 `recv_data`를 호출하여 수신 큐에서 데이터를 인출하면, 누적 전진 카운터(`fwd_cnt`)를 증가시키고 송신자에게 크레딧 갱신 패킷을 전달하여 가용 크레딧을 즉시 복원합니다.
4. **연결 상태 머신**:
   - `LISTEN`: 지정된 `(cid, port)`에서 연결 요청 대기.
   - `CONNECT`: 수신 대기 중인 서버와 가상 연결 수립 (초기 크레딧 교환).
   - `CLOSE`: 소켓 및 피어 소켓을 `CLOSED`로 전이.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:
- `config`:
  - `host_cid`: int (기본값: 2)
  - `default_buf_alloc`: int (기본값: 65536 바이트)
- `operations`: 일련의 연산 배열.

지원되는 연산:
1. `{"op": "LISTEN", "cid": int, "port": int, "buf_alloc": int|null}`
   - 지정 포트에서 리슨 상태를 개시합니다. 주소 중복 시 `EADDRINUSE`.
2. `{"op": "CONNECT", "src_cid": int, "src_port": int, "dst_cid": int, "dst_port": int, "buf_alloc": int|null}`
   - 목적지 소켓으로 연결을 수립합니다. 미존재 시 `ECONNREFUSED`.
3. `{"op": "SEND_DATA", "src_cid": int, "src_port": int, "data_len": int}`
   - 상대방 소켓으로 데이터를 전송합니다.
   - 연결 미수립 시 `ENOTCONN`, 상대 소켓 종료 시 `ECONNRESET`.
   - 크레딧 부족 시 `EAGAIN_CREDIT_EXHAUSTED` 반환 및 `flow_control_blocks` 카운트.
4. `{"op": "RECV_DATA", "cid": int, "port": int, "max_bytes": int|null}`
   - 수신 큐에서 데이터를 읽어내고 상대방 피어에 크레딧 업데이트를 통지합니다.
   - 수신 큐가 비어있으면 `EAGAIN_NO_DATA`.
5. `{"op": "CLOSE", "cid": int, "port": int}`
   - 연결을 종료합니다.
6. `{"op": "QUERY_VSOCK_STATE"}`
   - 모든 소켓의 상태, 카운터, 통계(`stats`)를 반환합니다.

---

## 출력 형식

표준 출력(stdout)으로 각 연산의 결과를 담은 JSON을 한 줄(compact)로 출력합니다:
```json
{"results": [...]}
```
