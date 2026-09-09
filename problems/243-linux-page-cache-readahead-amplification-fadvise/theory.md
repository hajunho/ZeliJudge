# Problem 243 Theory: 리눅스 커널 페이지 캐시와 리드어헤드 심층 분석 — `ondemand_readahead`, I/O 증폭, 캐시 오염 및 `posix_fadvise` / `O_DIRECT`

현대 운영체제의 VFS(Virtual File System) 서브시스템에서 **페이지 캐시(Page Cache)**는 느린 블록 디바이스(SSD, HDD, SAN)와 빠른 CPU/메모리 간의 속도 격차를 메워주는 핵심 가상 메모리 관리 계층입니다.

본 문서에서는 리눅스 커널 `mm/readahead.c`의 내부 선독 알고리즘, OLTP 무작위 룩업 시 발생하는 I/O 증폭 및 페이지 캐시 오염 메커니즘, 그리고 POSIX 힌트(`posix_fadvise`) 및 `O_DIRECT`를 활용한 데이터베이스 최적화 기법을 심층 분석합니다.

---

## 1. 리눅스 페이지 캐시와 `struct file_ra_state`

리눅스 커널은 열려 있는 모든 파일 디스크립터(`struct file`)마다 독립적인 리드어헤드 상태 구조체인 `struct file_ra_state`를 유지합니다.

```c
// include/linux/fs.h
struct file_ra_state {
    pgoff_t start;          // 현재 리드어헤드 윈도우의 시작 페이지 오프셋
    unsigned int size;      // 리드어헤드 윈도우의 총 페이지 수
    unsigned int async_size;// 비동기 프리페치를 트리거할 잔여 페이지 임계치
    unsigned int ra_pages;  // 이 파일에 허용된 최대 리드어헤드 페이지 한도
    pgoff_t prev_pos;       // 직전 읽기 요청의 마지막 바이트 위치
};
```

### 1.1 온디맨드 리드어헤드 (`mm/readahead.c`) 알고리즘
- 프로세스가 파일의 특정 오프셋을 읽을 때, 커널은 `page_cache_sync_readahead()` 또는 `page_cache_async_readahead()`를 호출합니다.
- **순차 읽기 감지 시**:
  - 첫 번째 읽기에서 4개 페이지(16KB)를 읽고, 순차적 접근이 계속 확인되면 윈도우를 지수적으로 2배씩 확장합니다 ($4 \to 8 \to 16 \to 32 \to 64$ 페이지).
  - 애플리케이션이 현재 윈도우의 데이터를 다 읽기 전에, 커널 백그라운드 스레드가 비동기 DMA를 통해 다음 윈도우를 미리 RAM에 로드해 둡니다.
  - 따라서 순차 파일 스캔(Full Table Scan, Log Parsing)에서는 디스크 대기 시간이 0에 수렴하는 극상의 처리량을 달성합니다.

---

## 2. 무작위 포인트 룩업의 재앙: I/O 증폭과 캐시 오염

### 2.1 I/O 증폭 (I/O Amplification) 메커니즘
관계형 데이터베이스(PostgreSQL, MySQL InnoDB)의 B-Tree 인덱스 탐색이나 NoSQL/LSM(RocksDB, Cassandra)의 SSTable 블록 조회의 전형적인 접근 패턴은 **무작위 4KB 포인트 룩업**입니다.
- 오프셋 100MB에서 4KB 읽기 $\to$ 오프셋 2GB에서 4KB 읽기 $\to$ 오프셋 500MB에서 4KB 읽기.
- 커널의 기본 설정(`/sys/block/<dev>/queue/read_ahead_kb = 128KB`, 즉 `ra_pages = 32`):
  - 프로세스는 4KB(1개 페이지)만 요청했음에도 불구하고, 커널은 뒤따르는 124KB(31개 페이지)를 "곧 읽힐 것"이라 착각하여 디스크에서 함께 읽어들입니다.
  - **I/O 증폭비**:
    $$\text{I/O Amplification} = \frac{128\,\text{KB}}{4\,\text{KB}} = 32\times$$
  - 디스크에서 실제로 전송된 데이터 중 96.8%는 단 한 번도 사용되지 않고 버려집니다. 고가의 프로비저닝된 NVMe IOPS와 대역폭이 순식간에 고갈됩니다.

### 2.2 페이지 캐시 오염 (Page Cache Pollution)
- 읽어 들인 124KB의 쓸모없는 페이지들은 커널의 LRU 리스트(Inactive List)에 삽입됩니다.
- 메모리 공간이 부족해지면, 커널의 메모리 회수 알고리즘(`kswapd`)은 새로 들어온 쓰레기 페이지를 담기 위해 **기존에 자주 조회되던 핫 인덱스 페이지(Working Set)를 메모리 밖으로 축출(Evict)**합니다.
- 결과적으로 애플리케이션의 캐시 히트율이 90% 이상에서 20~30%대로 폭락하며 시스템 전체의 P99 응답 지연시간이 수십 배 튀어 오릅니다.

