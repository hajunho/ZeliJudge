# Linux Device Mapper Multipath (`dm-multipath`) & SCSI ALUA 아키텍처 심층 분석

## 1. 엔터프라이즈 스토리지 아키텍처와 다중 경로(Multipathing)의 필요성

현대 금융권, 공공, 대형 클라우드 데이터 센터에서는 데이터베이스와 가상화 클러스터의 영구 스토리지를 위해 파이버 채널(Fibre Channel, FC), iSCSI, 또는 NVMe-oF 기반의 스토리지 에어리어 네트워크(Storage Area Network, SAN)를 구축합니다.

### 1.1 하드웨어 단일 장애점(SPOF)의 위협
호스트 서버에서 스토리지 LUN까지 도달하는 경로에는 수많은 물리 계층이 개입합니다:
1. 호스트 PCI-e 버스 및 HBA (Host Bus Adapter) 포트
2. 물리 광케이블(Optical Cable) 및 트랜시버(SFP+)
3. SAN 패브릭 스위치(Brocade, Cisco MDS 등)
4. 스토리지 컨트롤러 프론트엔드 타깃 포트
5. 스토리지 컨트롤러 프로세서 및 캐시 엔진

만약 서버가 단 하나의 경로로만 스토리지에 연결되어 있다면, 광케이블 단선이나 스위치 포트 리셋 하나만으로도 전사 데이터베이스가 커널 패닉에 빠지게 됩니다. 따라서 고가용성 엔터프라이즈 환경은 서버당 2~4개의 HBA 포트와 최소 2대의 독립된 SAN 스위치(Fabric A, Fabric B)를 구성하여 4개 이상의 물리적 경로를 확보합니다.

### 1.2 문제의 발생: 동일 LUN의 다중 인식
SCSI 서브시스템은 각각의 물리 경로를 서로 다른 독립 디스크로 인식합니다.
예를 들어 단일 1TB LUN이 4개의 경로로 연결되어 있다면, 리눅스 커널은 `/dev/sda`, `/dev/sdb`, `/dev/sdc`, `/dev/sdd`라는 4개의 서로 다른 블록 디바이스 노드를 생성합니다.
만약 애플리케이션이나 파일시스템이 이들 중 아무 곳에나 직접 쓰기를 시도하면:
- 파일시스템 메타데이터 충돌 및 블록 오염
- 캐시 불일치로 인한 영구 데이터 손실
이 발생합니다. 이를 단일 가상 디바이스(`/dev/mapper/mpathX`)로 안전하게 묶어주는 것이 바로 **`dm-multipath`**입니다.

---

## 2. SCSI ALUA (Asymmetric Logical Unit Access) 표준

과거의 스토리지 시스템은 액티브-패시브(Active-Passive) 구조를 사용하여 한 컨트롤러만 I/O를 처리하고 다른 컨트롤러는 대기했습니다. 그러나 현대의 스토리지(EMC PowerStore, NetApp ONTAP, PureStorage FlashArray)는 모든 컨트롤러가 동시에 동작하는 **액티브-액티브(Active-Active)** 구조를 채택합니다.

그럼에도 불구하고 내부 아키텍처상 특정 LUN은 특정 컨트롤러에 직접 할당되어 있는 것이 캐시 적중률과 처리 속도 면에서 압도적으로 유리합니다. 이를 공식 표준화한 것이 **SCSI-3/SCSI-4 ALUA (SPC-3 / SPC-4)**입니다.

### 2.1 ALUA의 4대 타깃 포트 그룹(TPG) 상태
1. **`active/optimized` (액티브/최적)**:
   - 해당 LUN의 주 소유권을 가진 컨트롤러의 포트들입니다.
   - 내부 컨트롤러 간 상호연결(CMI / Inter-Switch Link) 없이 캐시와 플래시 디스크로 직접 I/O를 수행하므로 지연시간이 가장 낮고 대역폭이 극대화됩니다.
