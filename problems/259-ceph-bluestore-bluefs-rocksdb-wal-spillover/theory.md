# [이론 및 배경] Ceph BlueStore 아키텍처와 RocksDB BlueFS 메타데이터 스필오버

## 1. Ceph FileStore에서 BlueStore로의 진화와 커널 바이패스

초기 Ceph 백엔드였던 **FileStore**는 POSIX 호환 로컬 파일시스템(XFS, btrfs) 위에 오브젝트를 일반 파일로 저장했습니다.
그러나 이는 다음과 같은 근본적인 병목을 유발했습니다:
1. **이중 저널링(Double Journaling) 오버헤드**: Ceph 자체의 분산 트랜잭션 저널 + XFS 로컬 저널로 인해 모든 쓰기 I/O가 디스크에 두 번 기록되는 50%의 대역폭 낭비 발생.
2. **POSIX 메타데이터 직렬화 병목**: 수백만 개의 작은 오브젝트 생성 시 디렉터리 inode 락 경합 및 `fsync()` 지연 급증.

Ceph 12(Luminous) 버전부터 기본 엔진으로 채택된 **BlueStore**는 POSIX 파일시스템을 완전히 제거하고, 리눅스 커널의 블록 레이어를 사용자 공간에서 직접 다루는 구조로 전면 재설계되었습니다:
- **Raw Block Device 제어**: 사용자 공간 블록 할당기(Bitmap Allocator / Stupid Allocator)가 디스크 블록을 직접 할당.
- **Copy-on-Write (CoW)**: 기존 데이터를 덮어쓰지 않고 새로운 블록에 기록 후 메타데이터를 원자적으로 교체함으로써 이중 저널링을 완전히 제거.
- **RocksDB 통합**: 오브젝트 네임스페이스, extent 매핑 맵, 속성(xattrs), omap 데이터를 임베디드 RocksDB LSM 트리에 초고속 인덱싱.

---

## 2. BlueFS: RocksDB를 위한 가상 사용자 공간 파일시스템

RocksDB는 내부적으로 POSIX 인터페이스(`open()`, `append()`, `rename()`, `delete()`)를 통해 파일(SSTable, WAL, MANIFEST)을 다루도록 설계되어 있습니다.
그러나 BlueStore는 로컬 파일시스템이 없기 때문에, RocksDB 아래에 최소한의 경량 사용자 공간 파일시스템인 **BlueFS** 계층을 배치합니다.

```
+-------------------------------------------------------------+
|                     Ceph OSD Daemon                         |
+------------------------------+------------------------------+
|       Object Data (CoW)      |    Object Metadata & WAL     |
|   (Direct Block Allocator)   |         (RocksDB)            |
+------------------------------+------------------------------+
|                              |      BlueFS (Virtual FS)     |
+------------------------------+------------------------------+
|                     BlueStore Block Device                  |
|    [  WAL Tier  ]   |    [  DB Tier  ]   |   [  Slow Tier  ] |
|     (Fast NVMe)     |     (Fast SSD)     |     (Data HDD)   |
+---------------------+--------------------+------------------+
```

BlueFS는 물리적 저장 공간을 3개의 디바이스 경로로 분할 관리합니다:
- **`BDEV_WAL`**: WAL 로그 전용 초고속 NVMe SSD (지연 시간 최우선).
- **`BDEV_DB`**: RocksDB SSTable 메타데이터 전용 고속 SSD.
- **`BDEV_SLOW`**: 주 데이터가 저장되는 대용량 HDD 또는 QLC 디바이스.

---

## 3. 메타데이터 스필오버(Spillover)의 메커니즘과 지연 시간 참사

### 3.1 동적 공간 확장과 스필오버 전이
BlueFS는 `BDEV_WAL`과 `BDEV_DB`에 고정된 크기를 사전에 슬라이싱하여 할당합니다.
그러나 프로덕션 클러스터에서 오브젝트 수가 수천만 개를 넘어서거나, 대규모 스냅샷, omap 데이터 급증, 또는 대량의 백필링(Backfilling)이 발생하면 `BDEV_DB`의 가용 공간이 바닥납니다.

