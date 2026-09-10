# 문제 412: Linux 커널 IPVLAN 네트워크 가상화 엔진 및 L2/L3/L3S Netfilter 상태 머신

## 문제 설명

클라우드 네이티브 컴퓨팅, 대규모 쿠버네티스(Kubernetes) 클러스터 및 텔코(Telco) 5G NFV(Network Functions Virtualization) 환경에서는 단일 물리 서버(Host) 위에 수백~수천 개의 컨테이너 및 파드(Pod)가 초고밀도로 배치됩니다.

초기 리눅스 컨테이너 가상화는 주로 **veth pair + Linux Bridge** 조합을 사용했으나, 이는 패킷이 브릿지를 통과할 때마다 발생하는 두 번의 네트워크 스택 순회 및 가상 인터페이스 컨텍스트 스위칭 오버헤드로 인해 처리량이 크게 제한되었습니다. 이를 극복하기 위해 물리 NIC를 직접 분할하여 가상 인터페이스를 제공하는 **Macvlan**이 도입되었으나, Macvlan은 각 컨테이너마다 고유한 물리 MAC 주소를 생성해야 하므로 다음과 같은 심각한 인프라 문제를 유발했습니다:
1. **스위치 포트 시큐리티(Port Security) 위반**: 엔터프라이즈 스위치나 클라우드 하이퍼바이저는 단일 물리 포트에서 여러 개의 서로 다른 MAC 주소가 감지되면 보안 위협으로 간주하여 해당 포트를 즉시 다운(Port Error-Disable)시킵니다.
2. **CAM 테이블(MAC 주소 테이블) 포화 및 플러딩**: 수천 개 컨테이너의 고유 MAC 주소가 ToR(Top-of-Rack) 스위치에 누적되면 스위치 메모리가 고갈되어 전체 네트워크에 패킷이 무차별 플러딩되는 브로드캐스트 스톰이 발생합니다.

이 문제를 해결하기 위해 리눅스 커널 3.19에 공식 도입된 네트워크 서브시스템이 바로 **IPVLAN (`drivers/net/ipvlan/ipvlan_core.c`, `drivers/net/ipvlan/ipvlan_main.c`, `CONFIG_IPVLAN`)**입니다.

### IPVLAN의 핵심 동작 메커니즘

1. **단일 물리 MAC 주소 공유 (Shared Physical MAC)**:
   - 호스트의 모든 슬레이브 인터페이스(`ipvl0`, `ipvl1`, ...)는 물리 부모 디바이스(`eth0`)의 단 하나의 물리 MAC 주소(`master_mac`)를 완전히 공유합니다.
   - 외부 스위치는 언제나 단 1개의 MAC 주소만을 인식하므로 포트 시큐리티나 CAM 테이블 고갈 문제가 원천적으로 발생하지 않습니다.
   - 패킷 디멀티플렉싱(Demultiplexing)은 L2 MAC이 아닌 **L3 목적지 IP 주소 (`dst_ip`)**를 기준으로 커널 해시 테이블(`ip_to_slave`)을 통해 O(1)에 수행됩니다.

2. **3대 포워딩 모드 (L2 / L3 / L3S)**:
   - **L2 모드 (`IPVLAN_MODE_L2`)**:
     - L2 브릿지처럼 동작하며, 유니캐스트 패킷은 목적지 IP를 기준으로 해당 슬레이브로 직접 전달됩니다.
     - ARP 브로드캐스트(`FF:FF:FF:FF:FF:FF`) 패킷을 수신하면, 마스터는 모든 슬레이브 인터페이스로 브로드캐스트를 복제(`DELIVERED_BROADCAST`) 전달합니다.
   - **L3 모드 (`IPVLAN_MODE_L3`)**:
     - L3 라우터처럼 동작합니다. L2 헤더를 무시하고 오직 IP 라우팅만 수행합니다.
     - L2 브로드캐스트 및 멀티캐스트 트래픽을 원천 차단(`L3_NO_BROADCAST`)하여 브로드캐스트 스톰을 방지합니다.
     - 동일 호스트 내 슬레이브 간 통신은 물리 NIC를 거치지 않고 커널 내부에서 직접 전달되는 **헤어핀(Hairpin) 로컬 스위칭**으로 처리됩니다.
   - **L3S 대칭 모드 (`IPVLAN_MODE_L3S` - L3 Symmetric)**:
     - Linux 4.15에 도입된 모드로, 인그레스(Ingress) 패킷 수신 시 단순 포워딩하는 대신 **수신 대상 슬레이브의 네트워크 네임스페이스(netns) 내부 Netfilter(iptables/nftables) `PRE_ROUTING` 체인을 직접 통과**시킵니다.
     - 이를 통해 컨테이너별 독립적인 방화벽 차단(`DROP`) 및 로컬 로드밸런싱/DNAT(`target_ip` 변환) 규칙을 완벽하게 적용할 수 있습니다.
     - 이그레스(Egress) 송신 시에도 송신 슬레이브 netns의 `POST_ROUTING` 체인을 거쳐 외부 또는 내부 헤어핀으로 전달됩니다.

