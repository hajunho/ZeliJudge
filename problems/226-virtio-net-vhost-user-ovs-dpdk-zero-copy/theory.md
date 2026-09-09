# 문제 226 이론: 리눅스 커널 가상화 네트워크 I/O 아키텍처와 DPDK 제로카피 공유 메모리 심층 분석

## 1. 하드웨어 가상화와 VM-Exit 오버헤드의 본질

Intel VT-x 및 AMD-V와 같은 CPU 하드웨어 가상화 환경에서 가상머신(Guest OS)은 **VMX Non-Root 모드**에서 실행되고, 하이퍼바이저(KVM)는 **VMX Root 모드**에서 실행됩니다.
게스트 OS의 가상 드라이버가 물리 I/O(예: NIC 레지스터 쓰기, MMIO, Port I/O `out` 명령어)를 시도하면, 하드웨어는 CPU 제어권을 하이퍼바이저로 강제 전환하며 이를 **VM-Exit**이라고 합니다.

```
[Hardware Virtualization Execution Modes]
+-------------------------------------------------------------+
| VMX Root Mode (Host Kernel / KVM)                           |
|   ^                                                     |   |
|   | (VM-Exit: Save Guest CPU State, Flush TLB, Trap)    |   |
|   |                                                     v   |
|   | (VM-Entry: Restore Guest CPU State, VMLAUNCH/VMRESUME)  |
+---+---------------------------------------------------------+
| VMX Non-Root Mode (Guest VM / VirtIO Driver)                |
+-------------------------------------------------------------+
```

### VM-Exit의 비용
- **하드웨어 컨텍스트 스위치**: 게스트 vCPU 레지스터(GPR, CR3, DR7, EPT 포인터 등)를 VMCS(Virtual Machine Control Structure)에 덤프하고, 호스트 레지스터를 복원하는 하드웨어 마이크로코드 동작에만 800~1,500 사이클이 소모됩니다.
- **CPU 파이프라인 및 TLB 플러시**: 분기 예측 버퍼(BTB) 무효화 및 캐시 미스로 인해 VM-Exit 1회당 약 **1.2 ~ 2.5 마이크로초($\mu\text{s}$)**의 CPU 시간 손실이 발생합니다.
- 패킷당 1회의 VM-Exit이 발생한다면, 단 1 Mpps(초당 100만 패킷)를 처리하는 데 CPU 코어 1개가 100% 포화되어 물리적으로 더 이상의 패킷 처리가 불가능해집니다.

---

## 2. 가상 네트워크 장치 아키텍처의 3단계 진화

```
+----------------------------------------------------------------------------------------------------+
| 1세대: Pure VirtIO-Net (QEMU Userspace Emulation)                                                  |
| Guest -> Virtqueue -> VM-Exit (I/O Trap) -> KVM -> eventfd -> QEMU Thread -> TAP Device            |
| (한계: 대규모 VM-Exit 발생, QEMU 프로세스 컨텍스트 스위칭, 0.7~0.9 Mpps 한계)                           |
+----------------------------------------------------------------------------------------------------+
| 2세대: vhost-net (Host Kernel Worker In-Tree Acceleration)                                         |
| Guest -> Virtqueue -> VM-Exit -> KVM -> irqfd -> [vhost-worker 커널 스레드] -> TAP Device          |
| (개선: QEMU 유저스페이스 우회, 한계: 여전히 VM-Exit 및 리눅스 SoftIRQ 인터럽트 스택 오버헤드, 2.8~3.5 Mpps)   |
+----------------------------------------------------------------------------------------------------+
| 3세대: vhost-user & OVS-DPDK (Kernel-Bypass & Hugepages Zero-Copy)                                |
| Guest Userspace (DPDK) <=== [공유 Hugepages vring (Desc/Avail/Used)] ===> OVS-DPDK PMD Core        |
| (혁신: VM-Exit 0회, 시스템 콜 0회, 인터럽트 0회, 메모리 복사 0회, 10 Mpps+ 초당 천만 패킷 극초저지연)      |
+----------------------------------------------------------------------------------------------------+
```