2. **`active/non-optimized` (액티브/비최적)**:
   - 피어(상대방) 컨트롤러의 포트들입니다.
   - I/O는 정상 처리되지만, 수신된 요청을 내부 백플레인 버스를 통해 소유권을 가진 파트너 컨트롤러로 포워딩해야 하므로 추가적인 지연시간과 패브릭 오버헤드가 발생합니다.
3. **`standby` (대기)**:
   - I/O를 수신하지 못하며, 컨트롤러 장애 시 액티브 상태로 전환될 준비만 하고 있는 상태입니다.
4. **`unavailable` (비가용)**:
   - 하드웨어 고장, 펌웨어 업데이트 등으로 완전히 오프라인인 상태입니다.

---

## 3. Device Mapper Multipath 내부 구조 (`dm-mpath.c`)

리눅스 커널의 Device Mapper 프레임워크는 가상 블록 디바이스 노드를 생성하고 I/O 요청(struct bio 또는 struct request)을 하위 실제 디바이스로 리매핑합니다.

### 3.1 우선순위 그룹(Priority Groups)과 페일오버
`dm-multipath`는 타깃 포트 그룹(TPG)을 커널 내부에서 `priority_group` 구조체로 추상화합니다:
- 각 PG는 정수 우선순위(`priority`)를 가집니다 (예: Optimized PG는 50, Non-Optimized PG는 10).
- 커널은 항상 `UP` 상태의 경로를 가진 가장 높은 우선순위의 PG를 `current_pg`로 유지합니다.
- 장애 감지:
  - 사용자 공간 데몬(`multipathd`)이 주기적으로 SCSI `TUR` (Test Unit Ready) 또는 직접 읽기 명령을 보내 경로의 생존을 감시합니다.
  - 전송 실패가 발생하면 해당 경로를 즉시 `PATH_DOWN`으로 마킹합니다.
  - 현재 PG의 모든 경로가 DOWN되면, 커널은 즉시 차순위 PG로 **페일오버(Failover)**합니다.

### 3.2 경로 선택자 알고리즘 (`dm-path-selector.c`)
단일 활성 PG 내에서 복수의 활성 경로가 존재할 때, 트래픽 분배 알고리즘을 선택할 수 있습니다:
1. **`round-robin`**:
   - 가장 고전적인 방식으로, 순차적으로 다음 경로로 번갈아 가며 I/O를 디스패치합니다.
   - 동일 사양의 동질적 HBA 환경에 적합합니다.
2. **`queue-length`**:
   - 현재 디바이스 큐에 대기 중인 인플라이트 I/O 개수(`inflight_ios`)를 비교하여 가장 큐가 비어있는 경로로 전송합니다.
   - 단기적인 지연 변동을 흡수하는 데 유리합니다.
3. **`service-time`**:
   - 경로별 처리 용량(가중치, `throughput_weight`)과 현재 전송 중인 바이트 수(`inflight_bytes`)의 비율을 계산합니다:
     $$	ext{Metric} = rac{	ext{inflight\_bytes}}{	ext{throughput\_weight}}$$
   - 32Gbps 고속 포트와 16Gbps 구형 포트가 공존하는 이종 패브릭 환경에서 완벽한 비례 배분을 구현합니다.

### 3.3 `queue_if_no_path`의 운명적 딜레마
SAN 네트워크의 모든 경로가 일시적으로 단절되었을 때의 동작 정책입니다:
- **`queue_if_no_path: true` (기본 권장)**:
  - 파일시스템에 에러를 보고하지 않고 메모리 내 큐에 I/O를 동결(Freeze)시킵니다.
  - 30초 내에 스위치가 재부팅되거나 케이블이 재연결되면 밀려있던 I/O가 플러시되어 서버 리부팅 없이 서비스를 복구합니다.
- **`queue_if_no_path: false` (Fail-Fast)**:
  - 경로가 없으면 즉시 I/O에 `-EIO` 에러를 반환합니다.
  - 클러스터 환경(Pacemaker / Corosync)에서 스토리지 장애 시 노드를 빠르게 펜싱(STONITH)하고 대기 서버로 서비스를 넘길 때 필수적입니다.
