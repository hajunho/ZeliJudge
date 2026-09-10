# PCIe SR-IOV 하드웨어 가상화 및 PF-VF 메일박스 프로토콜 이론

## 1. 하드웨어 I/O 가상화의 진화와 SR-IOV

서버 가상화 초기에 네트워크 I/O는 하이퍼바이저(Hypervisor)의 소프트웨어 에뮬레이션(e1000, VirtIO-Net)에 전적으로 의존했습니다. 이 방식은 패킷이 전송될 때마다 다음과 같은 심각한 지연을 겪었습니다:
1. 게스트 OS에서 하이퍼바이저로의 **VM-Exit** 발생
2. 소프트웨어 브리지(Linux Bridge, OVS)에서 패킷 헤더 복사 및 라우팅
3. 호스트 커널 드라이버를 거쳐 물리 하드웨어로 전달

이러한 오버헤드를 근본적으로 제거하기 위해 PCI-SIG는 **SR-IOV(Single Root I/O Virtualization)** 규격을 제정했습니다. SR-IOV를 지원하는 NIC(Intel 82599, X540, Mellanox ConnectX 시리즈)는 단일 실리콘 칩 내부에 수십 개의 독립적인 PCIe 가상 함수(Virtual Function, VF)를 하드웨어적으로 구현합니다.

---

## 2. PF와 VF의 역할 및 BDF 어드레싱

- **Physical Function (PF)**:
  - PCIe 표준 스펙을 완전히 준수하며 `PCI_EXT_CAP_ID_SRIOV` 확장 역량(Extended Capability) 헤더를 보유합니다.
  - 전원 관리, 하드웨어 초기화, 링크 속도 제어, VF 활성화(`pci_enable_sriov`), 전역 리소스(메모리 윈도우, 하드웨어 큐 풀) 분배를 총괄합니다.
- **Virtual Function (VF)**:
  - 경량화된 PCIe 장치로서 자체적인 구성 공간(Configuration Space)과 독자적인 Bus:Device:Function(BDF) 식별자를 갖습니다.
  - 하드웨어 RX/TX 링 버퍼와 직접 통신하므로, KVM 게스트에 VFIO(Virtual Function I/O)로 직접 패스스루되면 **하이퍼바이저 개입 없이 베어메탈에 준하는 대역폭과 극소 지연시간(Line Rate & Sub-Microsecond Latency)**을 달성합니다.

---

## 3. PF-VF 메일박스(Mailbox) 통신 프로토콜

VF는 독립적인 BDF를 갖지만, 물리적 PHY/MAC 레지스터나 전역 스위치 설정에 직접 쓸 수 있는 권한이 없습니다. 만약 임의의 VF가 PHY 레지스터를 재설정한다면 동일한 물리 포트를 공유하는 다른 모든 테넌트의 통신이 중단되기 때문입니다.

이를 해결하기 위해 호스트 PF와 게스트 VF 사이에 **메일박스(Mailbox) IPC 아키텍처**가 구축됩니다:

```
[ Step 1: VF Write ]
  VF 드라이버가 공유 메모리 버퍼(Shared RAM)에 요청 메시지를 기록 (16 Dwords)
  예: IXGBE_VF_SET_MAC_ADDR (요청 MAC: 52:54:00:11:22:33)

[ Step 2: VF Trigger ]
  VF가 VFMAILBOX 제어 레지스터의 VF_REQ(Request) 비트를 1로 설정
  -> 하드웨어가 호스트 PF에게 MSI-X 메일박스 인터럽트(PFMBICR) 발생

[ Step 3: PF Validation ]
  PF 인터럽트 핸들러가 깨어나 공유 메모리에서 메시지 파싱
  보안 정책 검증 (Admin Locked MAC 여부, Spoofcheck, Trust Mode)

[ Step 4: PF Reply ]
  PF가 결과를 버퍼에 기록 (ACK/NACK, 에러 코드)
  PFMAILBOX[vf] 레지스터의 PF_ACK 비트를 설정
  -> VF에게 응답 MSI-X 인터럽트가 전달되어 핸드셰이크 완료
```

---

## 4. SR-IOV 보안 아키텍처: Spoofcheck와 Trust Mode

### 4.1 안티 스푸핑 (Spoofcheck)
- `ip link set eth0 vf 0 spoofchk on`
- 악의적인 VM이 ARP 스푸핑(ARP Spoofing)이나 IP/MAC 위조 패킷을 방출하여 네트워크를 교란하는 것을 하드웨어 계층에서 원천 봉쇄합니다.
- PF는 VF의 송신 패킷 L2 헤더를 실시간 ASIC 필터로 감시하여, 사전에 등록된 관리자 MAC과 일치하지 않는 프레임을 0.1나노초 단위로 드롭합니다.

### 4.2 신뢰 모드 (Trust Mode)
- 기본적으로 VF는 **비신뢰(Untrusted)** 상태입니다.
  - 비신뢰 VF는 프로미스큐어스 모드(Promiscuous Mode)를 켤 수 없습니다. (동일 물리 포트의 다른 VF 및 호스트 트래픽을 도청할 수 없음)
  - 관리자가 사전에 할당한 MAC 주소나 VLAN 태그를 임의로 변경할 수 없습니다.
- 반면 방화벽 VM, 가상 라우터(vRouter), 침입 탐지 시스템(IDS)처럼 전 트래픽을 수신해야 하는 특수 워크로드의 경우, 관리자가 명시적으로 `trust on`을 설정할 때만 권한 있는 메일박스 제어가 허용됩니다.

### 4.3 메일박스 인터럽트 DoS 플러딩 방어
- 가상 머신 내부의 손상된 드라이버가 무한 루프로 `VF_RESET` 또는 `VF_SET_MAC`을 호출하면 호스트 CPU가 인터럽트 처리에 과부하되어 DoS 상태에 빠질 수 있습니다.
- 최신 리눅스 커널은 VF별 메일박스 요청 레이트 리미팅(Rate Limiting)을 적용하여 임계치 초과 요청을 즉각 `-EBUSY`로 완화합니다.

---

## 5. 실무 클라우드 및 텔코(NFV) 구축 모범 사례

1. **Kubernetes SR-IOV Network Device Plugin & CNI**:
   - 컨테이너 Pod에 물리 VF 인터페이스를 직접 주입하여 초고속 데이터 플레인(DPDK 패킷 처리)을 구축할 때 사용됩니다.
2. **OpenStack Nova & Neutron SR-IOV 포트 바인딩**:
   - `direct` 포트 바인딩 시 호스트 PF의 보안 그룹과 스푸프체크 정책을 동기화하여 다중 테넌트 격리를 보장합니다.
3. **Mellanox ASAP² (Accelerated Switch and Packet Processing)**:
   - SR-IOV VF와 OVS 하드웨어 오프로드(eSwitch)를 결합하여, 메일박스 프로토콜의 엄격한 제어 하에 초당 1억 개 이상의 패킷을 와이어 스피드로 처리합니다.
