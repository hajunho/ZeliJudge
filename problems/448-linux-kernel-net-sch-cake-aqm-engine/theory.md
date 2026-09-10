# 심층 시스템 이론: 리눅스 커널 CAKE Qdisc (`net/sched/sch_cake.c`) 및 차세대 능동적 대기열 관리 아키텍처

## 1. 버퍼블로트(Bufferbloat) 현상과 큐잉 메커니즘의 한계

전통적인 네트워크 라우터 및 스위치는 패킷 유실(Drop)을 방지하기 위해 인터페이스 큐의 크기를 수 메가바이트(수백~수천 패킷) 수준으로 과도하게 설정해 두었습니다. 이를 **버퍼블로트(Bufferbloat)**라 부릅니다.

### 1) 테일 드롭(Tail Drop) FIFO의 파멸적 결과
- 대용량 파일 전송(TCP CUBIC 등)은 링크 용량을 채울 때까지 윈도우 크기를 계속 증가시킵니다.
- 병목 링크(Bottleneck Link)의 대형 버퍼가 100% 가득 차기 전까지는 패킷 유실이 발생하지 않으므로 TCP 송신자는 속도를 줄이지 않습니다.
- 그 결과, 버퍼 내에 패킷 체류 지연(Sojourn Latency)이 수백 밀리초(최대 수 초)에 달하게 됩니다.
- 실시간 트래픽(VoIP 음성 패킷, 화상 통화, 게임 패킷)이 거대한 다운로드 패킷들의 뒤에 갇혀 지연 시간이 폭증합니다.

### 2) FQ-CoDel의 등장과 한계
- 리눅스 3.5에 도입된 FQ-CoDel(`sch_fq_codel`)은 플로우 공정 큐잉(Fair Queueing)과 CoDel 능동적 대기열 관리를 결합하여 버퍼블로트를 획기적으로 완화했습니다.
- 그러나 FQ-CoDel은:
  1. 플로우 해시 충돌(Hash Collisions) 시 두 플로우가 운명을 공유하는 문제,
  2. 음성/영상 등 멀티미디어 패킷에 대한 DiffServ 우선순위 처리의 부재,
  3. 비대칭 회선에서 순수 TCP ACK로 인한 업링크 고갈 문제를 해결하지 못했습니다.

---

## 2. CAKE(Common Applications Kept Enhanced)의 핵심 아키텍처

CAKE는 리눅스 커널 4.19에 공식 머지되었으며(`net/sched/sch_cake.c`), 네트워크 에지 및 가정용 라우터 환경에 최적화된 올인원 트래픽 제어 시스템입니다.

### 1) DiffServ 멀티-틴(Tin) 계층 구조
CAKE는 전송 계층의 패킷을 4가지 클래스(Tin)로 물리적으로 분리합니다:
1. **Voice (Tin 3)**: DSCP EF(46), CS5, CS6 등 초저지연 패킷. VoIP, DNS, 온라인 게임.
2. **Video (Tin 2)**: DSCP CS4, AF41, CS3 등 반응형 스트리밍 트래픽.
3. **Best Effort (Tin 1)**: 기본 인터넷 웹 서핑, 일반 트래픽.
4. **Bulk (Tin 0)**: DSCP CS1, 토렌트, 백그라운드 클라우드 동기화 트래픽.

틴 간의 스케줄링은 우선순위 및 대역폭 가중치 기반 Deficit Round Robin(DRR)을 통해 이루어지며, Voice 트래픽은 상시 최우선 디큐 권한을 가집니다.

### 2) 8-Way 세트 연관 플로우 격리 (Set-Associative Flow Hashing)
기존 FQ-CoDel이 1024개의 버킷을 단순 해시 매핑했던 것과 달리, CAKE는 CPU L1/L2 캐시의 아키텍처를 차용하여 **128 세트 × 8 웨이(총 1024 큐)** 구조를 채택했습니다:
$$\text{set} = \text{hash}(\text{5-tuple}) \pmod{128}$$
- 동일 세트 내에서 빈 슬롯(Way)이나 비활성 슬롯을 우선 할당하므로, 2개 이상의 플로우가 동일한 해시 버킷을 강제로 공유하는 **해시 충돌 확률을 99% 이상 제거**합니다.

