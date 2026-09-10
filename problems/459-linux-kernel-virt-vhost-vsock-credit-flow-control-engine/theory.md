# 이론: Linux Kernel VHost-VSOCK 크레딧 기반 흐름 제어 및 마이크로VM 초저지연 통신 아키텍처

## 1. 전통적인 가상 이더넷의 한계와 `AF_VSOCK`의 출현

클라우드 컴퓨팅 환경에서 호스트 하이퍼바이저와 게스트 가상 머신(VM) 간의 통신은 오랫동안 가상 NIC(virtio-net)과 가상 이더넷 브리지(Linux Bridge, Open vSwitch)를 통해 이루어졌습니다.

그러나 서버리스 컨테이너 및 경량 마이크로VM(AWS Firecracker, Kata Containers, gVisor)이 대두되면서 고전적 네트워크 스택은 극심한 병목으로 작용했습니다:
1. **불필요한 계층 오버헤드**:
   - 동일한 물리 서버의 호스트와 게스트 메모리 간 데이터 전송임에도 불구하고, 2계층(Ethernet 프레임 헤더, MAC 주소 학습), 3계층(IP 라우팅, 서브넷 계산, TTL 감소, IP 체크섬), 4계층(TCP 3-way 핸드셰이크, 시퀀스 번호 계산, 슬라이딩 윈도우)이 모두 동작합니다.
2. **IP 주소 관리 및 네임스페이스 고갈**:
   - 밀리초 단위로 수만 개의 마이크로VM이 생성/소멸할 때 서브넷 IP 고갈과 DHCP/ARP 트래픽 폭풍이 발생합니다.

리눅스 커널 3.9에 도입된 **`AF_VSOCK` (Virtual Sockets)**는 TCP/IP 계층 전체를 완전히 우회하여, 하이퍼바이저의 공유 메모리 큐(Virtqueue) 위에서 소켓 API(`socket(AF_VSOCK, SOCK_STREAM, 0)`)를 통해 직접 1:1 통신할 수 있는 커널 서브시스템입니다 (`drivers/vhost/vsock.c`, `net/vmw_vsock/virtio_transport.c`).

---

## 2. VHost-VSOCK 주소 체계와 패킷 헤더 구조

VSOCK은 IP 주소 대신 32비트 정수인 **Context ID (CID)**를 사용합니다:
- `VMADDR_CID_HYPERVISOR (0)`: 하이퍼바이저 예약 주소.
- `VMADDR_CID_LOCAL (1)`: 로컬 루프백.
- `VMADDR_CID_HOST (2)`: KVM 호스트 OS.
- `CID >= 3`: 게스트 가상 머신에 동적으로 할당되는 고유 ID.

가상 큐를 통해 송수신되는 모든 패킷은 `struct virtio_vsock_hdr` 헤더를 포함합니다:
```c
struct virtio_vsock_hdr {
    __le64 src_cid;
    __le64 dst_cid;
    __le32 src_port;
    __le32 dst_port;
    __le32 len;          /* 페이로드 바이트 길이 */
    __le16 type;         /* VIRTIO_VSOCK_TYPE_STREAM (1) */
    __le16 op;           /* 패킷 연산 코드 */
    __le32 flags;
    __le32 buf_alloc;    /* 수신측 할당 버퍼 크기 (바이트) */
    __le32 fwd_cnt;      /* 수신측이 소비한 누적 바이트 수 */
} __attribute__((packed));
```

---

## 3. 크레딧 기반 흐름 제어 (Credit-Based Flow Control)

VSOCK은 TCP의 슬라이딩 윈도우와 유사하지만 패킷 손실이 없는 가상 채널의 특성을 활용하여 **정밀한 크레딧 기반 흐름 제어**를 수행합니다:

1. **상태 추적 파라미터**:
   - 송신자 측:
     - `tx_cnt`: 송신자가 지금까지 송출한 총 누적 바이트 수.
     - `peer_fwd_cnt`: 수신자가 실제로 수신 버퍼에서 애플리케이션으로 꺼내간 총 누적 바이트 수.
     - `peer_buf_alloc`: 수신자가 광고한 최대 수신 윈도우 크기.
2. **가용 크레딧(Available Credit) 수학적 모델**:
   $$	ext{in\_flight} = 	ext{tx\_cnt} - 	ext{peer\_fwd\_cnt}$$
   $$	ext{free\_space} = 	ext{peer\_buf\_alloc} - 	ext{in\_flight}$$
3. **흐름 제어 트리거**:
   - 송신하려는 데이터 길이가 $	ext{free\_space}$보다 크면, 송신자는 패킷을 Virtqueue에 넣지 않고 대기 상태(`EAGAIN`)로 전환됩니다. 이는 수신 측 Virtqueue 버퍼의 메모리 오버플로를 100% 원천 차단합니다.
   - 수신자 프로세스가 `read()`/`recv()`를 수행하면, 커널은 `fwd_cnt += bytes`를 갱신하고 즉시 `VIRTIO_VSOCK_OP_CREDIT_UPDATE` 제어 패킷을 반대편으로 전송합니다.
   - 송신자는 새로운 `peer_fwd_cnt`를 수신하는 순간 $	ext{free\_space}$가 확장되어 막혀 있던 쓰기 작업이 즉각 깨어납니다.

---

## 4. 성능적 이점 및 실무 적용 사례

1. **제로카피 데이터 전송 (Zero-Copy Datapath)**:
   - 게스트 물리 메모리(GPA)는 QEMU/하이퍼바이저의 가상 메모리(HVA)로 1:1 mmap 매핑되어 있으므로, VHost 커널 모듈은 메모리 복사 없이 포인터 스왑만으로 데이터를 교환할 수 있습니다.
2. **AWS Firecracker 및 서버리스 샌드박스**:
   - AWS Lambda의 내부 컨테이너 런타임(Firecracker microVM)은 게스트 내부의 에이전트와 호스트 컨트롤 플레인 간의 모든 API 호출(함수 호출 페이로드 전달, 메트릭 수집)에 VSOCK을 전적으로 사용합니다.
   - 기존 가상 이더넷 대비 메모리 점유율을 90% 이상 절감하고, 콜드 스타트 지연 시간을 5ms 미만으로 단축시켰습니다.
