# Linux Kernel PCIe SR-IOV (Single Root I/O Virtualization) PF-VF 메일박스 프로토콜 및 하드웨어 가상화 보안 엔진

## 문제 설명

클라우드 데이터센터, 초저지연 금융망(HFT), 5G 텔코 NFV(Network Functions Virtualization) 환경에서 소프트웨어 가상화 브리지(OVS, Linux Bridge)의 CPU 오버헤드를 극복하기 위해 **PCIe SR-IOV(Single Root I/O Virtualization)** 하드웨어 가상화 기술이 표준적으로 사용됩니다.

SR-IOV 환경에서는 단일 물리 PCIe 장치가 두 가지 상이한 함수(Function)로 분할됩니다:
- **Physical Function (PF)**: 전체 PCIe 물리 자원을 제어하고 관리 정책을 설정하는 완전한 기능을 갖춘 엔터프라이즈 드라이버.
- **Virtual Function (VF)**: 하드웨어 RX/TX 큐, 인터럽트 벡터(MSI-X)의 일부를 쪼개어 가상 머신(KVM 게스트)이나 컨테이너에 직접 패스스루(VFIO)할 수 있는 경량 함수.

```
       [ Host / Hypervisor (PF Driver: ixgbe / mlx5_core) ]
       ├── Admin Policies: MAC/VLAN Lock, Spoofcheck, Trust Mode, Link State
       ├── Hardware Queue Pool Partitioning: 64 Queues -> 4 VFs (12 Queues / VF)
       └── Mailbox Control Registers (PFMAILBOX[vf] / PFMBICR Interrupts)
                               ▲                  │
            4-Way Handshake    │ (MSI-X Request)  │ (ACK / NACK Response)
            Shared Memory FIFO │                  ▼
       [ Guest VM / Container Namespace (VF Driver: ixgbevf / mlx5_vf) ]
       ├── Mailbox Registers (VFMAILBOX / VF_REQ)
       └── Direct Hardware DMA: Zero-Copy Packet Transmission
```

VF는 신뢰할 수 없는(Untrusted) 테넌트 VM 내부에서 동작하므로, 글로벌 하드웨어 레지스터를 직접 조작할 수 없습니다. 따라서 MAC 주소 변경, VLAN 설정, 무차별 모드(Promiscuous Mode) 활성화 등 주요 작업은 **PF-VF 메일박스(Mailbox) 프로토콜**을 통해 PF에게 요청하고 검증받아야 합니다.

본 문제는 리눅스 커널의 SR-IOV 코어(`drivers/pci/iov.c`) 및 고성능 NIC 드라이버(`ixgbe_sriov.c`, `ixgbe_mbx.c`)의 **PF-VF 메일박스 핸드셰이크, 하드웨어 큐 자원 분할, 안티 스푸핑(Anti-Spoofing), 신뢰 모드(Trust Mode) 보안 상태 머신**을 정밀하게 에뮬레이션하는 엔진을 구현하는 것입니다.

---

## 핵심 엔진 아키텍처 및 요구사항

### 1. 하드웨어 큐 자원 분할 (Hardware Queue Partitioning)
- 활성화된 VF 개수가 $N$개(`num_vfs_enabled`)일 때, PF를 포함하여 $N+1$개 주체가 하드웨어 큐 풀(`max_queues_total`)을 균등 분할합니다:
  $$	ext{queues\_per\_vf} = \lfloor 	ext{max\_queues\_total} / (N + 1) floor$$
- 비활성화된 VF(`vfid >= num_vfs_enabled`)에 대한 메일박스 접근 시 `-ENODEV` (`-19`), `VF_NOT_ENABLED` NACK을 반환합니다.

### 2. 메일박스 DoS 방어 (Rate-Limiting)
- 악의적인 게스트가 초당 수천 건의 인터럽트를 발생시켜 호스트 PF를 마비시키는 것을 방지하기 위해, 단일 VF의 메일박스 트랜잭션 빈도가 `mbx_rate_limit`을 초과하면 `-EBUSY` (`-16`), `MBX_RATE_LIMIT_EXCEEDED` NACK을 반환합니다.

### 3. 메일박스 명령어 및 보안 검증 규칙
1. **`VF_RESET`**:
   - VF의 가상 하드웨어 상태(무차별 모드 등)를 초기화하고 할당된 큐 개수와 링크 활성 여부를 반환하며 성공(`ACK`, `err_code = 0`).
2. **`VF_GET_QUEUES`**:
   - 할당된 큐 개수, 관리자 VLAN, 스푸프체크 활성 여부, 신뢰 모드 상태를 반환하며 성공(`ACK`, `err_code = 0`).
3. **`VF_SET_MAC`**:
   - PF 관리자가 사전에 MAC을 고정 할당(`admin_mac_locked`)했고 해당 VF가 비신뢰(`trust == false`) 상태인 경우, MAC 변경 요청을 `-EPERM` (`-1`), `MAC_CHANGE_DENIED_UNTRUSTED_VF` NACK으로 거부합니다.
   - 신뢰 모드(`trust == true`)이거나 사전 고정되지 않은 경우 요청된 MAC으로 갱신 후 성공(`ACK`).
