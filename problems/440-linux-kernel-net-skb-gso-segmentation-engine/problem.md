# Problem #440: 리눅스 커널 초고속 네트워킹: net/core/skbuff.c & net/ipv4/tcp_output.c GSO/TSO 세그멘테이션 오프로드 및 skb_segment 프래그먼트 슬라이싱 엔진

## 🌟 개요 (Executive Summary)
현대 100GbE / 200GbE / 400GbE 데이터센터 초고속 네트워킹 환경에서, TCP/IP 프로토콜 스택이 64KB 크기의 대용량 데이터 버스트를 전송할 때 표준 이더넷 MTU(1500바이트) 크기의 소형 패킷으로 일일이 분할하여 처리한다면:
1. 64KB 메시지 하나당 약 45개의 독립적인 소켓 버퍼(`struct sk_buff`)를 동적 할당(`kmem_cache_alloc`)해야 합니다.
2. 45개의 패킷 각각에 대해 커널 경로 조회(FIB Routing), 넷필터/iptables 방화벽 검사, TCP/IP 헤더 생성, 소프트웨어 체크섬 계산을 반복 수행하느라 CPU 사용률이 100%에 도달하여 네트워크 전송 속도가 10~15Gbps 수준에서 물리적으로 병목에 걸립니다.

리눅스 커널은 이를 극복하기 위해 **GSO (Generic Segmentation Offload) 및 TSO (TCP Segmentation Offload)** 기법을 도입하였습니다:
- **단일 거대 슈퍼-패킷(Super-Packet) 파이프라인**: 애플리케이션 계층에서 전송된 최대 64KB의 페이로드를 단 하나의 대형 `sk_buff`(선형 헤더 버퍼 + 최대 17개의 페이지 프래그먼트 배열 `skb_shinfo(skb)->frags`)로 유지한 채, 커널 네트워킹 계층 전체를 단 한 번만 통과시킵니다.
- **하드웨어 TSO (`NETIF_F_TSO`) 패스스루**: 물리 NIC ASIC이 하드웨어 세그멘테이션을 지원하는 경우, 거대 skb를 분할하지 않고 NIC의 송신 DMA 링 버퍼에 직통 전달하여 0-CPU-오버헤드로 회선 패킷 분할을 하드웨어에 위임합니다.
- **소프트웨어 GSO 엔진 (`skb_segment()` in `net/core/skbuff.c`)**:
  - NIC 하드웨어가 TSO를 지원하지 못하거나(예: 가상 veth 페어, 터널링 인터페이스, 브리지 장치), 세그멘테이션 오프로드가 불가능한 환경에서는 디바이스 드라이버 전송 직전 `skb_segment()`가 소프트웨어 분할을 수행합니다.
  - **정밀한 슬라이싱(Scatter-Gather Slicing)**: 선형 메모리와 물리 페이지 프래그먼트 경계를 정확히 추적하며 MSS(Maximum Segment Size, 기본 1448~1460바이트) 단위로 자르고, 페이지 메모리를 물리 복사하지 않고 페이지 참조 카운트만 증가시켜 제로-카피로 슬라이싱합니다.
  - **프로토콜 불변식 갱신**:
    - **TCP 시퀀스 번호**: $k$번째 세그먼트에 대해 $SEQ_k = SEQ_0 + \sum_{i=0}^{k-1} \text{len}_i$를 정밀 산출합니다.
    - **IP Identification**: IPv4 패킷 식별자 번호를 $IP\_ID_k = (IP\_ID_0 + k) \pmod{65536}$으로 증가시킵니다.
    - **TCP 플래그 격리**: 원본 패킷의 `ACK` 플래그는 모든 분할 세그먼트에 복제되지만, 버퍼 플러시를 의미하는 `PSH` 및 연결 종료를 의미하는 `FIN` 플래그는 **오직 마지막(최종) 세그먼트에만 보존**되고 중간 세그먼트에서는 엄격히 마스킹(제거)됩니다.

본 문제에서는 리눅스 커널 `net/core/skbuff.c` 및 `net/ipv4/tcp_output.c`의 GSO 슈퍼-패킷 조립, 하드웨어 TSO 패스스루, 소프트웨어 `skb_segment()` 프래그먼트 슬라이싱, 시퀀스/플래그 조작 엔진을 시뮬레이션합니다.

---

## 🏗️ 아키텍처 및 시스템 흐름도 (System Architecture)

