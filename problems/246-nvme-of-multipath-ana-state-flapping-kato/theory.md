# Problem 246 Theory: NVMe-over-Fabrics (NVMe-oF) 아키텍처 심층 분석 — Asymmetric Namespace Access (ANA), 네이티브 멀티패스 및 KATO 튜닝

현대 데이터센터의 스토리지 에코시스템은 기존 SAS/SATA 및 파이버 채널(FC) SAN 기반에서, 마이크로초 단위 초저지연과 수백만 IOPS를 제공하는 **NVMe-over-Fabrics (NVMe-oF)**로 급격히 전환되었습니다.

본 문서에서는 NVMe-oF 트랜스포트 계층, NVMe 사양의 비대칭 네임스페이스 접근(ANA - NVMe TP 4004), 리눅스 커널 네이티브 멀티패싱(`nvme_core.multipath`), 그리고 KATO(Keep-Alive Timeout) 기반 고가용성 설계 원리를 심층 분석합니다.

---

## 1. NVMe-over-Fabrics (NVMe-oF) 아키텍처

NVMe는 본래 PCIe 버스 상에서 CPU와 SSD 간의 직접 통신을 위해 고안된 프로토콜입니다. NVMe-oF는 이 고성능 NVMe 명령 세트(Submission Queue, Completion Queue, Doorbell)를 네트워크 패브릭(RDMA over Converged Ethernet - RoCEv2, InfiniBand, TCP)을 통해 원격 스토리지 노드로 확장합니다.

```
                    NVMe-oF 프로토콜 스택 비교
                    
   +-------------------------------------------------------------+
   |                  Linux Block Layer (blk-mq)                 |
   +-------------------------------------------------------------+
                                  │
                                  ▼
   +-------------------------------------------------------------+
   |            NVMe Core / Native Multipath Subsystem           |
   |              (struct nvme_ns_head, nvme_subsys)             |
   +-------------------------------------------------------------+
                                  │
               ┌──────────────────┴──────────────────┐
               ▼                                     ▼
   ┌──────────────────────┐               ┌──────────────────────┐
   │  NVMe RDMA Driver    │               │   NVMe TCP Driver    │
   │   (IB/RoCE QP/CQ)    │               │  (Kernel Sockets)    │
   └──────────┬───────────┘               └──────────┬───────────┘
              ▼                                      ▼
      100GbE RoCEv2 Fabric                   Standard TCP/IP Fabric
      (Sub-10us Wire Latency)                (50~100us Wire Latency)
```

- **초저지연**: 커널 락 경합과 복잡한 SCSI 변환 레이어를 거치던 iSCSI와 달리, NVMe-oF는 큐 페어(Queue Pair)를 CPU 코어에 1:1로 직결하여 마이크로초($\mu\text{s}$) 단위의 레이턴시를 구현합니다.

---

## 2. Asymmetric Namespace Access (ANA - NVMe TP 4004)

엔터프라이즈 스토리지 어레이는 컨트롤러 2개(Active-Active 또는 ALUA)가 고속 백플레인(NTB, Non-Transparent Bridge)으로 묶인 듀얼 컨트롤러 구조를 가집니다.
NVMe 표준 기구는 기존 SCSI ALUA(Asymmetric Logical Unit Access)를 현대화하여 **ANA(Asymmetric Namespace Access)** 표준을 정의했습니다.

```
       Dual Controller Storage Target에서의 ANA 상태 분화
       
                   ┌─────────────────────────────┐
                   │        Target Media         │
                   │     (NVMe Namespace 1)      │
                   └──────────────┬──────────────┘
                                  │ (Owned by SP-A)
                   ┌──────────────┴──────────────┐
                   ▼                             ▼
       ┌──────────────────────┐       ┌──────────────────────┐
       │     Controller A     │       │     Controller B     │
       │     (Storage SP-A)   │◄─────►│     (Storage SP-B)   │
       │   [ANA OPTIMIZED]    │  NTB  │ [ANA NON-OPTIMIZED]  │
       │  Local PCIe Bus Path │  Bus  │ Mirror Proxy Over NTB│
       └──────────┬───────────┘       └──────────┬───────────┘
                  ▲                              ▲
                  │                              │
             Low Latency                   High Latency
               (150us)                        (750us)
```

### 2.1 네 가지 ANA 상태
1. **`ANA Optimized`**:
   - 네임스페이스를 소유한 로컬 컨트롤러에 연결된 경로입니다.
   - 내부 미러 버스를 거치지 않고 직접 로컬 드라이브에 쓰므로 지연시간이 가장 낮고 대역폭이 최대화됩니다.