### 2.1 Virtqueue (vring) 내부 구조
VirtIO의 핵심 데이터 구조인 Virtqueue는 3개의 연속된 메모리 링 버퍼로 구성됩니다:
1. **디스크립터 테이블 (Descriptor Table)**: 물리 메모리 버퍼 주소(`addr`), 길이(`len`), 플래그(`flags: NEXT, WRITE`) 및 다음 인덱스 체인 저장.
2. **사용 가능 링 (Available Ring)**: 게스트 드라이버가 호스트/디바이스에게 처리를 요청하기 위해 준비한 디스크립터 체인의 헤드 인덱스들을 기록 (`avail->ring[]`, `avail->idx`).
3. **사용 완료 링 (Used Ring)**: 호스트/디바이스가 패킷 송수신 처리를 완료한 후 게스트에게 반환하는 디스크립터 인덱스 및 수신 바이트 수 기록 (`used->ring[]`, `used->idx`).

### 2.2 vhost-user 프로토콜과 공유 메모리 메커니즘
`vhost-user`는 QEMU와 외부 유저스페이스 프로세스(예: OVS-DPDK, SPDK, Snabb) 간에 협력하는 프로토콜입니다:
- **제어 평면 (Control Plane)**: UNIX Domain Socket을 통해 Virtqueue 메모리 매핑 정보(`VHOST_USER_SET_MEM_TABLE`)와 링 오프셋(`VHOST_USER_SET_VRING_ADDR`)을 교환합니다.
- **데이터 평면 (Data Plane)**: 파일 디스크립터(`memfd` 또는 `hugetlbfs`) 전달(`SCM_RIGHTS`)을 통해 게스트의 물리 메모리 전체를 호스트의 OVS-DPDK 프로세스 가상 메모리 공간에 `mmap()`으로 직접 매핑합니다.
- 송수신 시 패킷 복사 없이 오직 디스크립터 포인터만 교환(Zero-Copy)됩니다.

---

## 3. DPDK PMD (Poll Mode Driver)의 트레이드오프

### 3.1 100% CPU 스핀 vs 폴링 효율
DPDK의 핵심 설계는 **인터럽트 제거**입니다. 하드웨어 인터럽트가 발생하면 OS는 레지스터를 저장하고 ISR $\rightarrow$ SoftIRQ(NAPI) $\rightarrow$ 소켓 버퍼(`sk_buff`) 할당 과정을 거치는데, 이는 수백 나노초의 지연을 수반합니다.
DPDK PMD 코어는 전용 루프(`while(1)`)에서 Virtqueue를 연속 폴링하여 인터럽트 없이 극초저지연(3$\mu\text{s}$ 이하)을 달성합니다.

### 3.2 유휴 전력 낭비와 적응형 폴링 (Adaptive Polling)
- **문제점**: 트래픽이 전혀 없는 한밤중이나 유휴 시간대에도 PMD 코어는 100% 풀 클록으로 회전하므로 엄청난 전력(TDP)과 발열이 낭비됩니다.
- **해결책 (Adaptive Power Management)**:
  - 연속 빈 큐(Empty Poll) 횟수가 임계치(예: 1,000회)를 넘어서면, CPU 전력 절약 명령어(`PAUSE`, `UMWAIT`, `TPAUSE`)를 호출하여 클록을 낮춥니다.
  - 장기 유휴 상태에서는 인터럽트 모드(`epoll` / `eventfd`)로 전환하여 스레드를 블록(Sleep)시키고, 새 패킷 유입 시 인터럽트를 통해 즉각 PMD 폴링 모드로 복귀합니다.

---

## 4. 성능 최적화 파라미터 가이드

| 구성 요소 | 최적 권장 설정 | 주의점 및 장애 징후 |
| :--- | :--- | :--- |
| **Hugepages** | 1GB Hugepages (`default_hugepagesz=1G`) | 미설정 시 TLB 미스 폭증 및 DPDK 공유 메모리 할당 실패 |
| **vring Queue Size** | 1024 ~ 2048 디스크립터 | 256 이하 사용 시 트래픽 버스트 발생 순간 링 오버플로우 패킷 유실 |
| **PMD Core 할당** | 트래픽 5 Mpps당 격리된 전용 1 Core (`isolcpus`, `nohz_full`) | 다른 OS 프로세스와 코어 공유 시 지연시간 테일(Tail Latency) 스파이크 |
| **배치 크기 (Burst)** | 32 또는 64 패킷 단위 (`rte_eth_rx_burst(..., 32)`) | 배치 크기가 1이면 메모리 장벽(Memory Barrier) 동기화 오버헤드 과다 |
