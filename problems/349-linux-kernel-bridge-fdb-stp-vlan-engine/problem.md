# 리눅스 커널 Bridge 포워딩 데이터베이스(FDB), STP 포트 상태 머신 및 VLAN 필터링 엔진

## 1. 개요 및 배경

클라우드 컴퓨팅, 도커(Docker) 기본 브리지 네트워크(`docker0`), 쿠버네티스 CNI 플러그인(Flannel/Bridge), 그리고 KVM/QEMU 가상머신 TAP 디바이스 연동의 핵심 기반은 리눅스 커널의 **소프트웨어 브리지 서브시스템(`net/bridge/`)**입니다.

하드웨어 L2 이더넷 스위치를 소프트웨어로 구현한 리눅스 브리지는 다음과 같은 핵심 기능들을 수행합니다:
1. **포워딩 데이터베이스 (Forwarding DataBase, FDB)**: 인입되는 이더넷 프레임의 출발지 MAC 주소를 학습(`br_fdb_update`)하여 입력 포트와 매핑하고, 수명 타이머(`ageing_time`, 기본 300초)를 부여합니다. 목적지 MAC이 FDB에 존재하면 해당 포트로만 단일 전송(Unicast Forwarding)하고, 미등록 유니캐스트나 브로드캐스트(`FF:FF:FF:FF:FF:FF`)는 다른 모든 활성 포트로 플러딩(Flooding)합니다.
2. **신장 트리 프로토콜 (Spanning Tree Protocol, STP) 포트 상태 머신**: 브리지 루프(Loop)로 인한 브로드캐스트 스톰(Broadcast Storm)을 방지하기 위해 각 포트를 `DISABLED`, `BLOCKING`, `LISTENING`, `LEARNING`, `FORWARDING` 5대 상태로 전이합니다. 특히 `LEARNING` 상태에서는 MAC 주소 학습만 수행하고 데이터 프레임 포워딩은 차단함으로써 루프 방지와 FDB 수렴을 동시에 달성합니다.
3. **토폴로지 변경 통지 (Topology Change Notification, TCN)**: 네트워크 링크 장애나 포트 상태 변화 시 TCN을 수신하여 FDB 노화 타이머를 단축(Fast Aging, 기본 15초)함으로써 죽은 경로로 패킷이 전송되는 블랙홀(Blackhole) 참사를 신속히 방어합니다.
4. **VLAN 필터링 (`vlan_filtering`)**: IEEE 802.1Q 태그를 기반으로 트렁크(Trunk) 및 액세스(Access) 포트 간의 트래픽을 상호 격리합니다.
5. **동일 포트 반사 필터링 (Same-Port Filtering)**: 목적지 MAC이 프레임이 인입된 포트와 동일한 포트에 위치한 경우, 하부 세그먼트의 로컬 통신이므로 불필요한 반사 루프를 방지하기 위해 프레임을 즉시 필터링(Drop)합니다.

당신은 컨테이너 및 가상화 네트워크의 프레임 포워딩 동작을 정밀 검증하기 위해, 리눅스 커널 브리지의 FDB 동적 학습/노화, STP 상태 전이, 플러딩, VLAN 격리 및 TCN 단축 노화를 시뮬레이션하는 **리눅스 커널 브리지 엔진**을 구현해야 합니다.

---

## 2. 시스템 아키텍처 및 프레임 처리 파이프라인

```
           [ 물리/가상 인터페이스 인입 (veth, tap, eth) ]
                               │
                               ▼
        [ Ingress Port 상태 검사: DISABLED / BLOCKING? ]
              │                               │
             (Yes)                           (No)
              │                               │
         [즉시 드롭]                  [VLAN 인입 필터링 검사]
                                              │
                              ┌───────────────┴───────────────┐
                             (불일치)                        (일치)
                              │                               │
                         [VLAN 드롭]                  [FDB 동적 MAC 학습]
                                              (LEARNING / FORWARDING 상태)
                                                              │
                                              [Ingress Port가 FORWARDING인가?]
                                                              │
                                              ┌───────────────┴───────────────┐
                                             (No)                            (Yes)
                                              │                               │
                                      [학습 완료/포워딩 중단]         [목적지 MAC FDB 조회]
                                                                              │
                                      ┌───────────────────────────────────────┴───────────────────┐
                                      ▼                                                           ▼
                             [목적지 FDB 등록됨]                                          [미등록 or 브로드캐스트]
                                      │                                                           │
                      ┌───────────────┴───────────────┐                                           │
                      ▼                               ▼                                           ▼
             [출발지와 동일 포트]             [타 포트로 포워딩]                                 [모든 활성 포트로]
             -> [동일 포트 필터링]            -> [Egress 상태/VLAN 검사 후 전송]                [플러딩 (FLOOD)]
```

---

## 3. 핵심 규칙 및 알고리즘 명세

### 3.1 브리지 구성 및 포트 상태
- `ports`: 각 브리지 포트(`port_id`)는 다음 속성을 갖습니다:
  - `state`: `"DISABLED"`, `"BLOCKING"`, `"LISTENING"`, `"LEARNING"`, `"FORWARDING"`
  - `pvid`: 기본 포트 VLAN ID (정수)
  - `allowed_vlans`: 포트가 허용하는 VLAN ID 집합
