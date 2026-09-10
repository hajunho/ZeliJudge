# Problem #388: Linux Kernel eBPF Flow Dissector & RSS Hashing Engine (`net/core/flow_dissector.c`, `BPF_PROG_TYPE_FLOW_DISSECTOR`)

## 문제 설명

고성능 리눅스 네트워크 서브시스템에서 NIC 하드웨어 **RSS(Receive Side Scaling)** 및 소프트웨어 **RPS(Receive Packet Steering)**는 수신 패킷의 L3/L4 5-튜플(IP 주소, 포트, 프로토콜) 해시값을 계산하여 다중 수신 큐(Multi-Queue RX)로 트래픽을 분산합니다.

그러나 클라우드 데이터센터 가상화 환경에서 터널링 프로토콜(VXLAN, GRE, Geneve, VLAN QinQ)로 캡슐화된 패킷이 유입될 경우, 전통적인 하드웨어 RSS 엔진은 외부 오버레이 헤더(Outer Header)만을 인식하여 모든 트래픽을 단일 수신 큐로 몰아넣는 **수신 큐 편향 현상(Receive Queue Polarization)**을 초래합니다.

리눅스 커널은 네트워크 네임스페이스 레벨에서 프로그래머블 패킷 파싱을 수행하는 **eBPF Flow Dissector (`BPF_PROG_TYPE_FLOW_DISSECTOR`, `net/core/flow_dissector.c`)**를 도입했습니다:

```
+----------------------------------------------------------------------------------------------------+
|                                eBPF Flow Dissector Pipeline                                        |
+----------------------------------------------------------------------------------------------------+
| [ Ingress Raw Packet / sk_buff ]                                                                   |
|   | 1. L2 Ethernet & 802.1Q VLAN / QinQ Tag Extraction -> extract vlan_id                          |
|   | 2. Outer L3 IP (IPv4/IPv6) Length Validation -> detect truncation (actual < declared total_len)|
|   | 3. Tunnel Decapsulation (VXLAN UDP 4789, VNI extraction / GRE proto 47)                         |
|   | 4. Extract Canonical Flow Keys (Inner src_ip, dst_ip, src_port, dst_port, ip_proto)           |
|   | 5. Compute Symmetric 5-Tuple Jenkins/SipHash -> rx_queue = hash % num_rx_queues                |
|   | 6. Return BPF_OK (keys extracted) / BPF_DROP (corrupted header/flags)                           |
+----------------------------------------------------------------------------------------------------+
```

### 핵심 기능 및 파싱 규칙

1. **L2 및 VLAN 파싱**:
   - 이더넷 헤더 누락 시 `BPF_DROP` 처리.
   - 802.1Q VLAN 태그가 존재할 경우 `vlan_id`를 추출하고 오프셋을 시프트하여 L3를 파싱합니다.
2. **패킷 무결성 및 절단(Truncation) 방어**:
   - 패킷의 실제 바이트 길이(`length`)가 IP 헤더의 선언 길이(`total_len`)보다 작을 경우 절단된 패킷으로 판정하여 즉시 `BPF_DROP` 처리합니다.
3. **터널 캡슐화 해제 (VXLAN & GRE)**:
   - **VXLAN**: 외부 UDP 포트 4789 수신 시 VXLAN 헤더의 필수 `I-flag`(`0x08`)를 검증합니다. 플래그가 유효하지 않으면 `BPF_DROP` 처리합니다. 유효할 경우 24비트 VNI를 추출하고 내부(Inner) IP 및 L4 포트를 추출합니다.
   - **GRE**: 프로토콜 47 수신 시 GRE 헤더를 디캡슐화하여 내부 IP/L4를 파싱합니다.
4. **대칭 5-튜플 플로우 해싱 (Symmetric Flow Hashing)**:
   - 양방향 트래픽(A $\leftrightarrow$ B)이 동일한 RX 큐에 도달하여 CPU 캐시 친화도(Cache Locality)를 극대화할 수 있도록 순서 무관 대칭 정렬(`min/max(ip1, ip2)`, `min/max(port1, port2)`) 기반 해시를 생성합니다:
     $$\text{rx\_queue} = \text{flow\_hash} \pmod{\text{num\_rx\_queues}}$$

당신은 리눅스 커널의 eBPF Flow Dissector 엔진을 정밀 시뮬레이션하여 터널 디캡슐화, 패킷 무결성 검증, 5-튜플 대칭 해싱 및 다중 RX 큐 분산 히스토그램을 산출하는 프로그램을 구현해야 합니다.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다:

```json
{
  "config": {
    "num_rx_queues": 8,
    "hash_seed": 322423454,
    "decap_vxlan": true,
    "decap_gre": true
  },
  "packets": [
    {
      "id": "p1",
      "length": 64,
      "layers": {
        "ethernet": { "src": "aa:01", "dst": "bb:01" },
        "ipv4": { "src": "10.0.0.1", "dst": "10.0.0.2", "proto": 6, "total_len": 64 },
        "l4": { "src_port": 12345, "dst_port": 80 }
      }
    }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 공백 없이 컴팩트한 단일 JSON 객체를 출력합니다:

```json
{
  "total_packets": 1,
  "dropped_packets": 0,
  "encapsulated_packets": 0,
  "rx_queue_distribution": [0, 0, 1, 0, 0, 0, 0, 0],
  "events": [
    {
      "packet_id": "p1",
      "status": "BPF_OK",
      "flow_keys": {
        "src_ip": "10.0.0.1",
        "dst_ip": "10.0.0.2",
        "src_port": 12345,
        "dst_port": 80,
        "ip_proto": 6,
        "is_encapsulated": false,
        "vlan_id": null,
        "vni": null
      },
      "flow_hash_hex": "0xaabe467a",
      "rx_queue": 2
    }
  ]
}
```
