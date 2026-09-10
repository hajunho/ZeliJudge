# Problem #443: 리눅스 커널 가상화 및 초고속 I/O: drivers/vhost/net.c vhost-net 제로-카피(Zero-Copy TX) 및 ubuf_info 비동기 완료 콜백 엔진

## 🌟 개요 (Executive Summary)
KVM 하이퍼바이저 기반 클라우드 가상 머신(게스트 OS)에서 초고속 네트워크(10GbE / 40GbE / 100GbE) 패킷을 송신할 때, 호스트 커널의 백엔드 처리 모듈인 `vhost-net`(`drivers/vhost/net.c`, `drivers/vhost/vhost.c`)은 게스트의 VirtIO 링 버퍼 디스크립터를 읽어 호스트 네트워크 스택(`sk_buff`)으로 전달합니다.
전통적인 복사 모드(Copy Mode)에서는 게스트 물리 메모리(GPA)의 패킷 데이터를 호스트 커널 공간의 `skb` 버퍼로 매번 메모리 복사(`copy_from_user` / `memcpy`)해야 했습니다. 40Gbps~100Gbps 트래픽 상황에서 이 메모리 복사 오버헤드는 호스트 CPU 코어 4~8개를 100% 점유하며 심각한 캐시 오염(Cache Pollution)을 유발합니다.

리눅스 커널은 이를 제거하기 위해 **vhost-net 제로-카피 송신(Zero-Copy TX / ZCOPY_TX)** 기술을 도입하였습니다:
- **게스트 메모리 직접 핀(Pin) 매핑**: 게스트의 물리 메모리 페이지를 호스트 `sk_buff`의 프래그먼트 배열(`skb_shinfo(skb)->frags`)에 복사 없이 직접 참조(`get_user_pages_fast`)시킵니다.
- **물리 하드웨어 DMA 레이스 방어 및 `ubuf_info` 콜백**:
  - 게스트 OS는 패킷을 보낸 직후 해당 버퍼를 재사용하거나 해제하려 할 수 있습니다. 하지만 호스트 물리 NIC이 PCIe DMA로 패킷을 전송하는 도중에 게스트가 메모리를 덮어쓰면 심각한 패킷 변조 및 충돌이 발생합니다.
  - `vhost-net`은 각 제로-카피 skb에 참조 카운트가 연결된 `struct ubuf_info` 구조체를 부착하고 완료 콜백 함수(`vhost_zerocopy_callback()`)를 등록합니다.
  - 물리 NIC이 패킷 송신 DMA를 완수하여 `skb_release_data()`를 호출할 때 콜백이 트리거되어, 비로소 게스트 메모리가 해제되었음을 확인하고 게스트 VirtIO 가용 링(`vring.used`)에 등록한 뒤 게스트에게 비동기 통지(Kick)합니다.
- **적응형 임계치 및 인-플라이트 상한 폴백 (Adaptive Fallback)**:
  - **크기 임계치 (`zcopy_min_threshold`)**: 512바이트 미만의 소형 패킷은 페이지 매핑 및 unpin 오버헤드가 메모리 복사 비용보다 크므로 자동으로 복사 모드(`COPY_THRESHOLD`)로 처리하여 즉시 반환합니다.
  - **동시성 상한 (`max_zcopy_inflight`)**: NIC DMA 대기로 인해 게스트 VirtIO 링 버퍼가 고갈(Buffer Starvation)되는 것을 방지하기 위해, 현재 진행 중인 제로-카피 버퍼 수가 상한선에 도달하면 신규 패킷을 안전하게 복사 모드(`COPY_FALLBACK`)로 전환합니다.

본 문제에서는 리눅스 커널 `drivers/vhost/net.c`의 vhost-net 제로-카피 송신, `ubuf_info` 비동기 완료 콜백, 인-플라이트 상한 폴백 및 VirtIO 링 버퍼 플러시 엔진을 시뮬레이션합니다.

---

## 🏗️ 아키텍처 및 시스템 흐름도 (System Architecture)

