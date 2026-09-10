# 심층 시스템 이론: 리눅스 커널 RPS/RFS 패킷 스티어링 (`net/core/dev.c`) 및 CPU 캐시 국소성 최적화 아키텍처

## 1. 물리 네트워크 인터럽트와 CPU 아키텍처의 불일치

현대 멀티소켓 NUMA 서버에서 100GbE 네트워크 패킷 수신은 다음과 같은 치명적인 캐시 비효율성을 안고 있습니다.

### 1) 단일 큐 NIC 및 인터럽트 편향
- NIC의 하드웨어 인터럽트 라인(MSI-X)은 IRQ affinity 설정에 의해 특정 CPU 코어(예: Core 0)에 고정됩니다.
- 패킷 수신이 발생하면 Core 0의 드라이버가 DMA 디스크립터에서 `sk_buff`를 꺼내 `NET_RX_SOFTIRQ`를 실행합니다.
- 그러나 해당 TCP 연결의 데이터를 읽어가는 사용자 애플리케이션(Nginx 워커, Redis 스레드)은 Core 3이나 다른 NUMA 노드의 Core 15에서 실행 중일 수 있습니다.

### 2) 캐시라인 바운싱(Cacheline Bouncing) 오버헤드
- Core 0이 패킷 헤더와 페이로드를 파싱하면서 해당 메모리 주소들이 Core 0의 L1/L2 캐시에 적재됩니다.
- 직후 Core 3의 사용자 스레드가 `recvmsg()` 시스템 콜을 호출하여 소켓 수신 버퍼에서 데이터를 복사하려고 시도하면, 하드웨어 인터커넥트(QPI/UPI, Infinity Fabric)를 통해 Core 0의 캐시로부터 라인을 강제로 무효화하고 전송받아야 합니다.
- 이로 인해 메모리 버스 트래픽이 폭증하고, 패킷당 최대 수백 나노초의 지연이 누적되어 시스템 전체의 네트워크 처리량이 40% 이상 격감합니다.

---

## 2. RPS (Receive Packet Steering) 아키텍처

Google에 의해 제안되어 리눅스 커널 2.6.35에 도입된 RPS는 **소프트웨어 에뮬레이션 RSS**입니다.

```c
static int get_rps_cpu(struct net_device *dev, struct sk_buff *skb,
                       struct rps_dev_flow **rflowp);
```

1. **해시 추출**: NIC 하드웨어 해시(RSS Toeplitz 해시)를 재사용하거나 소프트웨어 4-튜플(Jenkins 해시)을 계산.
2. **CPU 매핑**: 관리자가 `/sys/class/net/<iface>/queues/rx-0/rps_cpus`에 설정한 비트마스크(`rps_map`)를 참조하여 대상 코어 선정:
   $$\text{target\_cpu} = \text{rps\_map}->\text{cpus}[\text{hash} \pmod{\text{len}}]$$
3. **백로그 큐잉 및 IPI**: 패킷을 대상 코어의 `softnet_data.input_pkt_queue`에 밀어 넣고, 비동기 IPI(`smp_call_function_single_async`)를 전송하여 대상 코어의 NAPI 폴링 루프(`process_backlog`)를 깨웁니다.

---

## 3. RFS (Receive Flow Steering) 및 소켓 플로우 테이블

RPS가 해시값을 기준으로 CPU 코어를 무작위로 분산시킬 뿐 실제 애플리케이션의 위치를 모른다는 한계를 극복하기 위해 **RFS**가 개발되었습니다.

```
                  User Application (Core 2)
                             │
                      recvmsg() 시스템 콜
                             │
                             ▼
  [Global rps_sock_flow_table] ──> (Hash 0x1234 -> Core 2)
                             ▲
                             │ RFS 룩업
                             │
         NIC Driver: Ingress Packet (Hash 0x1234)
                             │
                             ▼
              Target CPU = Core 2 (Direct Steering!)
```

### 1) 이중 플로우 테이블 (Dual-Table Architecture)
- **`rps_sock_flow_table` (전역 테이블)**:
  애플리케이션이 소켓 읽기(`sock_recvmsg`, `inet_recvmsg`)를 수행할 때마다 커널은 현재 실행 중인 CPU 번호(`smp_processor_id()`)를 해당 소켓의 플로우 해시 슬롯에 원자적으로 기록합니다.
- **`rps_dev_flow_table` (디바이스별 테이블)**:
  수신 경로에서 사용되며, 각 플로우가 마지막으로 스티어링된 CPU와 해당 CPU의 백로그 큐 테일 카운터(`last_qtail`)를 기록합니다.

---

## 4. 패킷 역전 방어 장벽 (Out-of-Order Barrier)

만약 OS 스케줄러가 부하 분산을 위해 Nginx 워커 프로세스를 Core 2에서 Core 3으로 마이그레이션했다고 가정해 봅시다.

1. **즉시 전환의 위험**:
   만약 RFS가 즉시 신규 패킷을 Core 3으로 보내기 시작하면, Core 2의 백로그 큐에 여전히 대기 중이던 이전 패킷들보다 Core 3의 신규 패킷이 먼저 TCP 스택에 도달할 수 있습니다.
   이는 심각한 **TCP 패킷 역전(Out-of-Order)**을 유발하여 불필요한 Duplicate ACK 및 가짜 고속 재전송(Spurious Fast Retransmit)을 일으키고 윈도우를 반토막 냅니다.
2. **배리어 검증 공식**:
   RFS는 디바이스 플로우 테이블의 `last_qtail`을 검사합니다:
   $$\text{cpu\_processed}[\text{old\_cpu}] \ge \text{last\_qtail}$$
   - Core 2가 과거에 적재된 패킷들을 완전히 드레인하기 전까지는, 신규 패킷도 Core 2로 계속 전송됩니다 (`RFS_DRAIN_HOLD`).
   - Core 2의 큐가 완전히 비워진 것이 확인된 순간 비로소 Core 3으로 플로우를 안전하게 전환합니다.

---

## 5. 결론

RPS와 RFS는 하드웨어 인터럽트의 물리적 불균형과 멀티코어 캐시 비효율성을 소프트웨어 계층에서 완벽히 조율하는 현대 리눅스 네트워킹 스택의 핵심 고속화 엔진입니다.
