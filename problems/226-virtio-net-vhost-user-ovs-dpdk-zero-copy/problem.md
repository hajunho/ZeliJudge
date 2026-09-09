# 문제 226: 가상화 네트워크 I/O 병목: VirtIO-Net VM-Exit 트랩 vs vhost-net vs vhost-user & OVS-DPDK 제로카피 공유 링 시뮬레이터

## 1. 개요 및 배경 (Incident Scenario)

대규모 클라우드 통신사(Telco)의 5G 코어 UPF(User Plane Function) 및 KubeVirt 기반 가상화 네트워크 기능(NFV) 클러스터에서 심각한 패킷 드롭 및 지연 장애가 발생했습니다. 실시간 음성 통화(VoIP) 및 초저지연 IoT 트래픽이 폭증하는 시간대에 가상머신(VM)으로 초당 250만 패킷(2.5 Mpps, 64바이트 소형 패킷)이 유입되었으나, VM 내부 애플리케이션에 도달한 패킷은 0.68 Mpps에 불과했고 73% 이상의 패킷이 가상 네트워크 인터페이스에서 무더기로 드롭(`PURE_VIRTIO_VM_EXIT_IO_TRAP_BOTTLENECK`)되었습니다.

호스트 노드의 CPU 사용률은 100%를 찍었으나 실제 네트워크 처리량이 아닌 **KVM 하이퍼바이저의 가상머신 트랩(VM-Exit / VM-Entry) 오버헤드**로 인해 CPU 사이클의 90% 이상이 낭비되고 있었습니다.

원인 분석 결과, 기존 시스템은 QEMU 유저스페이스 에뮬레이션 기반의 전통적인 **순수 VirtIO-Net** 드라이버를 사용하고 있었습니다:
1. **순수 VirtIO-Net의 한계**: 게스트 OS가 패킷을 Virtqueue(vring)에 넣고 통지(Kick)할 때마다 하드웨어 레벨의 VM-Exit(PIO/MMIO 트랩)이 발생합니다. VMX Non-Root 모드에서 Root 모드로 전환되는 컨텍스트 스위칭 비용(회당 약 1,200~2,500ns)과 QEMU 유저스페이스 프로세스로의 eventfd 시그널링 오버헤드로 인해, 단일 큐 처리량이 0.7~0.9 Mpps에서 물리적 벽에 부딪힙니다.
2. **커널 인트리 vhost-net 가속**: QEMU 유저스페이스를 건너뛰고 호스트 리눅스 커널 내부의 전용 워커 스레드(`vhost-worker`)가 링 버퍼를 직접 처리합니다. 그러나 링 버퍼 크기(`queue_size`)가 256 등 협소하면 트래픽 버스트 시 링 오버플로우 패킷 드롭(`VHOST_NET_RING_OVERFLOW_PACKET_DROP`)이 발생하며, 2.8~3.5 Mpps를 초과하는 회선 속도에서는 커널 인터럽트 처리 한계로 포화(`VHOST_NET_KERNEL_WORKER_SATURATION`)됩니다.
3. **vhost-user & OVS-DPDK 제로카피 아키텍처**: 커널을 완전히 바이패스(Kernel-Bypass)하고 유저스페이스 가상 스위치(OVS-DPDK)와 게스트 VM 간에 **1GB/2MB Hugepages(거대 페이지)** 기반 공유 메모리 링(vring)을 구성합니다. PMD(Poll Mode Driver) 워커 코어가 링을 락프리(Lock-Free)로 무한 폴링하여 **VM-Exit 0회, 인터럽트 0회, 메모리 복사 0회(Zero-Copy)**로 초당 1,000만 패킷(10 Mpps) 이상을 3.2μs 초저지연으로 완벽 처리(`OPTIMAL_VHOST_USER_DPDK_ZERO_COPY`)합니다.
   - 단, DPDK 구동 시 Hugepages가 비활성화되어 있으면 공유 메모리 할당 불가(`DPDK_HUGEPAGES_DISABLED_ALLOCATION_FAILURE`)로 기동 실패합니다.
   - 워크로드 대비 PMD 전용 코어가 부족하면 대기열 큐잉으로 인해 패킷 유실(`DPDK_PMD_CORE_STARVATION`)이 발생합니다.
   - 트래픽이 없는 유휴(IDLE) 시간대에도 PMD가 100% CPU 풀 스핀을 지속하면 심각한 전력 낭비(`DPDK_IDLE_CPU_SPIN_ENERGY_WASTE`)가 초래되므로, 적응형 인터럽트/에폭 수면 모드(`DPDK_ADAPTIVE_POLL_POWER_OPTIMIZED`)로 전환되어야 합니다.

