# [CS-105] 대용량 파일 읽었더니 메모리가 0B인데 디스크에서 바로 읽혀요?!: Linux 가상 메모리 파일 매핑 `mmap`과 페이지 캐시 Zero-Copy

> **"선생님! 10GB짜리 대용량 파일을 열었는데, 프로세스 메모리(RSS)가 0MB로 찍혀요! 그런데 파일 안의 데이터를 메모리 배열처럼 즉시 읽고 쓸 수 있는 게 말이 되나요?!"**
> 
> 검색 엔진 백엔드를 개발하는 주니어 엔지니어 태우는 10GB짜리 역색인(Inverted Index) 파일을 메모리로 불러와 초고속 검색을 구현하려 했습니다.
> 기존 방식대로 `file.read()`를 호출하자마자 서버 메모리가 순식간에 10GB 폭증하더니 리눅스 OOM-Killer에 의해 프로세스가 즉사(Exit Code 137)당했습니다.
> 
> 멘토는 혀를 차며 코드 한 줄을 수정해 주었습니다:
> `mapped_data = mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_WRITE)`
> 
> 그러자 기적이 일어났습니다! 프로세스의 물리 메모리 점유량(RSS)은 0KB로 유지되는데, `mapped_data[102400]`처럼 마치 메모리 배열을 다루듯 파일의 모든 위치를 0.001ms 만에 읽어낼 수 있었습니다.
> 
> "메모리에 올리지도 않았는데 어떻게 메모리 포인터로 읽히죠?!"  
> 시니어 아키텍트는 화이트보드에 가상 메모리와 페이지 테이블을 그리며 말했습니다.
> "태우 씨, 도서관에서 1만 페이지짜리 백과사전을 볼 때 책 전체를 가방에 다 쑤셔 넣고(Read 버퍼) 다니나요? 아니면 서가 번호표(가상 메모리 주소)만 쥐고 있다가, 읽고 싶은 페이지만 쏙 펼쳐서 책상(RAM)에 올려놓고(Page Fault) 보나요?"

---

## 1. 문제 배경과 현실 비유: 도서관 책 복사 vs 책장 좌표 지도

전통적인 `read()`/`write()` 시스템 콜은 디스크 데이터를 커널 페이지 캐시로 복사한 뒤, 이를 다시 유저 프로세스의 힙 메모리 버퍼로 복사하는 **이중 복사(Double Copy)** 오버헤드가 발생합니다. 10GB 파일을 읽으면 메모리 20GB가 낭비되며 극심한 CPU 복사 부하와 가비지 컬렉션(GC) 폭탄을 유발합니다.

반면, `mmap` (Memory Mapping)은 파일 데이터를 유저 공간으로 복사해 오지 않고, **파일의 디스크 블록을 프로세스의 가상 주소 공간(Virtual Address Space)에 1:1로 직접 연결(Mapping)**합니다.

### 핵심 메커니즘 3단계
1. **지연 할당 (Lazy Allocation)**:
   - `mmap`을 호출한 시점에는 물리 RAM(페이지 프레임)을 단 1바이트도 할당하지 않습니다.
   - 단지 가상 주소 공간의 메타데이터(VMA)만 생성하므로 프로세스의 실제 물리 메모리(RSS)는 **0B**입니다!
2. **요구 페이징 (Demand Paging) & 페이지 폴트 (Page Fault)**:
   - 프로그램이 특정 오프셋을 읽으려 할 때, 아직 물리 RAM에 올라와 있지 않다면 CPU MMU가 **페이지 폴트(Page Fault)** 인터럽트를 발생시킵니다.
   - 커널은 해당 오프셋이 속한 **정확히 4KB(1개 페이지)** 크기만 디스크에서 읽어 커널 페이지 캐시에 로드합니다 (`disk_io = 4096B`).
   - 이후 동일한 페이지에 대한 모든 접근은 디스크 I/O 없이 **물리 RAM에서 0.0001ms 만에 Zero-Copy로 직접 읽힙니다(Cache Hit, disk_io = 0B)**!
3. **더티 페이지 (Dirty Page) & `msync`**:
   - 가상 메모리에 값을 쓰면 해당 페이지만 `Dirty`로 마킹되고 즉시 쓰기 시스템 콜이 종료됩니다.
   - 변경된 데이터는 백그라운드에서 커널 플러셔 스레드가 디스크에 비동기 반영하거나, `msync`를 호출하여 명시적으로 디스크에 플러시할 수 있습니다.

---

## 2. 요구사항 및 명령어 사양

당신은 리눅스 커널의 가상 메모리 파일 매핑(`mmap`), 페이지 폴트, 페이지 캐시, 더티 페이지 및 msync 동기화를 시뮬레이션하는 `MmapSimulator` 엔진을 구현해야 합니다.
표준 입력(`stdin`)으로 들어오는 명령어들을 한 줄씩 파싱하여 정확한 형식으로 표준 출력(`stdout`)에 출력하십시오.
(기본 페이지 크기는 4096바이트(4KB)입니다.)

### 지원 명령어 목록

1. `CREATE_FILE <file_name> <size_bytes>`
   - 가상 디스크에 크기 `<size_bytes>`인 파일을 생성합니다.
   - 총 페이지 수 `pages = (size_bytes + 4095) // 4096`
   - 출력: `CREATE_FILE name=<file_name> size=<size_bytes> pages=<pages>`

