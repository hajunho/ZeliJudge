# Problem 215 심층 이론: 리눅스 VFS Negative Dentry 폭증과 커널 슬랩(Slab) 고갈 및 vfs_cache_pressure 튜닝

## 1. 리눅스 가상 파일 시스템(VFS)과 덴트리 캐시(Dentry Cache)의 내부 구조

리눅스 커널의 VFS(Virtual File System) 계층은 모든 파일 시스템(ext4, xfs, btrfs, nfs 등)에 대한 단일하고 추상화된 인터페이스를 제공합니다. VFS는 4개의 핵심 데이터 구조체로 구성됩니다:

```
[VFS 4대 핵심 구조체 관계도]
struct file (열린 파일 인스턴스, 파일 오프셋 f_pos)
     │
     ▼
struct dentry (디렉터리 엔트리: 경로 컴포넌트 이름 문자열 "app" <-> inode 매핑)
     │
     ▼
struct inode (실제 파일/디렉터리의 물리 메타데이터: 권한, 크기, 블록 포인터)
     │
     ▼
struct super_block (마운트된 파일 시스템 전역 메타데이터)
```

### 1.1 Dcache(Directory Cache)의 역할과 중요성
사용자가 `/var/log/nginx/access.log` 파일을 열 때, 커널은 루트(`/`)부터 시작하여 `var` $\to$ `log` $\to$ `nginx` $\to$ `access.log`까지 계층적으로 디렉터리를 탐색해야 합니다.  
매번 디스크에서 디렉터리 데이터 블록을 읽는 것은 엄청난 I/O 오버헤드를 유발하므로, 리눅스는 경로 컴포넌트를 해시 테이블과 LRU 리스트로 인메모리에 캐싱합니다. 이것이 바로 **덴트리 캐시(dentry_cache)**입니다.

---

## 2. Negative Dentry(네거티브 덴트리)의 탄생 목적과 위험성

### 2.1 왜 "없는 파일"까지 메모리에 캐싱하는가?
운영체제에서 "존재하지 않는 파일"을 찾는 시스템 콜은 상상을 초월할 정도로 빈번합니다:
1. **환경 변수 `$PATH` 탐색**: 쉘에서 명령어를 실행할 때마다 커널은 `/usr/local/bin`, `/usr/bin`, `/bin` 순으로 파일을 탐색하며 수많은 `ENOENT`(No such file)를 겪습니다.
2. **프로그래밍 언어 임포트**: 파이썬의 `import os`는 `sys.path`에 등록된 수십 개의 디렉터리를 순차 검색합니다.
3. **웹 서버 404 정적 에셋**: `/favicon.ico`, `/robots.txt` 등.

만약 존재하지 않는 파일에 대한 조회를 캐싱하지 않는다면, 매번 물리 디스크의 디렉터리 B-Tree나 해시 테이블을 풀 스캔해야 합니다.  
이를 방지하기 위해 리눅스 VFS는 **"이 파일은 존재하지 않는다"**는 사실 자체를 캐싱하기 위해 **`d_inode == NULL`인 `struct dentry` 객체**를 슬랩 메모리에 생성합니다. 이것이 **Negative Dentry**입니다.

### 2.2 페이지 캐시(Page Cache)와 슬랩 캐시(Slab Cache)의 결정적 차이
많은 시스템 엔지니어들이 덴트리 캐시를 페이지 캐시로 착각합니다:
- **페이지 캐시(Page Cache)**: 커널의 페이지 프레임 할당기(`alloc_pages`)가 $4\,\text{KB}$ 페이지 단위로 관리하며, 메모리가 부족하면 커널이 즉시 디스크로 플러시하거나 단 1줄의 함수 호출로 즉시 폐기할 수 있습니다.
- **덴트리 슬랩 캐시(dentry_cache)**: 커널의 슬랩/슬러브(SLAB/SLUB) 할당기(`kmem_cache_create`)가 관리하는 고정된 C 구조체 메모리 조각입니다. `/proc/meminfo`에서 `SReclaimable`로 분류되지만, 커널에 등록된 전용 **수축기(Shrinker)**를 호출하여 객체 단위로 참조 카운트를 확인하고 락을 획득하며 해제해야 하므로 회수 비용이 극도로 무겁습니다.

---

## 3. Negative Dentry 폭증과 메모리 고갈(OOM) 참사

### 3.1 무작위 404 스톰 공격 (Random 404 Storm)
해외 봇넷이나 취약점 스캐너가 다음과 같이 매번 다른 무작위 경로로 초당 수만 건의 요청을 보낼 때:
```
GET /scanner/0192a83f-48d2.php
GET /backup/database_dump_8273.sql
GET /admin/login_39821.action
```
1. 매 요청마다 파일이 없으므로(`ENOENT`), VFS는 매번 새로운 Negative Dentry를 생성하여 슬랩에 추가합니다.
2. 무작위 경로이므로 이전에 생성된 Negative Dentry는 두 번 다시 재사용되지 않습니다 (캐시 적중률 0%).
3. 슬랩 메모리(`dentry_cache`)가 $10\,\text{GB}, 30\,\text{GB}, 60\,\text{GB}$로 무한정 팽창합니다.
4. 호스트 가용 메모리가 고갈되어 `pages_min` 수위 밑으로 추락하면, 커널 **OOM Killer**가 작동하여 메모리를 가장 많이 점유하고 있던 사용자 프로세스(MySQL, Nginx, JVM)를 강제 사살(`SIGKILL`)합니다.

