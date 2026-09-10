# Linux 커널 가상 메모리: ZRAM 압축 인메모리 스왑 디바이스와 zsmalloc 슬랩 아키텍처

## 1. 개요 및 배경

현대 컴퓨팅 환경(스마트폰, IoT 엣지 게이트웨이, 클라우드 가상 머신, 하이퍼스케일러 컨테이너)에서 물리 메모리(DRAM)는 시스템의 성능과 밀도를 결정짓는 가장 핵심적이고도 비싼 하드웨어 자원입니다. 전통적인 유닉스/리눅스 가상 메모리 관리자(VMM)는 메모리가 부족해질 때 익명 페이지(Anonymous Pages: 힙, 스택, mmap 등)를 디스크(HDD, eMMC, NVMe SSD)의 스왑 파티션으로 축출(Swap-out)하였습니다.

그러나 플래시 메모리(eMMC, NAND Flash) 기반 모바일/임베디드 기기에서는 다음과 같은 치명적인 한계가 존재합니다:
1. **스토리지 쓰기 수명(P/E Cycle) 소모**: 빈번한 스왑 I/O는 NAND 셀의 수명을 급격히 단축시켜 기기 조기 고장을 유발합니다.
2. **I/O 병목 및 레이턴시 스파이크**: DRAM 접근 속도(수십 나노초) 대비 스토리지 I/O(수백 마이크로초~수 밀리초)는 $10^4$배 이상 느리며, 주 스레드가 스왑-인(Swap-in) 페이지 폴트 대기에 묶여 UI 프레임 드롭(Jank)과 앱 멈춤(ANR)이 발생합니다.
3. **배터리 소모 급증**: 스토리지 컨트롤러와 버스 구동은 모바일 배터리를 빠르게 소모합니다.

이에 따라 2008년 Nitin Gupta 등에 의해 제안된 `compcache` 프로젝트는 **ZRAM**(`drivers/block/zram/zram_drv.c`)이라는 정식 리눅스 커널 모듈로 진화하였으며, 현재 모든 현대 안드로이드 OS(Android 4.4 KitKat 이후 기본 탑재)와 Fedora, ChromeOS의 핵심 기본 인프라로 자리잡았습니다.

---

## 2. ZRAM 디바이스 아키텍처 및 핵심 메커니즘

### 2.1 블록 디바이스 계층 및 bio 처리 흐름
ZRAM은 가상 블록 디바이스(`/dev/zram0`)로 등록됩니다. 리눅스 스왑 서브시스템(`mm/swapfile.c`)은 `swapon /dev/zram0` 명령을 통해 ZRAM을 최고 우선순위(Highest Priority) 스왑 디바이스로 지정합니다.

스왑 요청이 발생하면 커널 블록 I/O 계층은 `bio` 구조체를 생성하여 `zram_submit_bio()`에 전달합니다:
- `REQ_OP_WRITE`: 스왑-아웃할 $4096\text{ 바이트}$ 페이지를 압축하여 메모리 풀에 저장.
- `REQ_OP_READ`: 스왑-인 요청 시 압축 풀에서 데이터를 읽어 원래 4KB 페이지로 복원(Decompress).
- `REQ_OP_DISCARD`: 스왑 영역이 해제될 때(`swapoff` 또는 스왑 엔트리 무효화) 해당 슬롯을 즉각 반환.

### 2.2 동일 페이지 중복 제거 (Same-Page Fill Optimization)
실제 운영체제 메모리에는 수많은 페이지가 $0$으로만 채워져 있거나(BSS 섹션, 제로 초기화 버퍼), 동일한 $32\text{비트}$ 워드 패턴(예: 디버그 카나리 `0xDEADBEEF`, 포인터 배열 `0xFFFFFFFF`)으로 채워져 있습니다.

커널 ZRAM은 압축 엔진(LZO, LZ4 등)을 구동하기 전, 초고속 SIMD/워드 루프를 통해 페이지 전체가 동일한 32비트 워드로 구성되어 있는지 검사합니다(`zram_same_page_fill()`):
$$\forall i \in [0, 1023], \quad Word_i = Word_0$$
- 동일 페이지로 판명되면, 압축을 생략하고 메타데이터 테이블에 `ZRAM_SAME` 플래그와 4바이트 패턴 값을 기록합니다.
- 이 경우 `zsmalloc` 할당자를 호출하지 않으므로 물리 DRAM 소비량은 **$0\text{ 바이트}$**가 됩니다.

### 2.3 비압축 거대 페이지 방어 (`ZRAM_HUGE`)
고도로 엔트로피가 높은 데이터(JPEG 이미지, H.264 동영상 프레임, 암호화 키 등)는 압축 알고리즘을 거쳐도 크기가 줄어들지 않으며, 오히려 메타데이터 오버헤드로 인해 원본 $4096\text{ 바이트}$보다 커지거나 거의 줄어들지 않습니다.
리눅스 ZRAM은 압축 결과 크기가 임계치인 $4096 - 64 = 4032\text{ 바이트}$ 이상인 경우:
- 압축 해제 CPU 비용을 낭비하지 않기 위해 원본 상태 그대로 저장합니다.
- 해당 슬롯에 `ZRAM_HUGE` 플래그를 마킹하여, 향후 보조 저장소 라이트백 시 최우선 축출 대상으로 삼습니다.