본 문제에서는 가상화 네트워크 드라이버(VirtIO-Net, vhost-net, vhost-user DPDK) 및 패킷 워크로드에 따른 처리량, 지연시간, VM-Exit 횟수, CPU 점유율을 시뮬레이션하고 최적 아키텍처를 진단하는 프로그램을 구현합니다.

---

## 2. 가상화 네트워크 드라이버 아키텍처 비교

```
1. [Pure VirtIO-Net (QEMU Userspace Emulation)]
Guest App -> Virtqueue Kick -> [VM-EXIT Trap (1500ns)] -> KVM Kernel -> eventfd -> QEMU Userspace -> TAP Device
=> Bottleneck: Massive VM-Exit CPU trap overhead & Context Switches (~0.8 Mpps limit)

2. [vhost-net (Host Kernel In-Tree Acceleration)]
Guest App -> Virtqueue Kick -> [VM-EXIT Trap] -> KVM Kernel -> irqfd -> [vhost-worker thread in Kernel] -> TAP
=> Skips QEMU userspace, but still constrained by VM-Exits and Kernel SoftIRQ interrupts (~3 Mpps)

3. [vhost-user & OVS-DPDK (Kernel-Bypass Zero-Copy)]
Guest App -> Shared Hugepages Virtqueue (vring) <=================> OVS-DPDK PMD Poll Thread
=> ZERO VM-Exits! ZERO System Calls! ZERO Memory Copies! Continuous PMD Polling (8~10+ Mpps)
```

---

