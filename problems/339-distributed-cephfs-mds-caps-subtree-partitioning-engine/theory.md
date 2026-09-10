# 분산 파일 시스템 CephFS 메타데이터 서버(MDS) 및 Capabilities 심층 이론

## 1. 분산 파일 시스템의 메타데이터 병목 문제와 CephFS의 해결책

대규모 분산 스토리지에서 실제 파일 데이터 블록은 수천 대의 OSD(Object Storage Daemon)로 스트라이핑되어 분산되므로 데이터 I/O 대역폭은 노드 수에 비례하여 확장됩니다. 그러나 파일 메타데이터(디렉터리 트리, 소유권, 권한, 수정 시간, 파일 크기 등)는 다음과 같은 엄격한 POSIX 요구사항으로 인해 분산 처리가 매우 어렵습니다:
- 부모 디렉터리 락(Lock) 및 경로 조회(Path Traversal) 원자성
- 동시 파일 쓰기 시 파일 크기(size) 및 수정 시간(mtime)의 선형적 정합성
- 디렉터리 리스팅(`readdir`)의 스냅샷 일관성

CephFS는 이 문제를 해결하기 위해 두 가지 획기적인 아키텍처를 결합했습니다:
1. **MDS 동적 서브트리 파티셔닝**: 메타데이터 트리를 계층적 서브트리로 동적 분할하여 여러 MDS 인스턴스에 샤딩.
2. **클라이언트 Inode Capabilities (Caps)**: 클라이언트가 MDS를 거치지 않고 로컬에서 캐시 읽기 및 버퍼 쓰기를 수행할 수 있도록 임대권 부여.

---

## 2. 동적 서브트리 파티셔닝 (Dynamic Subtree Partitioning)

정적 디렉터리 해싱(Static Hashing)은 디렉터리 트리의 지역성(Locality)을 파괴하여 `ls -l`이나 `find` 같은 명령어를 수행할 때 분산 네트워크 홉(Hop)이 폭증합니다. 반면 고정된 서브트리 정적 할당은 특정 디렉터리(예: `/var/log` 또는 인기 있는 Git 저장소)에 쓰기가 집중될 때 핫스팟(Hotspot)을 피할 수 없습니다.

### 2.1 서브트리 마이그레이션 라이프사이클
CephFS MDS는 각 디렉터리의 CPU 부하와 I/O 카운터를 실시간 측정하여 부하 균형기(MDS Balancer)가 서브트리를 다른 MDS 랭크로 이전합니다:
1. **DISCOVER**: 마이그레이션 대상 디렉터리의 Inode 및 덴트리(Dentry) 트리를 식별.
2. **EXPORT_PREP**: 대상 MDS(Importing MDS)에 서브트리 메타데이터 프리패치 요청.
3. **EXPORT_WARNING**: 연결된 모든 클라이언트에게 해당 서브트리의 권한 보유자(Auth MDS)가 곧 변경될 것임을 통지.
4. **EXPORT_GO**: 원본 MDS가 저널에 마이그레이션 커밋을 기록하고 소유권 핸드오프.
5. **ACTIVE**: 대상 MDS가 새로운 권한자(Authority)로서 클라이언트 Cap 요청을 처리.

클라이언트는 자신이 캐싱한 서브트리 맵을 기반으로 최장 접두사 일치(Longest Prefix Match)를 통해 올바른 MDS 랭크로 직접 통신합니다.

---

## 3. CephFS 클라이언트 Inode Capabilities (Caps) 메커니즘

CephFS에서 클라이언트가 파일에 접근할 때 MDS는 해당 Inode에 대해 세분화된 비트마스크 권한인 **Capability**를 발행합니다:

### 3.1 5대 Cap 범주
1. **Auth (`pA`)**: 소유자(uid/gid), 모드(mode) 등 접근 제어 정보.
2. **Link (`pL`)**: 하드 링크 수(nlink).
3. **Xattr (`pX`)**: 확장 파일 속성.
4. **File (`pF`)**: 파일 데이터 읽기/쓰기 및 크기, 수정 시간.
5. **Dir (`pD`)**: 디렉터리 엔트리 읽기 및 삽입.

### 3.2 File Cap 세부 권한
- `Fs` (Shared Read): 클라이언트가 OSD로부터 데이터를 읽고 로컬 페이지 캐시에 보관 가능.
- `Fc` (Cache): 클라이언트가 캐시된 데이터를 신뢰하고 재사용 가능.
- `Fw` (Write): 클라이언트가 데이터를 로컬 버퍼에 쓰고 Inode 크기를 증가시킬 수 있음.
- `Fx` (Exclusive): 클라이언트가 파일의 독점적 소유자로서 메타데이터 수정을 독점.

### 3.3 충돌 해결과 Cap Revocation Storm 방지
- 단일 작가 다중 독자(Single-Writer Multiple-Readers) 상호 배제 원칙에 따라:
  - `SHARED_READ`는 무제한 다수의 클라이언트가 동시에 보유 가능.
  - `EXCLUSIVE_WRITE`는 오직 단 하나의 클라이언트에게만 허용.
- 쓰기 클라이언트가 있는 상태에서 새로운 읽기 클라이언트가 진입하면, MDS는 쓰기 클라이언트에게 `CAP_OP_REVOKE`를 전송하여 버퍼링된 데이터를 OSD에 플러시(Flush)하도록 강제하고 Cap을 `Fs`로 강등합니다.
- 수백 대의 클라이언트가 동시에 동일 파일을 수정하려 할 때 발생하는 **Cap Revocation 폭풍**을 방지하기 위해, CephFS는 지연 회수(Revocation Throttling) 및 직접 I/O(O_DIRECT) 모드로의 자동 전환 메커니즘을 지원합니다.