3. **패킷 드롭 및 보안 격리 규칙**:
   - `DROP_INVALID_MAC`: 유니캐스트 패킷의 `dst_mac`이 마스터 디바이스의 MAC과 일치하지 않는 경우 L2 계층에서 즉시 폐기.
   - `L3_NO_BROADCAST`: L3 및 L3S 모드에서 브로드캐스트 패킷이 도착한 경우 폐기.
   - `DROP_NO_ROUTE`: 목적지 IP가 슬레이브 또는 호스트 IP와 매칭되지 않는 경우 폐기.
   - `NETFILTER_DROP`: 슬레이브 netns 내부 방화벽 룰에 의해 차단된 경우 폐기.

여러분은 리눅스 커널 IPVLAN 드라이버의 L2/L3/L3S 3대 포워딩 계층, 단일 MAC 기반 IP 디멀티플렉싱, 슬레이브 네임스페이스 Netfilter 체인 주입, 브로드캐스트 제어 및 헤어핀 로컬 스위칭 엔진을 충실히 모델링하는 시뮬레이터를 구현해야 합니다.

---

## 시스템 아키텍처 다이어그램

```
+==================================================================================================+
|                        Linux Kernel IPVLAN Network Architecture                                  |
+==================================================================================================+

   [ Physical Wire / External Switch ]
                   |
                   | Ingress Ethernet Frame (dst_mac, dst_ip)
                   v
+--------------------------------------------------------------------------------------------------+
| Physical Master Interface: eth0 (Master MAC: 02:42:ac:11:00:01)                                  |
|                                                                                                  |
|  [ Step 1: L2 MAC Verification ]                                                                 |
|    - Is dst_mac == master_mac OR FF:FF:FF:FF:FF:FF ?                                             |
|        * NO  ===> DROP (DROP_INVALID_MAC)                                                        |
|                                                                                                  |
|  [ Step 2: Broadcast / Multicast Demux ]                                                         |
|    - Is dst_mac == FF:FF:FF:FF:FF:FF ?                                                           |
|        * In L2 Mode   ===> Replicate to ALL Registered Slaves (DELIVERED_BROADCAST)              |
|        * In L3/L3S    ===> DROP (L3_NO_BROADCAST - Suppress Broadcast Storms!)                   |
|                                                                                                  |
|  [ Step 3: Unicast IP Demux & Mode-Specific Forwarding ]                                         |
|    - Lookup dst_ip in port->ip_to_slave hash table:                                              |
|                                                                                                  |
|      * Mode == L2:                                                                               |
|          - Direct forward to slave Rx queue (Zero Netfilter overhead!)                           |
|                                                                                                  |
|      * Mode == L3:                                                                               |
|          - Route at L3 layer, forward to slave Rx queue                                          |
|                                                                                                  |
|      * Mode == L3S (L3 Symmetric):                                                               |
|          - Inject into Slave Network Namespace Context!                                          |
|          - Traverse Netfilter PRE_ROUTING Chain:                                                 |
|              + ACCEPT ---> Deliver to Container Socket                                           |
|              + DROP   ---> DROP (NETFILTER_DROP)                                                 |
|              + DNAT   ---> Rewrite dst_ip and deliver!                                           |
|                                                                                                  |
|  [ Step 4: Inter-Slave Hairpin Local Switching ]                                                 |
|    - Egress packet from Slave A targeted at Slave B (same master):                               |
|        * Does NOT hit physical wire! Switched directly in kernel memory!                         |
|        * In L3S: Passes Slave A POST_ROUTING, then Slave B PRE_ROUTING!                          |
+==================================================================================================+
```

---

## 상세 요구사항 및 동작 규칙

### 1. 시스템 설정 파라미터 (`config`)
- `mode`: IPVLAN 동작 모드 (`"L2"`, `"L3"`, `"L3S"` 중 하나, 기본값: `"L2"`)
- `master_mac`: 물리 부모 인터페이스의 고유 MAC 주소 (기본값: `"02:42:ac:11:00:01"`)
- `host_ip`: 호스트 운영체제 자체의 로컬 IP 주소 (기본값: `"10.0.0.1"`)