- `fdb`: 키 `(mac, vlan)` -> `{"port", "last_seen_sec", "is_static"}`
  - `is_static == true`인 엔트리는 노화되지 않습니다.
  - `is_static == false`인 동적 엔트리는 `current_time - last_seen_sec >= effective_ageing` 조건 시 만료되어 소멸(`mac_aged_out` 1 증가)합니다.

### 3.2 프레임 인입(`FRAME_INGRESS`) 처리 파이프라인
1. **FDB 노화 정리(Purge)**: 이벤트 처리 전, 현재 시각 `timestamp_sec` 기준으로 만료된 동적 FDB 엔트리를 제거합니다. (단, TCN 단축 노화 활성 구간 내에서는 15초 적용)
2. **인입 포트 상태 검사**:
   - `state in ["DISABLED", "BLOCKING"]`: `frames_dropped_port_state` 1 증가, `action: "DROP_PORT_STATE"`.
3. **VLAN 인입 필터링**:
   - `vlan_filtering == true`이고 `vlan`이 포트의 `allowed_vlans`에 속하지 않는 경우:
     - `frames_dropped_vlan` 1 증가, `action: "DROP_VLAN_FILTERING"`.
4. **동적 MAC 학습 (Dynamic MAC Learning)**:
   - 인입 포트가 `LEARNING` 또는 `FORWARDING` 상태인 경우:
     - `(src_mac, vlan)` 엔트리가 FDB에 없거나 정적이 아닌 경우 갱신 (`port = in_port`, `last_seen_sec = timestamp_sec`).
     - 신규 등록 시 `mac_learned` 1 증가.
5. **포워딩 가능 여부 검사**:
   - 인입 포트가 `FORWARDING` 상태가 아니면 (`LEARNING` 등):
     - 학습만 수행하고 포워딩하지 않음 (`action: "LEARNED_NO_FORWARD"`).
6. **목적지 주소 판별 및 포워딩**:
   - 브로드캐스트(`FF:FF:FF:FF:FF:FF`), 멀티캐스트(`01:00:5E` 또는 `33:33` 시작), 또는 FDB 미등록 유니캐스트:
     - 인입 포트를 제외하고, `state == "FORWARDING"`이며 VLAN이 일치하는 모든 출력 포트로 전송 (`action: "FLOOD"`, `frames_flooded` 1 증가).
   - FDB에 등록된 유니캐스트:
     - `dest_port == in_port`: 로컬 루프 방지를 위해 드롭 (`action: "FILTER_SAME_PORT"`, `frames_filtered_same_port` 1 증가).
     - `dest_port != in_port`:
       - 대상 포트의 `state != "FORWARDING"`이면 `DROP_EGRESS_PORT_STATE`.
       - VLAN 불일치 시 `DROP_EGRESS_VLAN`.
       - 정상이면 대상 포트로 단일 전송 (`action: "FORWARD_UNICAST"`, `frames_forwarded_unicast` 1 증가).

### 3.3 제어 이벤트
- `SET_PORT_STATE`: 지정된 포트의 STP 상태를 갱신합니다.
- `TOPOLOGY_CHANGE_NOTIFICATION`: 토폴로지 변경 통지 수신 시 `forward_delay_sec`(기본 15초) 동안 단축 노화(15초)를 활성화하고, 즉시 15초 초과된 FDB 엔트리를 제거합니다 (`tcn_events` 1 증가).

---

## 4. 입출력 형식 및 제약 조건

### 입력 형식 (JSON)
```json
{
  "bridge_config": { "ageing_time_sec": 300, "vlan_filtering": true },
  "ports": {
    "eth0": { "state": "FORWARDING", "pvid": 1, "allowed_vlans": [1, 10] },
    "eth1": { "state": "FORWARDING", "pvid": 10, "allowed_vlans": [10] }
  },
  "initial_fdb": [
    { "mac": "00:11:22:33:44:01", "vlan": 10, "port": "eth1", "is_static": true }
  ],
  "events": [
    {
      "type": "FRAME_INGRESS",
      "frame_id": "f1",
      "timestamp_sec": 10,
      "in_port": "eth0",
      "src_mac": "AA:BB:CC:00:00:01",
      "dst_mac": "00:11:22:33:44:01",
      "vlan": 10
    }
  ]
}
```

### 출력 형식 (JSON)
```json
{
  "stats": {
    "frames_received": 1,
    "frames_forwarded_unicast": 1,
    "frames_flooded": 0,
    "frames_dropped_port_state": 0,
    "frames_dropped_vlan": 0,
    "frames_filtered_same_port": 0,
    "mac_learned": 1,
    "mac_aged_out": 0,
    "tcn_events": 0
  },
  "fdb_count": 2,
  "fdb": [
    { "mac": "00:11:22:33:44:01", "vlan": 10, "port": "eth1", "is_static": true, "last_seen_sec": 0 },
    { "mac": "AA:BB:CC:00:00:01", "vlan": 10, "port": "eth0", "is_static": false, "last_seen_sec": 10 }
  ],
  "ports": { "eth0": "FORWARDING", "eth1": "FORWARDING" },
  "event_logs": [ ... ]
}
```