---

## 4. `vfs_cache_pressure`와 Shrinker 스핀락 경합의 딜레마

리눅스 커널은 VFS 캐시(덴트리 및 inode)의 회수 강도를 조절하기 위해 `vm.vfs_cache_pressure` sysctl 파라미터를 제공합니다 (기본값: 100).

$$\text{Reclaim Target} = \text{Scan Batch} \times \frac{\text{vfs\_cache\_pressure}}{100}$$

### 4.1 `vfs_cache_pressure = 0` 또는 극단적으로 낮은 값의 위험
- 커널은 메모리 압박이 와도 덴트리 슬랩 캐시를 절대 회수하지 않습니다 (`reclaim_target = 0`).
- 404 스톰이 발생하면 가용 메모리가 즉각 0이 되며 100% 확률로 OOM Killer가 발동합니다.

### 4.2 `vfs_cache_pressure = 500` 이상의 과도한 설정과 락 경합(Spinlock Contention)
"슬랩 누수를 막기 위해 `vfs_cache_pressure`를 500이나 1000으로 올리면 해결되지 않을까?"라고 생각할 수 있지만, 이는 또 다른 형태의 시스템 마비를 초래합니다:
1. 매 파일 조회 시 메모리가 `min_watermark` 밑으로 떨어지면 **다이렉트 메모리 회수(Direct Reclaim)**가 발동합니다.
2. 커널의 `dentry_shrinker`가 LRU 리스트를 순회하며 수천 개의 덴트리를 회수하기 위해 **전역 `dcache_lru_lock` 스핀락**을 획득합니다.
3. 멀티 코어 서버에서 수백 개의 스레드가 동시에 `dcache_lru_lock`을 얻기 위해 바쁜 대기(Busy-waiting)를 수행하면서, **CPU의 시스템 시간(sys) 점유율이 95% 이상으로 폭증**합니다.
4. 파일 열기(`open()`) 지연시간이 평소 $1\,\mu\text{s}$에서 **$50 \sim 100\,\mu\text{s}$ 이상으로 100배 치솟으며** 시스템 전체가 사실상 동결(Freeze)됩니다.

---

## 5. 완벽한 프로덕션 방어책: 블룸 필터(Bloom Filter) 사전 차단 아키텍처

커널 내부 파라미터 튜닝만으로는 대규모 무작위 404 공격을 완전히 방어할 수 없습니다. 근본적인 해결책은 **"존재하지 않는 파일에 대한 조회가 커널 VFS 계층(open/stat 시스템 콜)에 아예 도달하지 못하도록 유저 공간 / 프록시 계층에서 사전에 필터링하는 것"**입니다.

```
[블룸 필터 기반 Negative Dentry 사전 차단 아키텍처]

Client Request (GET /scan/random_uuid.php)
      │
      ▼
┌────────────────────────────────────────────────────────┐
│ Nginx / API Gateway / Application (User-Space)         │
│                                                        │
│ [ In-Memory Bloom Filter ]                             │
│ - 서버에 실제로 존재하는 정적 파일 경로들을 비트 배열에 해싱     │
│ - bloom.contains("/scan/random_uuid.php") ──► FALSE!   │
│                                                        │
│ ==> VFS 시스템 콜을 호출하지 않고 유저 공간에서 404 즉각 반환! │
└──────────────────────────┬─────────────────────────────┘
                           │ (검증 통과한 정상 파일만 진입)
                           ▼ open() 시스템 콜
┌────────────────────────────────────────────────────────┐
│ 리눅스 커널 VFS (dentry_cache)                          │
│ - 불필요한 Negative Dentry 생성 = 정확히 0건!          │
│ - 슬랩 메모리 점유 = 0%                                │
│ - Shrinker 락 경합 = 0건                               │
│ - 0.2 us 극초저지연 유지!                               │
└────────────────────────────────────────────────────────┘
```

### 5.1 블룸 필터(Bloom Filter)의 수학적 강점
- **False Negative = 0%**: 실제로 존재하는 파일이 블룸 필터에 의해 거부되는 일은 수학적으로 0%입니다. 따라서 정상 서비스에는 어떠한 영향도 주지 않습니다.
- **초소형 메모리**: 100만 개의 파일 경로를 0.1% 오탐률(False Positive Rate)로 필터링하는 데 필요한 메모리는 불과 **$1.8\,\text{MB}$**에 불과합니다 (커널 슬랩 60GB 낭비와 비교 불가).

---

## 6. 프로덕션 관측성(Observability) 명령어 가이드

1. **전역 덴트리 상태 확인**:
   ```bash
   $ cat /proc/sys/fs/dentry-state
   # 출력 예시: 52428800  48129300  45  0  0  0
   # [총 dentry 수] [미사용/Negative dentry 수] [에이징 제한] ...
   ```
2. **슬랩 메모리 점유율 실시간 모니터링**:
   ```bash
   $ sudo slabtop -s c
   # 상위 1위: dentry_cache 가 수십 GB를 차지하고 있는지 감시
   ```
3. **슬랩 캐시 강제 수축 (비상 조치)**:
   ```bash
   $ echo 2 > /proc/sys/vm/drop_caches  # dentry & inode 캐시만 즉시 해제
   ```
