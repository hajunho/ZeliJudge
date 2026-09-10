# 리눅스 커널 Device Mapper dm-thin 가상 프로비저닝 및 메타데이터 B-Tree 백서

## 1. 전통적 Thick Provisioning의 한계와 Thin Provisioning

전통적인 SAN/LVM 스토리지 환경에서 볼륨 프로비저닝은 **선제적 고정 할당(Thick Provisioning)** 방식을 사용했습니다:
- 100개의 가상머신에 각각 50GB 가상 디스크를 생성하면, 물리 스토리지 풀에서 즉시 $100 \times 50\text{GB} = 5\text{TB}$의 연속 섹터를 예약합니다.
- 그러나 실제 OS 설치 직후 각 VM이 사용하는 용량은 평균 3~5GB(총 300~500GB)에 불과합니다.
- 그 결과 고가의 엔터프라이즈 NVMe SSD 용량의 90% 이상이 쓰이지도 않으면서 묶여버리는 거대한 자본적 지출(CAPEX) 비효율이 발생합니다.

**Thin Provisioning (가상 프로비저닝)**은 "기록되는 시점에만 블록을 할당(Allocate on First Write)"하여, 물리 스토리지 크기보다 훨씬 더 큰 가상 용량을 사용자에게 제공하는 **초과 할당(Overprovisioning)**을 가능하게 합니다.

---

## 2. dm-thin의 커널 메타데이터 설계 (`drivers/md/persistent-data/`)

리눅스 커널 개발자 조 손(Joe Thornber)이 설계한 `dm-thin`은 기존 `dm-snapshot`의 치명적 병목(스냅샷 개수가 늘어날수록 쓰기 증폭이 선형 증가하는 문제)을 해결하기 위해, 독립적인 트랜잭셔널 메타데이터 라이브러리를 도입했습니다.

### 2.1 2단계 영속적 B-Tree 매핑
- **최상위 디바이스 트리 (Device Details Tree)**: 풀 내에 존재하는 가상 디바이스 ID(`dev_id`)와 각 디바이스의 메타데이터 루트를 관리합니다.
- **가상-물리 매핑 트리 (Mapping B-Tree)**: 각 Thin Device는 자신의 독립적인 B-Tree를 갖습니다.
  - Key: 가상 청크 번호 ($v\_chunk = \lfloor \text{sector} / \text{chunk\_sectors} \rfloor$)
  - Value: 물리 청크 번호 ($p\_chunk$)
- B-Tree의 모든 노드는 4KB 크기이며, CoW 방식으로 갱신(Shadowing)되어 전원이 갑자기 차단되어도 파일시스템 저널처럼 원자적 롤백이 가능합니다.

### 2.2 공간 맵 (Space Map, `dm_space_map`)
- 모든 물리 청크의 참조 카운트(`ref_count`)를 추적하는 전용 비트맵/배열입니다.
- **Reference Counting**:
  - $0$: 미할당 (Free Chunk)
  - $1$: 단독 소유. 추가 쓰기 시 제자리 덮어쓰기(In-place Overwrite) 수행.
  - $N \ge 2$: 스냅샷 공유. 쓰기 시 CoW 분기 발생, 새 청크 할당 및 이전 청크 카운트 감소.
- 스냅샷 생성 시 물리 데이터를 복사할 필요 없이, B-Tree 루트 포인터만 복제하고 매핑된 청크들의 Space Map 참조 카운트를 1씩 증가시키므로 **$O(1)$ 시간**에 즉시 완료됩니다.

---

## 3. Discard (TRIM)와 가비지 컬렉션의 동작 원리

게스트 OS(가상머신) 안에서 파일이 삭제되어도, 하부 블록 디바이스 입장에서는 어떤 섹터가 비었는지 알 수 없습니다. 이를 방치하면 가상 볼륨의 물리 사용량은 영원히 증가만 하게 됩니다.

- 파일시스템의 `discard` 마운트 옵션이나 `fstrim` 명령은 사용 해제된 섹터 범위에 대해 `REQ_OP_DISCARD` 바이오(bio)를 발행합니다.
- `dm-thin` 드라이버는 해당 가상 청크의 B-Tree 매핑을 삭제하고, Space Map의 참조 카운트를 감소시킵니다.
- 참조 카운트가 0에 도달한 물리 청크는 즉시 물리 풀의 프리 리스트(Free List)로 반환되어 다른 볼륨이나 스냅샷이 재사용할 수 있게 됩니다.

---

## 4. 실무 운영상의 위험: Out-of-Data-Space (OODS) 참사

초과 할당(Overprovisioning)은 강력하지만, 물리 풀이 100% 소진되었을 때 **재앙적인 정지(Catastrophic Freeze)**를 유발할 수 있습니다.

1. **Docker `devicemapper` 루프백 참사**:
   - 초기 도커는 기본 스토리지 드라이버로 스파스 루프백 파일 기반의 `devicemapper`를 사용했습니다.
   - 컨테이너 빌드 및 로그 누적으로 thin pool이 100%에 도달하자, 모든 쓰기 I/O가 정지되면서 도커 데몬 전체가 락업(Lock-up)되는 사고가 빈번했습니다.
2. **`error_if_no_space` vs `queue_if_no_space`**:
   - `error_if_no_space`: 풀이 가득 차면 즉시 `-ENOSPC` 에러를 반환합니다. 게스트 파일시스템은 즉시 읽기 전용(Read-Only)으로 마운트 해제되거나 크래시됩니다.
   - `queue_if_no_space`: I/O를 커널 큐에 보류합니다. 프로세스는 블로킹되지만, 시스템 관리자가 물리 LVM 볼륨을 증설(`lvextend`)할 때까지 데이터 유실 없이 기다립니다.
3. **`dmeventd` 자동 확장 메커니즘**:
   - 엔터프라이즈 환경에서는 데몬(`dmeventd`)이 `low_watermark`(예: 80%) 이벤트를 감지하여, 풀이 고갈되기 전에 자동으로 물리 LVM 풀을 증설(`thin_pool_autoextend_threshold`)함으로써 무중단 서비스를 보장합니다.