2. **`ANA Non-Optimized`**:
   - 파트너 컨트롤러를 통해 접근하는 경로입니다.
   - 컨트롤러 간 내부 인터커넥트(PCIe NTB 버스)를 거쳐 데이터를 전달하므로 지연시간이 $3\sim5$배 증가하고 내부 버스 대역폭을 소모합니다.
3. **`ANA Inaccessible`**:
   - 해당 컨트롤러가 백엔드 SSD 미디어와의 통신을 완전히 상실한 상태입니다. 이 경로로 I/O를 전송하면 실패하거나 영구 블로킹됩니다.
4. **`ANA Change`**:
   - 스토리지 어레이 내부 장애로 인해 소유권이 이전(Failover)될 때 발생하는 상태입니다.

---

## 3. 리눅스 네이티브 NVMe 멀티패스 (`nvme_core.multipath=Y`)

과거에는 장치 매퍼(`dm-multipath` / `multipathd`)를 사용하여 다중 경로를 관리했으나, 초당 수백만 IOPS를 처리하는 NVMe 환경에서는 `dm`의 글로벌 락 경합이 극심한 병목이 되었습니다.
리눅스 커널 4.15부터 내장된 **네이티브 NVMe 멀티패스**는 락이 없는 `blk-mq` 기반으로 동작합니다.

### 3.1 I/O 정책의 함정: Round-Robin vs Optimized-Only
- **잘못된 설정 (`iopolicy = "round-robin"`)**:
  - 호스트 드라이버가 단순히 경로 1과 경로 2를 번갈아가며 I/O를 전송합니다.
  - 최적 경로(`OPTIMIZED`, 150us)가 멀쩡히 살아있음에도 불구하고, 절반의 패킷이 비최적 경로(`NON_OPTIMIZED`, 750us)로 보내집니다.
  - 그 결과 전체 애플리케이션 I/O의 P99 지연시간이 폭증하고 스토리지 성능이 절반으로 추락합니다.
- **올바른 설정 (`iopolicy = "numa"` 또는 최적 경로 우선 정책)**:
  - 오직 `ANA Optimized` 경로로만 I/O를 전송합니다.
  - 컨트롤러 장애가 발생하여 AEN을 수신하고 상태가 변경된 경우에만 `NON_OPTIMIZED` 경로로 안전하게 전환(Failover)합니다.

---

## 4. ANA 플래핑과 KATO(Keep-Alive Timeout) 장애

### 4.1 ANA 플래핑과 NVMe Head 재큐잉 프리즈
- 스토리지 컨트롤러 간 내부 하트비트 떨림으로 인해 ANA 상태 변경(AEN)이 수 초 내에 반복적으로 발생하면:
- 호스트 드라이버는 현재 처리 중인 모든 I/O를 `nvme_ns_head`의 재시도 큐로 돌려보내고 새 경로를 검색합니다.
- 경로가 안정화될 때까지 모든 I/O가 멈추는 **I/O Freeze(수 초~수십 초)**가 발생합니다.

### 4.2 KATO (Keep-Alive Timer)와 RoCEv2 정체
- NVMe-oF 타깃은 호스트가 주기적으로 Keep-Alive 명령을 보내지 않으면 세션을 종료합니다.
- RoCEv2 네트워크에서 PFC(Priority Flow Control) Pause 프레임 폭풍이 발생하여 Keep-Alive 명령이 `kato_sec`(기본 5초) 이상 전달되지 못하면:
  - 호스트와 타깃 모두 연결이 끊어진 것으로 간주하고 큐 페어(QP)를 파기합니다.
  - 인플라이트 I/O가 모두 어보트되고 세션을 처음부터 다시 맺는 재연결 루프(Reconnect Storm)가 발생합니다.

---

## 5. 실무 SRE 튜닝 및 진단 체크리스트

| 점검 항목 | 설정 및 확인 명령 | 권장 프로덕션 기준 |
| :--- | :--- | :--- |
| **네이티브 멀티패스 활성화** | `cat /sys/module/nvme_core/parameters/multipath` | 반드시 `Y`여야 함 (dm-multipath 배제) |
| **멀티패스 I/O 정책 확인** | `cat /sys/class/nvme-subsystem/nvme-subsys*/iopolicy` | `numa` 설정 권장 (`round-robin` 절대 금지) |
| **ANA 경로 상태 확인** | `nvme ana-log /dev/nvme0` | 주 경로가 `optimized`, 보조 경로가 `non-optimized`인지 검증 |
| **KATO 타임아웃 튜닝** | `nvme connect ... --keep-alive-tmo=15` | 혼잡 패브릭 환경에서는 기본 5초에서 15~30초로 완화 권장 |
| **RoCEv2 무손실 패브릭 점검** | `ethtool -S <eth_dev> \| grep -E 'pfc\|pause'` | Pause 프레임 누적 및 버퍼 드롭 지속 감시 |