2. `MMAP_FILE <conn_id> <file_name> <prot: READ|WRITE>`
   - 가상 주소 공간에 파일을 매핑합니다.
   - 초기 물리 메모리 점유량은 0B입니다.
   - 출력: `MMAP_FILE id=<conn_id> file=<file_name> prot=<prot> mapped_pages=<pages> initial_rss_bytes=0`

3. `READ_BYTE <conn_id> <offset>`
   - 가상 메모리의 특정 `<offset>` 바이트를 읽습니다.
   - 유효 범위(`0 <= offset < size_bytes`)를 벗어나면:
     - 출력: `ERROR id=<conn_id> reason=OFFSET_OUT_OF_BOUNDS offset=<offset>`
   - 해당 오프셋이 속한 페이지(`page_no = offset // 4096`):
     - 물리 메모리에 없는 경우:
       - 페이지 폴트 발생 및 디스크 4KB 로드: `PAGE_FAULT id=<conn_id> page=<page_no> reason=READ_MISS disk_io=4096B`
     - 이미 물리 메모리에 있는 경우:
       - 캐시 히트: `PAGE_HIT id=<conn_id> page=<page_no> disk_io=0B`
   - 읽기 성공: `READ_SUCCESS id=<conn_id> offset=<offset> page=<page_no> val=<val>`

4. `WRITE_BYTE <conn_id> <offset> <val>`
   - 가상 메모리의 특정 `<offset>`에 바이트 값 `<val>`(0~255)을 씁니다.
   - 매핑 권한이 `READ`인 경우:
     - 출력: `ERROR id=<conn_id> reason=PERMISSION_DENIED_READONLY`
   - 유효 범위를 벗어나면 `ERROR id=<conn_id> reason=OFFSET_OUT_OF_BOUNDS offset=<offset>`
   - 해당 페이지가 물리 메모리에 없으면 페이지 폴트 발생 (`reason=WRITE_MISS disk_io=4096B`), 이미 있으면 캐시 히트 (`disk_io=0B`).
   - 메모리에 값 기록 후 해당 페이지를 더티(`dirty=True`)로 설정.
   - 출력: `WRITE_SUCCESS id=<conn_id> offset=<offset> page=<page_no> val=<val> dirty=True`

5. `MSYNC <conn_id>`
   - 현재 더티 상태인 모든 페이지를 디스크로 플러시하고 더티 상태를 해제합니다.
   - 플러시된 총 바이트 수 = `더티페이지수 * 4096`.
   - 출력: `MSYNC id=<conn_id> flushed_pages=<count> flushed_bytes=<bytes>`

6. `MUNMAP <conn_id>`
   - 파일 매핑을 해제합니다. 아직 플러시되지 않은 더티 페이지가 있다면 자동으로 디스크에 플러시한 뒤 모든 물리 메모리를 반환합니다.
   - 출력: `MUNMAP id=<conn_id> auto_flushed_pages=<count> released_rss_bytes=<bytes>`

7. `STATS <conn_id>`
   - 현재 세션의 가상 메모리 및 디스크 I/O 통계를 출력합니다.
   - 출력: `STATS id=<conn_id> page_faults=<faults> cache_hits=<hits> total_disk_io_bytes=<io_bytes> current_rss_bytes=<rss_bytes> dirty_pages=<dirty_count>`

---

## 3. 입출력 예시

### 예시 입력 1
```text
CREATE_FILE data.bin 16384
MMAP_FILE map1 data.bin WRITE
READ_BYTE map1 0
READ_BYTE map1 10
WRITE_BYTE map1 20 65
STATS map1
MSYNC map1
STATS map1
MUNMAP map1
```

### 예시 출력 1
```text
CREATE_FILE name=data.bin size=16384 pages=4
MMAP_FILE id=map1 file=data.bin prot=WRITE mapped_pages=4 initial_rss_bytes=0
PAGE_FAULT id=map1 page=0 reason=READ_MISS disk_io=4096B
READ_SUCCESS id=map1 offset=0 page=0 val=0
PAGE_HIT id=map1 page=0 disk_io=0B
READ_SUCCESS id=map1 offset=10 page=0 val=0
PAGE_HIT id=map1 page=0 disk_io=0B
WRITE_SUCCESS id=map1 offset=20 page=0 val=65 dirty=True
STATS id=map1 page_faults=1 cache_hits=2 total_disk_io_bytes=4096 current_rss_bytes=4096 dirty_pages=1
MSYNC id=map1 flushed_pages=1 flushed_bytes=4096
STATS id=map1 page_faults=1 cache_hits=2 total_disk_io_bytes=8192 current_rss_bytes=4096 dirty_pages=0
MUNMAP id=map1 auto_flushed_pages=0 released_rss_bytes=4096
```

---

## 4. 실무 핵심 요약 (Architecture Takeaway)

1. **Zero-Copy와 메모리 절약**:
   - `mmap`은 커널 페이지 캐시와 유저 프로세스 힙 사이의 불필요한 메모리 복사를 원천 제거하여, 테라바이트 단위의 초대형 파일도 물리 RAM 크기에 구애받지 않고 초고속으로 탐색할 수 있게 합니다.
2. **고성능 시스템 소프트웨어의 핵심 기반**:
   - Apache Kafka(메시지 로그), Lucene/Elasticsearch(역색인 세그먼트), SQLite/RocksDB(B-Tree 인덱스) 등 현대의 거의 모든 고성능 스토리지 엔진은 `mmap`과 OS 페이지 캐시를 주력 I/O 아키텍처로 사용합니다.