---

## 3. 프로덕션 최적화 기법: `posix_fadvise` & `O_DIRECT`

```
                  리눅스 파일 I/O 제어 전략 비교
                  
   +-------------------------------------------------------------+
   |            User-space Application / Database Engine         |
   +-------------------------------------------------------------+
           │                           │                  │
           ▼ (POSIX_FADV_RANDOM)       ▼ (O_DIRECT)       ▼ (DEFAULT)
   +─────────────────────────+         │          +─────────────────────────+
   |  Kernel Page Cache      |         │          |  Kernel Page Cache      |
   |  ra_pages = 0 (정확히    |         │          |  ra_pages = 32 (128KB   |
   |  요청 크기만 캐싱)       |         │          |  투기적 프리페치 & 증폭) |
   +─────────────────────────+         │          +─────────────────────────+
           │                           │                  │
           ▼ (4KB DMA)                 ▼ (Direct DMA)     ▼ (128KB DMA)
   +─────────────────────────────────────────────────────────────+
   |                   Storage Device (NVMe SSD)                 |
   +-------------------------------------------------------------+
```

### 3.1 `posix_fadvise` 시스템 콜
POSIX 표준 시스템 콜인 `posix_fadvise(int fd, off_t offset, off_t len, int advice)`는 커널에게 해당 파일 영역의 접근 패턴 힌트를 전달합니다.

1. **`POSIX_FADV_RANDOM`**:
   - 커널 내부에서 해당 파일의 `ra_pages`를 `0`으로 설정합니다.
   - 투기적 선독이 완전히 중단되며, 프로세스가 요청한 바이트만큼만 정확히 디스크에서 읽어 I/O 증폭비를 완벽하게 $1.0\times$로 만듭니다.
   - RocksDB의 SSTable 파일 핸들, PostgreSQL의 인덱스 파일 접근 시 필수적으로 적용됩니다.
2. **`POSIX_FADV_DONTNEED`**:
   - 지정된 범위의 캐시 페이지를 즉시 LRU 리스트에서 해제(`invalidate_mapping_pages`)합니다.
   - 대규모 덤프/백업이나 일회성 ETL 배치 작업 후 즉시 호출하면, 대량의 콜드 데이터가 운영 트랜잭션의 핫 캐시를 오염시키는 것을 원천 방지합니다.
3. **`POSIX_FADV_WILLNEED`**:
   - 지정된 파일 영역을 커널이 비동기적으로 미리 페이지 캐시에 적재하도록 요청합니다. 쿼리 플래너가 곧 읽을 범위를 알고 있을 때 유용합니다.

### 3.2 `O_DIRECT` (Direct I/O)
- 파일을 열 때 `open(path, O_RDWR | O_DIRECT)` 플래그를 지정하면, 커널의 페이지 캐시를 완전히 바이패스합니다.
- 디스크 컨트롤러(NVMe DMA)와 유저스페이스 메모리 버퍼 간에 직접 데이터가 교환됩니다.
- 자체 버퍼 풀(Buffer Pool)을 정교하게 관리하는 DBMS(MySQL InnoDB, Oracle, ScyllaDB)는 OS 페이지 캐시와의 이중 버퍼링(Double Buffering) 낭비와 락 경합을 피하기 위해 `O_DIRECT`를 기본으로 채택합니다.

---

## 4. 실무 SRE 진단 및 튜닝 체크리스트

| 점검 항목 | 확인 명령 및 파라미터 | 권장 기준 및 튜닝 방안 |
| :--- | :--- | :--- |
| **블록 디바이스 리드어헤드 한도** | `/sys/block/<dev>/queue/read_ahead_kb` | OLTP 전용 NVMe 디바이스의 경우 `16` ~ `32` (KB) 이하로 대폭 축소 |
| **I/O 증폭 모니터링** | `iostat -xz 1` (`r_await`, `rMB/s`) | 읽기 바이트 수 대비 실제 쿼리 처리량 비율 점검 |
| **페이지 캐시 오염 관측** | `sar -B 1` (`pgpgin/s`, `kswapd`) | 벌크 작업 실행 중 `kswapd` 스캔 급증 및 활성 캐시 축출 여부 확인 |
| **eBPF 커널 선독 추적** | `bpftrace -e 'kprobe:ondemand_readahead { ... }'` | 파일별 실제 리드어헤드 호출 빈도 및 윈도우 크기 실시간 프로파일링 |