## 3. 입력 형식 (Input Specification)

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "config": {
    "driver_type": "VHOST_USER_DPDK",
    "queue_size": 1024,
    "hugepages_enabled": true,
    "pmd_cores": 2,
    "adaptive_interrupt_enabled": false,
    "target_sla_drop_rate": 0.001
  },
  "workload": {
    "packet_rate_mpps": 8.0,
    "packet_size_bytes": 64,
    "traffic_profile": "ACTIVE"
  }
}
```

- `config`:
  - `driver_type`: `"VIRTIO_NET"`, `"VHOST_NET"`, `"VHOST_USER_DPDK"` 중 하나
  - `queue_size`: Virtqueue 디스크립터 링 크기 (256, 512, 1024 등)
  - `hugepages_enabled`: 호스트/게스트 공유 Hugepages(거대 페이지) 활성화 여부 (boolean)
  - `pmd_cores`: DPDK PMD(Poll Mode Driver) 전용 CPU 코어 수 (기본 1)
  - `adaptive_interrupt_enabled`: 유휴 시 적응형 인터럽트/수면 전환 지원 여부 (boolean)
  - `target_sla_drop_rate`: 허용 최대 패킷 손실률 (기본 0.001, 즉 0.1%)
- `workload`:
  - `packet_rate_mpps`: 유입 패킷 전송률 (단위: Million Packets Per Second, Mpps)
  - `packet_size_bytes`: 패킷 바이트 크기 (기본 64바이트)
  - `traffic_profile`: 트래픽 유형 (`"ACTIVE"` 또는 `"IDLE"`)

---

## 4. 연산 및 시뮬레이션 공식

1. **대역폭(Gbps) 환산 공식**:
   - 이더넷 프레임 오버헤드(Preamble 8B, Inter-Packet Gap 12B 등 20B) 포함:
     $$\text{throughput\_gbps} = \frac{\text{actual\_throughput\_mpps} \times 10^6 \times (\text{packet\_size\_bytes} + 20) \times 8}{10^9}$$
2. **순수 VirtIO-Net (VIRTIO_NET)**:
   - 최대 처리 용량: $\text{max\_capacity\_mpps} = 0.9 \times (1.0 \text{ if } \text{queue\_size} \ge 512 \text{ else } 0.75)$
   - VM-Exit 발생 횟수 (8개 패킷 배치 처리 가정):
     $$\text{vm\_exits\_per\_sec} = \lfloor \frac{\min(\text{packet\_rate\_mpps}, \text{max\_capacity\_mpps}) \times 10^6}{8} \rfloor$$
   - 손실률: $\text{drop\_rate} = \frac{\max(0, \text{packet\_rate\_mpps} - \text{max\_capacity\_mpps})}{\text{packet\_rate\_mpps}}$
   - 실제 처리량: $\text{actual\_throughput\_mpps} = \min(\text{packet\_rate\_mpps}, \text{max\_capacity\_mpps})$
   - 지연시간: $\text{avg\_latency\_us} = 45.0 + 30.0 \times \left(\frac{\text{packet\_rate\_mpps}}{\text{max\_capacity\_mpps}}\right)$
   - CPU 사용률: $\text{cpu\_utilization\_pct} = \min(100.0, \frac{\text{packet\_rate\_mpps}}{\text{max\_capacity\_mpps}} \times 98.0)$
   - $\text{drop\_rate} > \text{target\_sla\_drop\_rate}$ 이면 `PURE_VIRTIO_VM_EXIT_IO_TRAP_BOTTLENECK` 판정.
3. **커널 인트리 가속 (VHOST_NET)**:
   - 최대 처리 용량:
     $$\text{mult} = 1.2 \text{ (queue} \ge 1024) \text{ else } 1.0 \text{ (queue} \ge 512) \text{ else } 0.7$$
     $$\text{max\_capacity\_mpps} = 2.8 \times \text{mult}$$
   - VM-Exit 발생 횟수 (32개 배치):
     $$\text{vm\_exits\_per\_sec} = \lfloor \frac{\min(\text{packet\_rate\_mpps}, \text{max\_capacity\_mpps}) \times 10^6}{32} \rfloor$$
   - 링 크기 512 미만이고 패킷 전송률 > 2.0 Mpps인 경우:
     - 링 버퍼 오버플로우 발생: $\text{actual\_throughput\_mpps} = \text{max\_capacity\_mpps} \times 0.7$
     - $\text{drop\_rate} = \frac{\text{packet\_rate\_mpps} - \text{actual\_throughput\_mpps}}{\text{packet\_rate\_mpps}}$
     - $\text{avg\_latency\_us} = 25.0$, `status`: `"FAILED"`, `verdict`: `"VHOST_NET_RING_OVERFLOW_PACKET_DROP"`
   - 그 외 용량 초과 시: `VHOST_NET_KERNEL_WORKER_SATURATION` (FAILED)
   - 정상 수용 시: $\text{avg\_latency\_us} = 12.0$, `VHOST_NET_STABLE_FORWARDING` (SUCCESS)
4. **유저스페이스 커널 바이패스 (VHOST_USER_DPDK)**:
   - `hugepages_enabled == False`인 경우:
     - 메모리 할당 실패로 즉시 종료: `DPDK_HUGEPAGES_DISABLED_ALLOCATION_FAILURE` (`status`: `"FAILED"`, `drop_rate`: 1.0, 나머지 메트릭 0)
   - 코어당 용량: $\text{cap\_core} = 5.5 \times (1.15 \text{ if } \text{queue} \ge 1024 \text{ else } 1.0)$ Mpps
   - 총 용량: $\text{total\_capacity\_mpps} = \text{pmd\_cores} \times \text{cap\_core}$
   - $\text{vm\_exits\_per\_sec} = 0$ (Zero VM-Exits)
   - `traffic_profile == "IDLE"`인 경우:
     - `adaptive_interrupt_enabled == False`:
       - `status`: `"WARNING"`, `verdict`: `"DPDK_IDLE_CPU_SPIN_ENERGY_WASTE"`, $\text{cpu\_utilization\_pct} = 100.0$, $\text{avg\_latency\_us} = 2.1$
     - `adaptive_interrupt_enabled == True`:
       - `status`: `"SUCCESS"`, `verdict`: `"DPDK_ADAPTIVE_POLL_POWER_OPTIMIZED"`, $\text{cpu\_utilization\_pct} = 3.5$, $\text{avg\_latency\_us} = 8.5$
   - `traffic_profile == "ACTIVE"`인 경우:
     - $\text{packet\_rate\_mpps} > \text{total\_capacity\_mpps}$:
       - `status`: `"FAILED"`, `verdict`: `"DPDK_PMD_CORE_STARVATION"`, $\text{cpu\_utilization\_pct} = 100.0$, $\text{avg\_latency\_us} = 15.0$
     - 정상 처리 시:
       - `status`: `"SUCCESS"`, `verdict`: `"OPTIMAL_VHOST_USER_DPDK_ZERO_COPY"`, $\text{drop\_rate} = 0.0$, $\text{avg\_latency\_us} = 3.2$, $\text{cpu\_utilization\_pct} = \min(100.0, \frac{\text{packet\_rate\_mpps}}{\text{total\_capacity\_mpps}} \times 100.0)$

---

## 5. 진단 판정 (Verdict Rules) 요약

| 상태 (`status`) | 진단 결과 (`verdict`) | 발생 조건 |
| :--- | :--- | :--- |
| `FAILED` | `PURE_VIRTIO_VM_EXIT_IO_TRAP_BOTTLENECK` | VirtIO-Net에서 VM-Exit 트랩으로 인한 SLA 손실률 초과 |
| `FAILED` | `VHOST_NET_RING_OVERFLOW_PACKET_DROP` | vhost-net에서 큐 크기 512 미만 버스트로 인한 링 오버플로우 |
| `FAILED` | `VHOST_NET_KERNEL_WORKER_SATURATION` | vhost-net 커널 워커의 대역폭 한계 초과 패킷 유실 |
| `FAILED` | `DPDK_HUGEPAGES_DISABLED_ALLOCATION_FAILURE` | DPDK 구동 시 필수 전제 조건인 거대 페이지(Hugepages) 부재 |
| `FAILED` | `DPDK_PMD_CORE_STARVATION` | DPDK 유입 트래픽이 할당된 PMD 워커 코어 처리 용량 초과 |
| `WARNING` | `DPDK_IDLE_CPU_SPIN_ENERGY_WASTE` | DPDK 유휴 상태에서 적응형 수면 미적용으로 100% CPU 전력 낭비 |
| `SUCCESS` | `DPDK_ADAPTIVE_POLL_POWER_OPTIMIZED` | DPDK 유휴 상태에서 적응형 인터럽트/수면 전환으로 저전력 달성 |
| `SUCCESS` | `OPTIMAL_VHOST_USER_DPDK_ZERO_COPY` | 제로카피 공유 링 기반 0 드롭, 0 VM-Exit 초고속 전송 달성 |
| `SUCCESS` | `VHOST_NET_STABLE_FORWARDING` | vhost-net 안정적 수용 범위 내 정상 포워딩 |
| `SUCCESS` | `STANDARD_VIRTIO_NET_SUCCESS` | 저부하 트래픽에 대한 표준 VirtIO-Net 정상 처리 |

---

## 6. 출력 형식 (Output Specification)

표준 출력(stdout)으로 다음 형식의 JSON 객체를 한 줄로 출력합니다:

```json
{
  "status": "SUCCESS",
  "verdict": "OPTIMAL_VHOST_USER_DPDK_ZERO_COPY",
  "metrics": {
    "driver_type": "VHOST_USER_DPDK",
    "actual_throughput_mpps": 8.0,
    "throughput_gbps": 5.38,
    "drop_rate": 0.0,
    "avg_latency_us": 3.2,
    "cpu_utilization_pct": 63.2,
    "vm_exits_per_sec": 0
  }
}
```