4. **`VF_SET_VLAN`**:
   - 관리자 VLAN이 고정되었고 비신뢰 상태인 경우 `-EPERM` (`-1`), `VLAN_CHANGE_DENIED_ADMIN_ASSIGNED` NACK으로 거부합니다.
5. **`VF_SET_PROMISC` (무차별 모드)**:
   - 비신뢰 VF가 무차별 모드를 요청할 경우 다른 테넌트의 트래픽을 도청(Sniffing)할 위험이 있으므로 `-EPERM` (`-1`), `PROMISCUOUS_MODE_DENIED_UNTRUSTED_VF` NACK으로 차단합니다.
   - 신뢰 VF인 경우에만 허용(`ACK`).
6. **`VF_SEND_PACKET` (패킷 송신)**:
   - 링크 상태가 `disable`인 경우 `-ENETDOWN` (`-100`), `LINK_DOWN_ADMINISTRATIVELY_DISABLED` NACK.
   - 스푸프체크(`spoofcheck == true`)가 켜진 상태에서 송신 패킷의 소스 MAC(`src_mac`)이 VF의 공인 MAC과 불일치할 경우 즉시 패킷을 폐기하고 `-EACCES` (`-111`), `PACKET_DROPPED_SPOOFCHECK_VIOLATION` NACK.
   - 정상 패킷은 성공(`ACK`).

---

## 입력 형식

JSON 문자열이 표준 입력(`stdin`)으로 주어집니다:

```json
{
  "pf_config": {
    "total_vfs": 8,
    "num_vfs_enabled": 2,
    "max_queues_total": 64,
    "mbx_rate_limit": 5
  },
  "vf_configurations": [
    {
      "vf_id": 0,
      "mac": "52:54:00:11:22:00",
      "vlan": 100,
      "spoofcheck": true,
      "trust": false,
      "link_state": "auto"
    },
    {
      "vf_id": 1,
      "mac": "52:54:00:11:22:01",
      "vlan": 0,
      "spoofcheck": true,
      "trust": true,
      "link_state": "auto"
    }
  ],
  "transactions": [
    {
      "txn_id": "TXN_01",
      "vf_id": 0,
      "msg_type": "VF_GET_QUEUES"
    },
    {
      "txn_id": "TXN_02",
      "vf_id": 0,
      "msg_type": "VF_SET_PROMISC",
      "params": {"promisc": true}
    },
    {
      "txn_id": "TXN_03",
      "vf_id": 0,
      "msg_type": "VF_SEND_PACKET",
      "params": {"src_mac": "aa:bb:cc:dd:ee:ff"}
    },
    {
      "txn_id": "TXN_04",
      "vf_id": 1,
      "msg_type": "VF_SET_PROMISC",
      "params": {"promisc": true}
    }
  ]
}
```

---

## 출력 형식

메일박스 트랜잭션 처리 결과와 집계 메트릭을 JSON 형태로 표준 출력(`stdout`)에 공백 없이 출력합니다:

```json
{
  "engine": "pcie_sriov_pf_vf_mailbox",
  "metrics": {
    "total_transactions": 4,
    "acks_issued": 2,
    "nacks_issued": 2,
    "spoof_drops": 1,
    "promisc_denials": 1,
    "mac_denials": 0,
    "mbx_rate_limit_mitigations": 0,
    "queues_per_vf": 21
  },
  "verdict": "VF_SECURITY_VIOLATION_CONTAINED",
  "results": [
    {
      "txn_id": "TXN_01",
      "vf_id": 0,
      "status": "ACK",
      "err_code": 0,
      "data": {
        "num_queues": 21,
        "default_vlan": 100,
        "spoofcheck": true,
        "trust": false
      }
    },
    {
      "txn_id": "TXN_02",
      "vf_id": 0,
      "status": "NACK",
      "err_code": -1,
      "reason": "PROMISCUOUS_MODE_DENIED_UNTRUSTED_VF"
    },
    {
      "txn_id": "TXN_03",
      "vf_id": 0,
      "status": "NACK",
      "err_code": -111,
      "reason": "PACKET_DROPPED_SPOOFCHECK_VIOLATION"
    },
    {
      "txn_id": "TXN_04",
      "vf_id": 1,
      "status": "ACK",
      "err_code": 0,
      "data": {
        "promisc": true
      }
    }
  ]
}
```

---

## 판정 규칙 (`verdict`)

1. 스푸프 드롭, 무차별 모드 거부, MAC 변경 거부, 메일박스 플러딩 제한 등 보안 위반 시도가 1건 이상 방어된 경우:
   `"VF_SECURITY_VIOLATION_CONTAINED"`
2. 모든 트랜잭션이 NACK 없이 온전히 ACK 처리된 경우:
   `"SRIOV_FABRIC_OPTIMAL"`
3. 비활성화된 VF 요청 또는 잘못된 구성으로 인한 오류 발생 시:
   `"SRIOV_CONFIGURATION_FAULT"`