---

## 3. zsmalloc 메모리 할당자 (`mm/zsmalloc.c`) 심층 분석

일반적인 커널 슬랩 할당자(`kmalloc` / `SLUB`)는 $2^n$ 단위(바디 할당)로 크기를 나누기 때문에 가변 크기 압축 객체(예: $127\text{B}$, $583\text{B}$)를 저장할 경우 극심한 내부 단편화(Internal Fragmentation)를 초래합니다. 반면 ZRAM 전용 할당자인 **`zsmalloc`**은 객체 크기별 세분화된 클래스와 다중 페이지 체이닝 기법을 도입하였습니다.

### 3.1 크기 클래스(Size Class) 및 최적 zspage 체이닝
`zsmalloc`은 스텝 크기($S$, 보통 32 또는 64바이트) 단위로 크기 클래스 $C \in [S, 2S, \dots, 4096]$를 정의합니다.
임의의 압축 크기 $size$에 대해 할당 클래스는 다음과 같이 결정됩니다:
$$C = \min\left(4096, \; \left\lceil \frac{size}{S} \right\rceil \times S\right)$$

하나의 `zspage`는 1개에서 최대 4개(`ZS_MAX_PAGES_PER_ZSPAGE = 4`)의 연속된 물리 프레임($p \in \{1, 2, 3, 4\}$)으로 구성됩니다. 크기 클래스 $C$에 대해 내부 낭비 바이트가 최소화되는 $p$를 사전 계산합니다:
$$\text{Waste}(p, C) = (p \times 4096) \pmod C$$
$$p^* = \arg\min_{p \in \{1, 2, 3, 4\}} \text{Waste}(p, C)$$
$$\text{Capacity}(C) = \left\lfloor \frac{p^* \times 4096}{C} \right\rfloor$$

### 3.2 Fullness 그룹 및 슬롯 재활용
각 크기 클래스는 `zspage`들을 포화도에 따라 4가지 링크드 리스트로 분리하여 관리합니다:
1. `ZS_EMPTY`: 활성 객체 0개 (즉시 반환 또는 재사용 대기).
2. `ZS_ALMOST_EMPTY`: $0 < used \le \lfloor capacity / 3 \rfloor$.
3. `ZS_ALMOST_FULL`: $\lfloor capacity / 3 \rfloor < used < capacity$.
4. `ZS_FULL`: $used = capacity$ (빈 슬롯 없음).

새로운 객체 할당 시 `ALMOST_FULL` 리스트의 `zspage`에서 슬롯을 먼저 채워 완전히 꽉 차게 만들고, 그 다음 `ALMOST_EMPTY`를 채우는 전략(First-fit with fullness preference)을 사용하여 메모리 사용률을 극대화합니다.

---

## 4. 백킹 디바이스(Backing Device) 라이트백 및 메모리 압축(Compaction)

### 4.1 2차 보조 저장소 라이트백 (Writeback)
ZRAM만 사용할 경우, 시스템의 모든 메모리가 압축된 스왑 데이터로 가득 차면 결국 물리 RAM이 고갈되는 한계에 부딪힙니다. Linux 4.14부터 도입된 백킹 디바이스 지원은 저속의 플래시 드라이브나 eMMC 블록 디바이스를 2차 백업 스토리지로 연동합니다:
- `SET_IDLE`: 스왑 인덱스별 마지막 접근 시각(`last_access_ts`)을 검사하여, 오랜 시간 동안 읽히지 않은 "차가운(Cold) 페이지"에 `ZRAM_IDLE` 플래그를 마킹합니다.
- `WRITEBACK`:
  - `IDLE`: 오랫동안 접근되지 않은 페이지를 플래시 디바이스로 축출하여 물리 RAM을 확보.
  - `HUGE`: 압축률이 극도로 낮아 RAM을 4KB씩 통째로 낭비하는 페이지를 우선 축출.
  - 축출된 페이지는 ZRAM 물리 풀에서 해제되며, `in_backing_dev = True` 상태로 유지되어 필요 시 백킹 디바이스에서 직접 읽힙니다.

### 4.2 슬랩 메모리 압축 해소 (Compaction)
스왑 데이터의 빈번한 쓰기/삭제/라이트백이 누적되면 동일 크기 클래스 내 수많은 `zspage`들이 $1\sim 2$개의 객체만을 담은 채 물리 $4\text{KB}$ 프레임들을 붙잡고 있는 외부 단편화(External Fragmentation)가 발생합니다.

관리자가 `/sys/block/zram0/compact`를 트리거하면 `zs_compact()`가 수행됩니다:
1. 사용 슬롯이 적은 공여자(Donor) `zspage`를 선택.
2. 수용 슬롯 여유가 있는 수신자(Receiver) `zspage`로 객체를 복사/이주.
3. 모든 객체가 이주되어 `used = 0`이 된 공여자 `zspage`의 물리 프레임 $p^*$개를 리눅스 버디 할당자로 즉시 반환(`free_page()`).

이로써 단편화로 낭비되던 수십~수백 메가바이트의 물리 DRAM이 즉각 해소되어 활성 애플리케이션에 재할당됩니다.
