# 문제 249 이론: CephFS 멀티 액티브 MDS 동적 서브트리 파티셔닝, Cap 회수 데드락 및 비콘 장애 조치 메커니즘

---

## 1. CephFS와 메타데이터 서버(MDS) 아키텍처

CephFS는 분산 오브젝트 스토리지(RADOS) 위에 구축된 고성능 POSIX 파일시스템입니다. 일반적인 분산 파일시스템과 달리, CephFS는 메타데이터 관리와 실제 파일 I/O 경로를 완전히 분리합니다:

```
+-------------------------------------------------------------+
| CephFS Client (Kernel Driver / FUSE)                        |
+-------------------------------------------------------------+
        │ (1) Open / Stat / Readdir          │ (2) Read / Write Direct
        ▼                                    ▼
+-----------------------+          +--------------------------+
| Ceph MDS Cluster      |          | Ceph OSDs (RADOS Pool)   |
| (Directory Hierarchy) |          | (Raw File Chunks/Objects)|
+-----------------------+          +--------------------------+
```

### 멀티 액티브 MDS (Multi-Active MDS)
대규모 클러스터에서는 단일 MDS가 병목이 되는 것을 방지하기 위해 여러 대의 활성 MDS 랭크(Rank 0, Rank 1...)를 구성합니다. 전체 디렉토리 트리는 **서브트리(Subtree)**라는 단위로 동적으로 분할되어 각 MDS가 권한(Authority, `auth`)을 나누어 갖습니다.

---

## 2. 동적 서브트리 파티셔닝과 부하 감지 (Subtree Balancer)

MDS는 지속적으로 각 디렉토리 서브트리의 인기(Heat)를 측정합니다:
$$H = 	ext{Read\_Ops} + 2 	imes 	ext{Write\_Ops} + 	ext{Metadata\_Creations}$$
- 각 랭크의 부하가 불균형해지면, 밸런서는 부하가 높은 랭크에서 낮은 랭크로 서브트리를 마이그레이션(Export)합니다.
- 마이그레이션 단계:
  1. `DISCOVER`: 대상 랭크에게 서브트리 이전 의사를 전달.
  2. `FREEZE_TREE`: 해당 서브트리 내의 신규 요청을 중단하고 대기 큐에 보관.
  3. `REVOKE_CAPS`: 클라이언트들이 쥐고 있는 캐시 락(Caps)을 회수.
  4. `EXPORT/IMPORT`: 인메모리 아이노드 및 덴트리 상태를 네트워크로 전송.
  5. `ACTIVE`: 권한 이양 완료 및 보류된 클라이언트 요청 해제.

---

## 3. 프로덕션 장애 패턴 분석 (Production Failure Modes)

### (1) 클라이언트 Cap 회수 타임아웃과 이전 교착 (Stuck Cap Revocation)
CephFS 클라이언트는 성능을 위해 파일 메타데이터의 읽기/쓰기 권한(Caps: `As`, `Fs`, `Frw` 등)을 로컬에 캐싱합니다.
- 서브트리를 다른 MDS로 넘기려면, 기존 MDS는 해당 서브트리에 접근하던 모든 클라이언트에게 `CEPH_CAP_OP_REVOKE`를 보내 캐시를 반환받아야 합니다.
- **치명적 문제**: 네트워크 순단, 커널 패닉, 혹은 높은 I/O 대기로 인해 특정 클라이언트가 ACK를 보내지 못하면 서브트리 전체가 `FREEZE` 상태에 영구적으로 갇힙니다.
- **해결책**:
  ```bash
  # 응답 없는 클라이언트를 자동 축출하도록 설정
  ceph config set mds mds_cap_revoke_eviction_timeout 30
  ```
  타임아웃 발생 시 MDS가 해당 클라이언트의 세션을 강제 축출(Evict)하여 교착을 깨뜨려야 합니다.

### (2) 서브트리 핑퐁 플래핑 (Ping-Pong Flapping)
- 배치 워크로드나 CI 파이프라인에서 두 디렉토리의 부하가 번갈아 가며 치솟는 경우:
  - T=10초: Rank 0에서 Rank 1로 `/pipeline` 이전.
  - T=20초: Rank 1이 과부하되자 다시 Rank 0으로 `/pipeline` 이전.
- 이 과정에서 매번 디렉토리 전체가 동결되어 빌드 프로세스가 멈추고 p99 지연 시간이 30초 이상 폭증합니다.
- **해결책**:
  - 마이그레이션 쿨다운(감쇠 타이머)을 설정하여 최소 수 분간 동일 서브트리의 재이전을 금지.
  - 또는 자주 접근하는 핫 디렉토리를 특정 MDS 랭크에 수동 핀(Pinning) 설정:
    ```bash
    setfattr -n ceph.dir.pin -v 0 /mnt/cephfs/pipeline
    ```

### (3) 대규모 아이노드 캐시 트리밍과 비콘 하트비트 타임아웃
- 수천만 개의 파일이 삭제되거나 생성될 때 MDS의 인메모리 아이노드 수가 `mds_cache_memory_limit`을 초과합니다.
- MDS가 수십만 개의 덴트리를 동기식으로 트리밍(`sync trim`)하면 메인 스레드가 락을 잡고 CPU를 100% 점유합니다.
- 이로 인해 Ceph Monitor(`ceph-mon`)로 전송해야 하는 하트비트 메시지(`MDS_BEACON`)가 `mds_beacon_grace`(기본 4초) 내에 나가지 못합니다.
- 모니터는 MDS가 다운된 것으로 오판하여 해당 랭크를 강제 Failover(Standby-replay 교체)시키며, 새 MDS가 메타데이터 저널을 리플레이하는 동안 전체 파일시스템이 수 분간 정지됩니다.
- **해결책**:
  - `async_cache_trim`을 활성화하여 백그라운드 청크 단위로 분할 트리밍 수행.

---

## 4. 엔터프라이즈 운영 런북 및 모니터링 가이드

1. **클라이언트 지연 경고 모니터링**:
   ```bash
   ceph health detail | grep MDS_HEALTH_CLIENT_LATE
   ```
2. **MDS 비콘 및 하트비트 튜닝**:
   ```bash
   ceph config set mds mds_beacon_grace 15
   ceph config set mds mds_cache_trim_threshold 200000
   ```
3. **핫 디렉토리 수동 분할**:
   - 디렉토리 계층별로 담당 MDS를 명시적으로 분리하여 동적 밸런서의 오작동 방지.