이때 BlueFS는 프로세스 중단을 막기 위해 다음과 같은 단계로 공간을 할당합니다:
1. `BDEV_DB` 공간이 부족하면 자동으로 `BDEV_SLOW` (HDD) 디바이스에서 블록을 할당받습니다 (**DB Spillover**).
2. `BDEV_WAL` 공간이 부족하면 `BDEV_DB`로 전이되고, `BDEV_DB`도 부족하면 `BDEV_SLOW`로 전이됩니다 (**WAL Spillover Catastrophe**).

### 3.2 왜 HDD 스필오버는 재앙인가?
SSD와 HDD의 무작위 I/O 지연 시간 격차는 약 **100배~1,000배**에 달합니다:
- SSD Write Latency: $pprox 100\mu	ext{s}$
- HDD Random Seek & Write: $pprox 10	ext{ms} \sim 15	ext{ms}$

RocksDB의 Commit 파이프라인은 WAL 쓰기가 디스크에 물리적으로 동기화(`fdatasync`)될 때까지 후속 클라이언트 쓰기 트랜잭션을 직렬화하여 대기시킵니다.
WAL 또는 Level-0 SSTable이 HDD로 스필오버되는 순간, 단 한 번의 동기화 쓰기가 15ms 동안 OSD 작업 큐(`tp_osd_tp`)를 완전히 블로킹하며 초당 수만 IOPS를 처리하던 OSD가 수십 IOPS로 주저앉습니다.

---

## 4. 슬로우 OSD와 하트비트 플래핑(Flapping) 장애

Ceph 클러스터 내의 수천 개 OSD는 서로 간에 주기적인 메시지 핑을 주고받으며 피어의 생존 여부를 감시합니다:
- `osd_heartbeat_interval`: 6초마다 피어 OSD에 하트비트 전송.
- `osd_heartbeat_grace`: 20초 동안 하트비트 응답이 없으면 해당 OSD를 `DOWN`으로 판정하고 MON(Monitor)에 보고.

### 4.1 플래핑의 악순환(Cascading Meltdown)
1. **스필오버로 인한 OSD 행(Hang)**: HDD 메타데이터 쓰기로 인해 OSD 데몬의 작업 스레드가 20초 이상 블로킹됩니다.
2. **피어 OSD의 `DOWN` 신고**: 피어들이 하트비트 실패를 감지하고 모니터에 OSD 장애를 보고합니다.
3. **PG 피어링 및 리커버리 스톰**: 클러스터 맵이 변경되면서 해당 OSD에 있던 수백 개의 배치 그룹(PG)이 다른 OSD들로 복제(Peering & Backfill)를 시작합니다.
4. **OSD 부활(`UP`)**: 잠시 후 HDD I/O가 완료되면서 OSD가 깨어나 피어에게 핑을 보내고, 모니터에 자신이 살아있음을 알립니다.
5. **무한 반복 (Flapping)**: 다시 부활하자마자 밀려 있던 클라이언트 I/O와 백필 트래픽이 쏟아져 들어오며 즉시 HDD 스필오버 스톨이 재발하고 다시 `DOWN` 상태로 추락합니다.

이로 인해 전체 스토리지 클러스터의 CPU, 네트워크 대역폭, I/O 버스가 피어링 폭풍으로 마비됩니다.

---

## 5. 프로덕션 완화 및 최적화 아키텍처

Ceph 엔지니어링 팀은 이 참사를 방지하기 위해 3단계 방어선을 구축했습니다:
1. **하트비트 스레드 분리 (`heartbeat_decoupled = True`)**:
   스토리지 I/O 작업 큐와 하트비트 네트워크 송수신 큐를 완전히 별도의 실시간 우선순위 스레드로 분리하여, 디스크 I/O가 멈추더라도 하트비트 핑은 즉각 응답하도록 설계.
2. **사전 쓰기 스로틀링 (Write Throttling)**:
   `db` 여유 공간이 임계치(`bluefs_min_free_ratio = 0.10`) 아래로 내려가면 클라이언트 쓰기 레이트를 능동적으로 낮추어 공간 고갈을 지연시킴.
3. **긴급 L0 컴팩션 및 수동 공간 마이그레이션 (`ceph-bluestore-tool`)**:
   여유 공간 확보 시 `compact`를 트리거하여 HDD로 누출된 SSTable을 고속 DB SSD로 다시 흡수.
