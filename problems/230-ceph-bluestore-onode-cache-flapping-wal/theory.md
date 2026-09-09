# 문제 230 이론: Ceph BlueStore 스토리지 엔진 아키텍처와 Onode 캐시, BlueFS RocksDB 컴팩션 및 OSD 플래핑 심층 분석

## 1. Ceph 스토리지 엔진의 진화: FileStore에서 BlueStore로

Ceph의 초기 엔진인 **FileStore**는 XFS나 ext4 같은 범용 POSIX 파일시스템 위에 객체를 저장했습니다:
- POSIX 원자성 부재로 인해 저널 파일(Journal)에 먼저 쓰고 본 파일에 다시 쓰는 **이중 쓰기(Double-Write) 패널티**가 발생하여 쓰기 대역폭이 50% 반토막 났습니다.
- 수백만 개의 소형 객체 생성 시 디렉토리 분할(Directory Sharding) 및 파일시스템 inode 락 경합으로 심각한 병목이 유발되었습니다.

```
[FileStore vs BlueStore Architecture]

FileStore (Legacy):
User Data ---> POSIX File System (XFS) ---> Double Journaling ---> Raw Disk
(Problem: Double-write penalty, POSIX inode bottleneck, High latency)

BlueStore (Modern):
User Data ------------(Direct Raw Extents I/O: Zero POSIX FS!)-------------> Raw HDD/NVMe
Object Metadata ------(Onodes, omap, extents)-----> RocksDB on BlueFS ----> Dedicated NVMe
(Benefits: Double-write eliminated, Checksum for bit-rot, 2x write performance!)
```

---

## 2. BlueStore 내부 구성 요소 심층 분석

BlueStore는 운영체제의 파일시스템을 완전히 배제하고 유저스페이스에서 원시 블록 장치를 직접 제어합니다:

1. **블록 할당자 (Block Allocator)**:
   - 대용량 연속 블록 할당을 위한 **비트맵 할당자(Bitmap Allocator)**를 탑재하여 객체 데이터를 디바이스 블록 오프셋에 직접 배치합니다.
2. **Onode (Object Node)**:
   - 각 Ceph 객체의 모든 메타데이터(크기, 논리적 오프셋에서 물리적 디바이스 익스텐트로의 매핑, 체크섬, 사용자 정의 속성 xattr)를 담고 있는 핵심 구조체입니다.
   - Onode는 메모리 내 2Q/LRU 캐시에 적재되며, 캐시 미스 시 RocksDB에서 디시리얼라이즈되어 메모리로 로드됩니다.
3. **BlueFS와 임베디드 RocksDB**:
   - RocksDB는 본래 POSIX 파일 인터페이스(`Env`)를 요구하므로, BlueStore 내부에 RocksDB의 WAL 및 SSTable 파일만을 전담 저장하는 초경량 특수 파일시스템인 **BlueFS**를 내장했습니다.

---

## 3. OSD 플래핑(OSD Flapping)의 발생 메커니즘과 데스 스파이럴

Ceph OSD들은 피어 OSD들과 초당 수회씩 하트비트(Heartbeat) 메시지를 주고받으며 생존 여부를 모니터링합니다:

```
[The OSD Flapping Mechanism]
OSD A (Heartbeat Monitor) -------- Ping --------> OSD B (Subject)
OSD A <----------------------- Pong/Ack -------- OSD B

If OSD B undergoes heavy RocksDB compaction on slow storage:
- Disk I/O saturates at 100% utilization.
- RocksDB triggers Write Stall to throttle ingestion.
- The OSD thread pool locks up, and heartbeat packets cannot be dispatched.
- Elapsed time reaches 20.1 seconds (exceeding osd_heartbeat_grace = 20s).
- OSD A informs Ceph Monitor: "OSD B is UNRESPONSIVE!"
```

### 3.1 플래핑 데스 스파이럴 (Death Spiral)
1. 모니터가 OSD B를 `DOWN` 처리합니다.
2. CRUSH 맵이 재계산되어 OSD B가 담당하던 배치 그룹(PG)들이 다른 정상 OSD들로 재배치됩니다.
3. 수백 기가바이트에서 수 테라바이트에 달하는 **백필(Backfill) 복제 트래픽**이 클러스터 네트워크를 뒤덮습니다.
4. 불과 5초 뒤 RocksDB 컴팩션이 완료되어 OSD B가 응답을 재개하고 `UP` 상태로 복귀합니다.
5. 모니터는 다시 CRUSH 맵을 롤백하고 진행 중이던 백필을 취소합니다.
6. 직후 대기 중이던 클라이언트 쓰기가 다시 OSD B로 폭주하면서 또다시 컴팩션 스톨이 발생하고, OSD가 다시 `DOWN`으로 떨어집니다.
7. 이 주기가 무한 반복되며 클러스터 전체가 다운되는 치명적인 장애를 **OSD Flapping Storm**이라 부릅니다.

---

## 4. 실무 엔지니어링 최적화 튜닝 가이드

| 튜닝 파라미터 | 권장 설정 | 주의점 및 기대 효과 |
| :--- | :--- | :--- |
| **BlueFS 디바이스 분리** | `block.db`를 전용 초고속 NVMe에 배치 | 메타데이터 쓰기와 대용량 데이터 I/O 간의 경합 완벽 차단 |
| **컴팩션 병렬화** | `rocksdb_max_background_compactions = 4~8` | 단일 스레드 병목으로 인한 10초 이상의 긴 컴팩션 스톨 방지 |
| **하트비트 유예 시간** | `osd_heartbeat_grace = 30~40s` | 일시적 컴팩션 스톨로 인한 허위 `DOWN` 오판 및 플래핑 원천 방지 |
| **전용 하트비트 스레드** | `osd_heartbeat_use_min_delay_socket = true` | 디스크 I/O 워커 블로킹과 무관하게 하트비트 패킷 우선 송수신 |
| **Onode 캐시 사이징** | 객체 100만 개당 최소 1.5GB 이상 할당 | 캐시 미스로 인한 RocksDB 디스크 I/O 스파이크 및 지연시간 20배 폭증 방어 |