```
       [ TCP Stack: tcp_write_xmit() ]
                      │
   Assemble Giant Super-Packet (up to 64KB)
   gso_size = MSS (e.g. 1448), linear_len + paged_frags
                      │
   Pass through Routing, Netfilter, Traffic Control (Only 1 Pass!)
                      │
                      ▼
            [ dev_hard_start_xmit() ]
                      │
           Does NIC support hw_tso?
          ┌───────────┴───────────┐
         Yes                      No
          │                       │
          ▼                       ▼
 [ Hardware TSO Pass ]  [ Call skb_segment() ]
  Direct handoff to DMA  Software GSO Slicing
  Zero CPU Cycles used   Chops into MSS-sized skbs
  segments emitted by    - SEQ_k = SEQ_0 + offset
  NIC ASIC               - IP_ID_k = (IP_ID_0 + k) % 65536
                         - PSH / FIN on LAST segment ONLY!
                         - Scatter-gather frags sliced
          │                       │
          └───────────┬───────────┘
                      ▼
          [ Wire Packets to Wire ]
```

---

## ⚙️ I/O 데이터 규격 (Input/Output Specifications)

### 1. 입력 JSON 구조
```json
{
  "config": {
    "hw_tso": false,
    "default_mss": 1448,
    "header_len": 54
  },
  "trace": [
    {
      "op": "ASSEMBLE_GSO_SKB",
      "skb_id": "SKB_1",
      "gso_size": 1448,
      "ip_id_start": 1000,
      "tcp_seq_start": 50000,
      "tcp_flags": ["ACK", "PSH"],
      "linear_data_len": 0,
      "frags": [
        {"page_pfn": 8192, "offset": 0, "size": 2048},
        {"page_pfn": 8193, "offset": 0, "size": 2048}
      ]
    },
    {"op": "TRANSMIT_SKB", "skb_id": "SKB_1"},
    {"op": "GET_STATS"}
  ]
}
```

### 2. 필드 정의
- `config`:
  - `hw_tso` (bool, default=false): NIC 하드웨어 TSO 지원 여부.
  - `default_mss` (int, default=1448): 기본 최대 세그먼트 크기 (바이트).
  - `header_len` (int, default=54): 이더넷(14) + IP(20) + TCP(20) 총 헤더 길이.
- `trace` 명령어:
  1. `ASSEMBLE_GSO_SKB`:
     - `skb_id` (str): 슈퍼-패킷 식별자.
     - `gso_size` (int): 세그먼트 단위 크기 (MSS).
     - `ip_id_start` (int): 시작 IP Identification 번호.
     - `tcp_seq_start` (int): 시작 TCP Sequence Number.
     - `tcp_flags` (list of str): 포함된 TCP 플래그 목록 (예: `["ACK", "PSH", "FIN"]`).
     - `linear_data_len` (int): skb 선형 헤더 영역 페이로드 바이트 수.
     - `frags` (list of dict): 페이지 프래그먼트 배열 (`page_pfn`, `offset`, `size`).
  2. `TRANSMIT_SKB`:
     - `skb_id` (str): 전송할 skb 식별자. 하드웨어 TSO 패스스루 또는 소프트웨어 GSO 분할 수행.
  3. `GET_STATS`:
     - 현재 엔진 누적 통계 조회.

### 3. 출력 JSON 구조
```json
{
  "events": [
    {
      "op": "ASSEMBLE_GSO_SKB",
      "skb_id": "SKB_1",
      "total_payload_bytes": 4096,
      "gso_size": 1448,
      "gso_segs": 3,
      "num_frags": 2,
      "status": "GSO_SKB_ASSEMBLED"
    },
    {
      "op": "TRANSMIT_SKB",
      "skb_id": "SKB_1",
      "mode": "SOFTWARE_GSO_SEGMENTED",
      "total_payload_bytes": 4096,
      "segments_emitted": 3,
      "segments": [
        {
          "seg_index": 0,
          "ip_id": 1000,
          "tcp_seq": 50000,
          "payload_len": 1448,
          "wire_len": 1502,
          "tcp_flags": ["ACK"],
          "is_last_seg": false,
          "frags_sliced": 1
        },
        ...
      ],
      "cpu_cycles_saved_est": 0
    }
  ],
  "summary": {
    "hw_tso_enabled": false,
    "total_gso_skbs": 1,
    "hw_tso_dispatched": 0,
    "sw_gso_segmented": 1,
    "total_wire_packets": 3,
    "total_payload_bytes": 4096
  }
}
```