### 2. 이벤트 트레이스 연산 (`trace`)

1. **`REGISTER_SLAVE`**:
   - `time`, `slave_id`, `netns_id`, `ip_addr`.
   - 새로운 컨테이너 슬레이브 인터페이스를 등록하고 IP 해시 테이블에 매핑합니다.

2. **`UNREGISTER_SLAVE`**:
   - `time`, `slave_id`.
   - 컨테이너 종료에 따라 슬레이브 인터페이스 및 IP 매핑을 해제합니다.

3. **`SET_NETFILTER_RULE`**:
   - `time`, `netns_id`, `chain` (`"PRE_ROUTING"` 또는 `"POST_ROUTING"`), `action` (`"ACCEPT"`, `"DROP"`, `"DNAT"`), `match_ip`, `target_ip`.
   - 특정 네트워크 네임스페이스의 Netfilter 체인에 방화벽/변환 규칙을 등록합니다.

4. **`INGRESS_PACKET`**:
   - `time`, `src_mac`, `dst_mac`, `src_ip`, `dst_ip`, `proto`, `payload_len`.
   - 외부 네트워크에서 물리 마스터 인터페이스로 수신된 패킷 처리:
     - `dst_mac`이 `master_mac`과 다르고 브로드캐스트가 아니면 `DROP_INVALID_MAC`으로 드롭.
     - 브로드캐스트인 경우: L2 모드면 모든 활성 슬레이브로 복제 전달, L3/L3S 모드면 `L3_NO_BROADCAST`로 드롭.
     - 유니캐스트인 경우: `dst_ip`가 등록된 슬레이브이면 해당 슬레이브로 포워딩 (L3S 모드에서는 슬레이브 netns의 `PRE_ROUTING` 검사 통과 필요). `dst_ip == host_ip`이면 호스트 로컬 수신, 일치하는 대상이 없으면 `DROP_NO_ROUTE`로 드롭.

5. **`EGRESS_PACKET`**:
   - `time`, `slave_id`, `dst_ip`, `proto`, `payload_len`.
   - 컨테이너 슬레이브에서 송신되는 패킷 처리:
     - L3S 모드인 경우 송신 슬레이브 netns의 `POST_ROUTING` 규칙을 먼저 평가 (DROP 시 즉시 폐기, DNAT 시 목적지 IP 재작성).
     - 변환된 목적지 IP가 동일 마스터에 등록된 다른 슬레이브의 IP인 경우:
       - **헤어핀(Hairpin) 로컬 스위칭** 발동.
       - L3S 모드라면 수신 슬레이브 netns의 `PRE_ROUTING` 체인을 추가 통과한 후 수신 슬레이브에 전달.
     - 목적지 IP가 외부인 경우:
       - 물리 마스터 인터페이스를 통해 외부 유선망으로 송신(`TRANSMITTED_WIRE`, 소스 MAC은 `master_mac`으로 설정).

---

## 입출력 형식 (JSON)

### 입력 형식 (Standard Input)

```json
{
  "config": {
    "mode": "L3S",
    "master_mac": "02:42:ac:11:00:01",
    "host_ip": "10.0.0.1"
  },
  "trace": [
    {
      "time": 0,
      "type": "REGISTER_SLAVE",
      "slave_id": "c1",
      "netns_id": "ns1",
      "ip_addr": "10.0.0.10"
    },
    {
      "time": 1,
      "type": "INGRESS_PACKET",
      "src_mac": "00:11:22:33:44:55",
      "dst_mac": "02:42:ac:11:00:01",
      "src_ip": "1.1.1.1",
      "dst_ip": "10.0.0.10"
    }
  ]
}
```

### 출력 형식 (Standard Output)

공백 없이 압축된 단일 라인 JSON 문자열(`separators=(',', ':')`, `ensure_ascii=False`)로 출력해야 합니다:

```json
{
  "summary": {
    "mode": "L3S",
    "forwarded_ingress_packets": 1,
    "forwarded_egress_packets": 0,
    "hairpin_local_switched_packets": 0,
    "dropped_packets": 0,
    "netfilter_inspected_packets": 1,
    "active_slaves_count": 1
  },
  "active_slaves": {
    "c1": {
      "slave_id": "c1",
      "netns": "ns1",
      "ip": "10.0.0.10"
    }
  },
  "packet_history": [
    {
      "time": 1,
      "direction": "INGRESS",
      "status": "DELIVERED_SLAVE",
      "slave_id": "c1",
      "netns": "ns1",
      "mode": "L3S",
      "src_ip": "1.1.1.1",
      "dst_ip": "10.0.0.10"
    }
  ],
  "event_logs": [ ... ]
}
```