---

## 3. TCP ACK 필터링 알고리즘 (`cake_ack_filter`)

비대칭 접속망(예: 1000Mbps 다운로드 / 50Mbps 업로드)에서 대용량 다운로드를 수행하면 초당 수만 개의 순수 TCP ACK(Pure ACK, 54~64바이트) 패킷이 업링크로 쏟아집니다.

```
Downlink (1 Gbps)  ──[Data Segments]──> Client
                                           │
                                       Pure ACKs
                                           │
                                           ▼
Uplink (50 Mbps)   <──[ACK Filter]────── Client Router
                        (구형 ACK 폐기)
```

### 1) 순수 TCP ACK의 누적 속성 (Cumulative ACK Property)
TCP의 ACK 번호는 누적 확인 응답(Cumulative Acknowledgment)이므로, 시퀀스 번호 10,000에 대한 ACK는 이미 1,000부터 9,000까지의 모든 데이터가 정상 수신되었음을 내포합니다.
- 만약 라우터의 송신 큐에 ACK 5,000이 대기 중인데, 뒤이어 ACK 10,000이 들어왔다면 앞선 ACK 5,000은 이미 전송할 가치를 상실한 **잉여 패킷(Redundant Packet)**입니다.
- CAKE는 큐 내부를 고속 검사하여 동일 플로우의 더 낮은 ACK 번호를 가진 순수 ACK를 발견 즉시 폐기(Drop)합니다.
- **결과**: 업링크 버퍼 공간의 30~50%가 즉각 회수되며, 업링크 혼잡으로 인한 다운로드 속도 저하 현상이 완벽히 해소됩니다.

---

## 4. CoDel AQM 및 ECN CE 마킹

각 플로우 큐는 독립적인 CoDel(Controlled Delay) 상태 머신을 구동합니다:

### 1) 체류 지연 시간(Sojourn Latency) 감시
패킷이 큐에 머무는 시간:
$$t_{\text{sojourn}} = t_{\text{dequeue}} - t_{\text{enqueue}}$$
- $t_{\text{sojourn}} \le \text{target}$ (기본 5ms)인 경우: 일시적 버스트(Good Queue)로 간주하고 어떠한 조치도 취하지 않음.
- $t_{\text{sojourn}} > \text{target}$ 상태가 $\text{interval}$ (기본 100ms) 이상 지속되는 경우: 지속적 버퍼블로트(Bad Queue)로 확정하고 `dropping` 상태로 진입.

### 2) ECN(Explicit Congestion Notification) 처리
- 패킷 IP 헤더의 ECN 필드가 ECT(0) 또는 ECT(1)로 설정된 경우:
  패킷을 버리지 않고 **CE(Congestion Experienced, 11b)** 비트로 재작성(Marking)하여 게스트/서버 TCP 스택이 패킷 손실 없이 송신 속도를 자발적으로 감속하도록 유도합니다.
- ECN 미지원 패킷인 경우에만 패킷을 물리적으로 폐기(`AQM_DROPPED`)하여 버퍼블로트를 강제 해소합니다.

---

## 5. 결론

CAKE는 리눅스 커널의 네트워크 스케줄러 역사상 가장 실용적이고 고도화된 안티-버퍼블로트 솔루션입니다.
복잡한 수동 튜닝 없이도 멀티미디어 트래픽 우선권 보장, 플로우 간 절대적 공정성, 비대칭 업링크 ACK 폭풍 방어, 초저지연 버퍼 제어를 모두 단일 Qdisc 수준에서 완벽하게 통합 제공합니다.
