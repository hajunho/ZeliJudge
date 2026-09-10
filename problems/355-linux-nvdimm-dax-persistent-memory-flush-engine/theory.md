# 리눅스 커널 NVDIMM/DAX 아키텍처 및 영구 메모리(PMEM) 심층 분석

## 1. 개요 및 스토리지 패러다임의 혁명

지난 수십 년간 운영체제의 스토리지 계층 구조는 하드디스크(HDD) 및 솔리드 스테이트 드라이브(SSD)와 같은 블록 디바이스의 느린 레이턴시(수 밀리초~수십 마이크로초)를 은폐하기 위해 **DRAM 페이지 캐시(Page Cache)**에 절대적으로 의존해 왔습니다.

그러나 Intel Optane DC Persistent Memory 등으로 대표되는 **NVDIMM (Non-Volatile Dual In-line Memory Module)** 및 CXL 기반 영구 메모리(PMEM)의 출현은 이 전제를 근본적으로 파괴했습니다:
- **DRAM 버스(DDR/CXL) 직접 연결**: 메모리 컨트롤러를 통해 바이트 단위(Byte-Addressable)로 직접 주소 지정 가능.
- **초저지연(Near-DRAM Latency)**: 읽기 $\approx 100\sim 300\text{ns}$, 쓰기 $\approx 100\sim 500\text{ns}$.
- **비휘발성(Non-Volatility)**: 전원이 차단되어도 데이터가 영구 보존됨.

---

## 2. 왜 페이지 캐시가 장애물이 되는가?

기존 파일시스템(ext4, XFS)을 PMEM에 그대로 적용할 경우 치명적인 병목이 발생합니다:
1. **이중 복사(Double Copying) 오버헤드**:
   - `read()` 호출 시: PMEM $\to$ DRAM 페이지 캐시 복사 $\to$ 사용자 버퍼 복사.
   - `write()` 호출 시: 사용자 버퍼 $\to$ DRAM 페이지 캐시 복사 $\to$ 플러시 스레드가 PMEM으로 다시 복사.
   - DRAM 메모리 버스 대역폭의 50% 이상이 단순 복사 작업에 낭비됩니다.
2. **시스템 콜 및 컨텍스트 스위칭 오버헤드**:
   - PMEM의 접근 시간(100ns)이 시스템 콜 트랩 및 문맥 교환 비용(1,000ns+)보다 훨씬 빠르기 때문에, 커널을 거치는 것 자체가 거대한 병목이 됩니다.

---

## 3. DAX (Direct Access) 아키텍처 (`fs/dax.c`)

**DAX(Direct Access)**는 리눅스 VFS와 파일시스템이 DRAM 페이지 캐시를 100% 우회(Bypass)하고, 영구 메모리의 물리적 주소(PFN)를 사용자 가상 메모리 공간(VMA)에 직결하는 기술입니다.

```
[ Traditional File I/O ]
User Space <---> [ DRAM Page Cache ] <=== Block Layer / bio ===> Storage Device
                     (Double Copy!)

[ DAX (Direct Access) ]
User Space <================== CPU MMU / Page Table ==================> PMEM Device
                        (Zero-Copy Direct Load/Store!)
```

### 3.1 DAX 페이지 폴트 메커니즘 (`dax_iomap_fault`)
1. 애플리케이션이 `mmap(..., MAP_SHARED)`을 호출한 후 해당 가상 주소에 첫 접근을 시도하면 CPU MMU가 **페이지 폴트(Page Fault)**를 발생시킵니다.
2. DAX 폴트 핸들러는 파일시스템의 익스텐트 맵(iomap)을 조회하여 파일 논리 오프셋에 대응하는 PMEM 블록의 물리 프레임 번호(PFN)를 획득합니다.
3. 커널은 `struct page`를 DRAM에 할당하지 않고, **PMEM의 PFN을 직접 사용자 프로세스의 PTE(4KB) 또는 PMD(2MB 휴지 페이지)에 매핑**합니다.
4. 폴트 핸들러가 반환된 후, CPU는 일반 어셈블리 명령어(`MOV [rax], rbx`)를 사용하여 PMEM 물리 셀에 수 나노초 만에 직접 데이터를 쓰거나 읽습니다.

---

## 4. 캐시 일관성과 영속성 도메인 (Persistence Boundary)

CPU 코어가 메모리에 `STORE` 명령을 내리면, 데이터는 즉시 PMEM 미디어에 도달하는 것이 아니라 **휘발성 CPU L1/L2/L3 캐시**에 기록됩니다. 이 상태에서 시스템 전원이 차단되면 캐시에 머물던 커밋 데이터는 영구히 증발하여 데이터베이스 WAL이나 파일시스템 메타데이터가 파괴됩니다.

### 4.1 하드웨어 플러시 명령어
이를 해결하기 위해 인텔과 AMD는 전용 비휘발성 메모리 명령어 세트를 도입했습니다:
- **`clflushopt` / `clwb` (Cache Line Write Back)**:
  - 지정된 캐시라인의 더티 데이터를 메모리 컨트롤러의 비휘발성 쓰기 큐(Asynchronous DRAM Refresh, ADR 도메인)로 밀어냅니다.
  - 특히 `clwb`는 캐시라인을 캐시에서 축출(Evict)하지 않고 클린(Clean) 상태로 유지하므로, 후속 읽기 시 캐시 히트(Cache Hit)를 지속적으로 누릴 수 있어 성능이 탁월합니다.
- **`sfence` (Store Fence)**:
  - 이전의 모든 `clwb` 및 `store` 명령이 메모리 컨트롤러에 안전하게 도달할 때까지 후속 명령어의 파이프라인 진행을 차단하는 메모리 배리어입니다.

### 4.2 ADR vs eADR
- **ADR (Asynchronous DRAM Refresh)**:
  - 전원 장애 시 메모리 컨트롤러의 쓰기 큐에 도달한 데이터만 배터리/커패시터로 플러시됩니다.
  - 따라서 소프트웨어는 반드시 `clwb + sfence`를 호출해야 합니다.
- **eADR (Extended ADR)**:
  - CPU 내부의 L1/L2/L3 캐시 전체가 배터리 백업 도메인에 포함됩니다.
  - 전원이 꺼져도 캐시 내용이 하드웨어에 의해 PMEM으로 자동 플러시되므로, 소프트웨어는 `clwb`를 호출할 필요가 없으며 오직 저장 순서 제어를 위한 `sfence`만 발행하면 됩니다!

---

## 5. 결론 및 마일스톤 850 달성의 의의

DAX PMEM 엔진은 현대 고성능 스토리지의 궁극적 이상향인 '스토리지와 메모리의 융합'을 달성한 기술입니다. 이는 ZeliJudge가 초등 수학 알고리즘부터 시작하여, 분산 합의(Raft/Spanner), 리눅스 커널 심층 가상화(KVM/Nested VMX), 네트워크 보안(Netfilter/SYNPROXY)을 거쳐 차세대 하드웨어(NVDIMM/DAX)에 이르기까지 **컴퓨터 과학과 시스템 엔지니어링의 전 영역을 포괄하는 세계 최고 수준의 온라인 저지 플랫폼**임을 입증합니다.
