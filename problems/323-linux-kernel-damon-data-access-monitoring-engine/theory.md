# Linux Kernel DAMON & DAMOS: 현대 클라우드 메모리 가상화와 적응형 모니터링 이론

## 1. 배경: 전통적 메모리 스캔 방식의 한계와 메모리 인플레이션

현대 하이퍼스케일러 환경에서 메모리 집약적 워크로드(인메모리 DB인 Redis, RocksDB 블록 캐시, 대규모 JVM/Go 런타임, LLM 추론 엔진)는 할당된 메모리의 상당 부분을 수 시간 이상 읽지 않는 **콜드 메모리(Cold Memory)**로 유지합니다.

### 1.1 전통적 LRU 리스트의 구조적 병목
리눅스 커널의 전통적인 페이지 회수 엔진(`mm/vmscan.c`)은 시스템 전역의 Active/Inactive LRU 리스트를 스캔합니다.
1. **PTE Young Bit 스캔 오버헤드**:
   페이지가 실제로 접근되었는지 확인하려면 커널은 페이지 테이블을 순회하며 하드웨어 MMU가 설정한 PTE의 `Accessed` (x86에서는 `_PAGE_ACCESSED`, ARM에서는 `PTE_AF`) 비트를 읽고 클리어해야 합니다.
   $$PTE_{new} = PTE_{old} \ \& \ \sim 	ext{\_PAGE\_ACCESSED}$$
   이 과정에서 각 프로세스의 `page_table_lock` 또는 split PTE lock을 획득해야 하므로, 수백 코어 CPU 환경에서 극심한 **스핀락 경합(Spinlock Contention)**과 TLB 플러시 오버헤드가 발생합니다.
2. **사후 반응적(Reactive) 한계**:
   `kswapd`는 여유 메모리가 `watermark_low` 이하로 떨어져야 깨어납니다. 메모리 부족이 닥쳤을 때 급격하게 페이징이 시작되므로, 유저 스페이스 애플리케이션은 **Direct Reclaim Latency Spike**(수십 밀리초 이상 스레드가 멈추는 현상)를 겪게 됩니다.

---

## 2. DAMON (Data Access MONitoring)의 핵심 혁신

리눅스 5.15 커널에 머지된 DAMON(작성자: 박성재 / SeongJae Park)은 다음 3가지 핵심 원리로 작동합니다.

### 2.1 영역 기반 적응형 공간 분할 (Region-based Adaptive Spatial Partitioning)
전체 주소 공간을 페이지(4KB) 단위로 일일이 추적하는 대신, 연속된 주소 블록인 **영역(Region)** 단위로 그룹화합니다.
- 각 영역 $R_i = [start_i, end_i)$은 하나의 대표 샘플링 포인트 또는 범위 내 임의 접근 여부로 평가됩니다.
- 모니터링 영역 개수를 $[min\_nr\_regions, max\_nr\_regions]$로 고정함으로써, 주소 공간이 1GB이든 1TB이든 커널의 모니터링 오버헤드(CPU 점유율 및 메모리 소모량)를 $O(N_{regions})$ 상한선으로 완벽히 통제할 수 있습니다.

### 2.2 동적 영역 병합 및 분할 (Dynamic Merging & Splitting)
1. **병합 (`damon_merge_regions_of`)**:
   인접한 두 영역 $R_i$와 $R_{i+1}$의 접근 빈도 차이 $|acc_i - acc_{i+1}| \le merge\_threshold$이고 나이 차이 $|age_i - age_{i+1}| \le age\_merge\_threshold$이면 두 영역을 병합합니다. 이를 통해 접근 패턴이 균일한 거대한 콜드 영역들을 단일 영역으로 묶어 모니터링 효율을 극대화합니다.
2. **분할 (`damon_split_regions_at`)**:
   영역 수가 `max_nr_regions`에 도달하지 않았다면, 크기와 접근 빈도가 높은 영역($Score = size 	imes (acc + 1)$)을 절반으로 쪼갭니다. 이를 통해 집중적으로 접근되는 **핫스팟(Working Set Hotspot)**의 경계를 바이트 단위에 가깝게 정밀하게 좁혀 나갑니다.

### 2.3 나이(Age) 추적 메커니즘
접근 빈도가 급변하지 않고 안정적으로 유지되는 경우 $age$ 카운터를 증가시킵니다:
$$age_{t+1} = egin{cases} age_t + 1 & 	ext{if } |acc_{t+1} - acc_t| \le 1 \ 0 & 	ext{otherwise} \end{cases}$$
이를 통해 일시적인 캐시 스캔(One-hit Wonder / Sequencial Scan)과 장기적으로 안정적인 콜드/핫 메모리를 통계적으로 완벽히 구분합니다.

---

## 3. DAMOS (DAMON-based Operation Schemes): 지능형 메모리 조작

DAMON이 '관측(Monitoring)'이라면, DAMOS는 '행동(Operation)'입니다.

### 3.1 4대 조작 액션 (Actions)
- `PAGEOUT`: 접근 빈도가 0이고 나이가 오래된 영역을 선제적으로 스왑/회수하여 물리 메모리 여유분을 상시 확보합니다. (AWS 등의 데이터센터에서 메모리 비용 20~30% 절감).
- `LRU_PRIO`: 접근 빈도가 높은 영역을 커널 활성 LRU 헤드로 선점 승격시켜, 메모리 회수 폭풍 시에도 작업 집합이 스왑아웃되지 않도록 보호합니다.
- `LRU_DEPRIO`: 접근 빈도가 낮아진 영역을 비활성 LRU 꼬리로 강등합니다.
- `STAT`: 실제 메모리 조작 없이 일치하는 영역의 크기와 개수만을 통계 집계합니다.

### 3.2 할당량(Quota) 및 우선순위 가중치 (Priority Weights)
대규모 메모리 조작이 일시에 발생하면 스토리지 I/O 및 CPU 병목이 발생할 수 있습니다. DAMOS는 주기당 최대 적용 바이트 수(`sz_quota_bytes`)를 강제하며, 할당량 초과 시 영역별 우선순위 점수를 산출하여 가장 시급한 영역부터 차례로 처리합니다:
$$Score(R) = W_{sz} 	imes rac{Size(R)}{4096} + W_{acc} 	imes Acc(R) + W_{age} 	imes Age(R)$$
콜드 메모리 회수(`PAGEOUT`)의 경우 $W_{age}$에 높은 가중치를 부여하여 가장 오래된 콜드 페이지부터 우선 회수함으로써 워크로드 충격을 최소화합니다.