```
        [ Guest VM: virtqueue_add_outbuf() ]
                         │
                         ▼
        [ vhost-net: handle_tx_zerocopy() ]
                         │
              len < zcopy_min_threshold?
              ┌──────────┴──────────┐
             Yes                    No
              │                     │
              ▼                     ▼
    [ COPY_THRESHOLD ]     inflight >= max_zcopy_inflight?
    Host memcpy() to skb          ┌─────────┴─────────┐
    Return to used_ring          Yes                  No
    status = IMMEDIATE            │                   │
                                  ▼                   ▼
                         [ COPY_FALLBACK ]     [ ZERO_COPY ]
                         Host memcpy() to skb  Direct page pinning
                         Return to used_ring   inflight_zcopy++
                         status = FALLBACK     Attach ubuf_info
                                               Hold in-flight!
                                                      │
 ─────────────────────────────────────────────────────┼──────
      Physical Host NIC Hardware DMA Execution        │
 ─────────────────────────────────────────────────────┼──────
                                                      │
                                    [ NIC_DMA_COMPLETE ]
                                    skb_release_data() calls
                                    vhost_zerocopy_callback()
                                    inflight_zcopy--
                                    cycles_saved calculated
                                    Add desc to used_ring!
                                                      │
                                                      ▼
                                            [ FLUSH_USED_RING ]
                                            virtqueue_kick() to Guest
```

---

## ⚙️ I/O 데이터 규격 (Input/Output Specifications)

### 1. 입력 JSON 구조
```json
{
  "config": {
    "max_zcopy_inflight": 4,
    "zcopy_min_threshold": 512,
    "copy_cost_cycles": 0.5
  },
  "trace": [
    {"op": "SUBMIT_GUEST_TX", "tx_id": "TX_1", "desc_idx": 0, "len": 256},
    {"op": "SUBMIT_GUEST_TX", "tx_id": "TX_2", "desc_idx": 1, "len": 1500},
    {"op": "NIC_DMA_COMPLETE", "tx_id": "TX_2"},
    {"op": "FLUSH_USED_RING"},
    {"op": "GET_STATS"}
  ]
}
```

### 2. 필드 정의
- `config`:
  - `max_zcopy_inflight` (int, default=4): 동시 진행 가능한 최대 제로-카피 버퍼 수.
  - `zcopy_min_threshold` (int, default=512): 제로-카피 적용 최소 패킷 크기 (바이트).
  - `copy_cost_cycles` (float, default=0.5): 1바이트 복사 시 소요되는 호스트 CPU 사이클 비용.
- `trace` 명령어:
  1. `SUBMIT_GUEST_TX`:
     - `tx_id` (str): 전송 식별자.
     - `desc_idx` (int): 게스트 VirtIO 디스크립터 인덱스.
     - `gpa` (int, optional): 게스트 물리 주소.
     - `len` (int): 패킷 크기 (바이트).
  2. `NIC_DMA_COMPLETE`:
     - `tx_id` (str): 물리 NIC 송신 DMA를 완료한 전송 식별자. `ubuf_info` 콜백 트리거.
  3. `FLUSH_USED_RING`:
     - 누적된 사용 완료 디스크립터들을 게스트 VirtIO 큐로 일괄 통지(Kick) 및 반환.
  4. `GET_STATS`:
     - 현재 누적 전송량, 절감된 CPU 사이클, 킥 횟수 등 통계 조회.

### 3. 출력 JSON 구조
```json
{
  "events": [
    {
      "op": "SUBMIT_GUEST_TX",
      "tx_id": "TX_1",
      "desc_idx": 0,
      "mode": "COPY_THRESHOLD",
      "len": 256,
      "status": "TX_COPIED_IMMEDIATE_RETURN",
      "inflight_zcopy": 0,
      "used_ring_pending": 1
    },
    ...
  ],
  "summary": {
    "total_tx_packets": 2,
    "zcopy_packets": 1,
    "copied_packets": 1,
    "zcopy_fallback_count": 0,
    "total_bytes_transmitted": 1756,
    "bytes_copied": 256,
    "bytes_zerocopy": 1500,
    "host_cpu_cycles_saved": 750,
    "virtqueue_kicks": 1
  }
}
```
