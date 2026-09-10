# 분산 파일 시스템 CephFS 메타데이터 서버(MDS) Inode Capabilities(Caps) 회수 및 동적 서브트리 파티셔닝 엔진

## 문제 설명

대규모 클라우드 및 HPC 환경에서 사용되는 오픈소스 분산 파일 시스템 **CephFS**는 POSIX 호환성을 제공하면서도 수십억 개의 파일과 페타바이트급 데이터를 선형적으로 확장할 수 있도록 설계되었습니다. 일반적인 분산 파일 시스템(HDFS, GlusterFS, Lustre 등)과 차별화되는 CephFS의 두 가지 핵심 혁신 기술은 **동적 서브트리 파티셔닝(Dynamic Subtree Partitioning)**과 **클라이언트 Inode Capabilities(Caps)** 모델입니다.

1. **동적 서브트리 파티셔닝 (Dynamic Subtree Partitioning)**:
   전통적인 분산 파일 시스템이 고정된 해시나 정적 디렉터리 분할을 사용하는 것과 달리, CephFS의 메타데이터 서버(MDS) 클러스터는 디렉터리 서브트리(Subtree) 단위로 부하를 실시간 측정하여 과부하가 걸린 서브트리를 다른 활성 MDS 랭크(MDS Rank)로 무중단 라이브 마이그레이션(`EXPORT_PREP` $\to$ `EXPORT_GO` $\to$ `ACTIVE`)합니다.
2. **클라이언트 Inode Capabilities (Caps)**:
   클라이언트가 파일을 읽거나 쓸 때마다 매번 MDS에 질의하면 MDS가 병목이 됩니다. CephFS는 클라이언트에게 특정 Inode에 대한 캐싱 및 접근 권한인 **Capability(Cap)**를 대여(Lease)합니다.
   - **공유 읽기(Shared Read, `Fs | Fc`)**: 여러 클라이언트가 동시에 파일을 로컬 캐시에 저장하고 읽을 수 있습니다.
   - **독점 쓰기(Exclusive Write, `Fs | Fc | Fw | Fx`)**: 단 하나의 클라이언트만이 파일에 버퍼링된 쓰기(`Fw`)를 수행하고 파일 크기/수정 시간을 로컬에서 갱신할 수 있습니다.
   - **충돌 및 회수(Revocation)**: 독점 쓰기를 가진 클라이언트가 있는 상태에서 다른 클라이언트가 읽기를 요청하면, MDS는 쓰기 클라이언트에게 `REVOKE_CAP` 메시지를 보내 버퍼링된 더티 데이터를 스토리지로 플러시하도록 강제하고 권한을 `Fs`로 다운그레이드합니다. 반대로 읽기 클라이언트들이 존재하는 상태에서 한 클라이언트가 독점 쓰기를 요청하면, 모든 읽기 클라이언트의 Cap이 전량 회수됩니다.

본 문제에서는 CephFS의 **MDS 동적 서브트리 파티셔닝 및 클라이언트 Inode Capabilities 엔진**을 정밀하게 구현해야 합니다.

---

## 시스템 아키텍처 및 Cap 상태 전이도

```
+---------------------------------------------------------------------------------------------------+
|               Distributed CephFS MDS Subtree Partitioning & Inode Caps Engine                    |
+---------------------------------------------------------------------------------------------------+

     [ Dynamic Subtree Partitioning across MDS Ranks ]
     +--------------------------------------------------------------------+
     | Root Subtree "/"                     -> MDS Rank 0                 |
     | Exported Subtree "/export"           -> MDS Rank 1                 |
     | Nested Subtree "/export/user/alice"  -> MDS Rank 2                 |
     | Resolution: Longest Prefix Match (LPM) on Subtree Map              |
     +--------------------------------------------------------------------+
                                      |
                                      v
     [ Client Inode Capabilities (Caps) & Conflict Resolution ]
     
     Client A requests READ (/file)               Client B requests WRITE (/file)
                 |                                                |
                 v                                                v
     +-----------------------+                        +-----------------------+
     | Grant Shared Read     |                        | Check Existing Caps   |
     | Caps: ["Fc", "Fs"]    |                        | Any Readers/Writers?  |
     +-----------------------+                        +-----------------------+
                 |                                                |
                 | (Concurrent Reads OK)                          v (Conflict!)
                 |                                    +-----------------------+
                 +----------------------------------> | Revoke Client A Caps  |
                                                      | Wait Dirty Flush      |
                                                      +-----------------------+
                                                                  |
                                                                  v
                                                      +-----------------------+
                                                      | Grant Exclusive Write |
                                                      | Caps: Fc, Fs, Fw, Fx  |
                                                      +-----------------------+
                                                                  |
                                                                  v
                                                      +-----------------------+
                                                      | Buffer Local Writes   |
                                                      | (Mark Dirty Inode)    |
                                                      +-----------------------+
```

---

## 엔진 명세 및 규칙

### 1. MDS 랭크 및 서브트리 계층 해석
- 시스템은 $M$개의 활성 MDS 랭크($0 \le \text{rank} < M$)를 가집니다.
- 서브트리 테이블은 경로(path)에서 담당 MDS 랭크로의 매핑을 유지하며, 초기에는 루트 경로 `"/"`가 Rank 0에 할당되어 있습니다.
- 임의의 Inode 경로의 담당 MDS 랭크는 서브트리 테이블에서 **최장 접두사 일치(Longest Prefix Match, LPM)**를 통해 결정됩니다.
  (예: 서브트리에 `"/"` (Rank 0)과 `"/export"` (Rank 1)가 등록되어 있을 때, `"/export/docs/readme.txt"`는 `"/export"`에 매칭되어 Rank 1이 담당합니다.)

### 2. Inode 생성 (`CREATE_INODE`)
- `path`, `type` (`"DIR"` 또는 `"FILE"`), `size`를 받아 Inode를 생성합니다.
- 메타데이터 버전은 1로 초기화됩니다.
- Inode의 담당 MDS 랭크와 서브트리 루트 경로를 반환합니다.

### 3. 서브트리 분할 및 마이그레이션 (`SPLIT_SUBTREE`)
- 지정된 디렉터리 경로(`path`)를 서브트리 경계로 지정하고 목적지 MDS 랭크(`dst_rank`)로 소유권을 이전합니다.
- `dst_rank < mds_ranks`이어야 하며, 디렉터리 Inode가 존재해야 합니다.

### 4. Cap 요청 및 충돌 회수 (`REQUEST_CAP`)
- **READ 요청**:
  - 기존에 `Fx` 또는 `Fw`를 보유한 다른 클라이언트가 존재하면:
    - 해당 클라이언트가 더티 상태(`dirty == True`)인 경우, 버퍼링된 데이터를 즉시 커밋(플러시)하여 Inode 크기 및 버전을 갱신합니다.
    - 해당 클라이언트의 Cap을 독점에서 공유 읽기(`{"Fs", "Fc"}`)로 다운그레이드하고 회수 기록(`revocations`)에 추가합니다.
  - 요청 클라이언트에게 `{"Fs", "Fc"}` Cap을 부여합니다.
- **WRITE 요청**:
  - 기존에 Cap을 보유한 모든 다른 클라이언트(읽기 또는 쓰기)에 대해:
    - 더티 상태이면 데이터를 커밋(플러시)하여 Inode 크기/버전을 갱신합니다.
    - 해당 클라이언트의 Cap을 전량 회수(`set()`)하고 회수 기록(`revocations`)에 추가합니다.
  - 요청 클라이언트에게 `{"Fs", "Fc", "Fw", "Fx"}` Cap을 부여합니다.

### 5. 버퍼링된 데이터 쓰기 (`WRITE_DATA`)
- 클라이언트가 유효한 쓰기 Cap(`Fw`)을 보유하고 있어야 합니다.
- Inode를 즉시 디스크에 쓰지 않고 클라이언트 로컬에서 버퍼링(`dirty = True`, `size = new_size`)합니다.

### 6. Cap 플러시 (`FLUSH_CAPS`)
- 클라이언트의 더티 플래그가 참이면:
  - Inode의 크기를 클라이언트의 버퍼링된 크기로 커밋하고 버전을 1 증가시킵니다.
  - 클라이언트의 `dirty` 플래그를 `False`로 해제합니다.

---

## 입력 형식

표준 입력(stdin)으로 다음 구조의 JSON 객체가 주어집니다:

```json
{
  "config": {
    "mds_ranks": 3
  },
  "operations": [
    {
      "op": "CREATE_INODE",
      "path": "/export",
      "type": "DIR"
    },
    {
      "op": "SPLIT_SUBTREE",
      "path": "/export",
      "dst_rank": 1
    },
    {
      "op": "CREATE_INODE",
      "path": "/export/file.txt",
      "type": "FILE",
      "size": 100
    },
    {
      "op": "REQUEST_CAP",
      "client_id": "client1",
      "path": "/export/file.txt",
      "cap_type": "WRITE"
    },
    {
      "op": "WRITE_DATA",
      "client_id": "client1",
      "path": "/export/file.txt",
      "new_size": 2048
    },
    {
      "op": "REQUEST_CAP",
      "client_id": "client2",
      "path": "/export/file.txt",
      "cap_type": "READ"
    }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 각 연산의 수행 결과와 최종 클러스터 상태를 담은 JSON 객체를 공백 없는 압축 형식(`separators=(',', ':')`)으로 출력합니다:

```json
{
  "results": [
    {
      "status": "CREATED",
      "path": "/export",
      "mds_rank": 0,
      "subtree_root": "/"
    }
  ],
  "cluster_state": {
    "stats": {
      "cap_grants": 2,
      "cap_revocations": 1,
      "cap_flushes": 1,
      "subtree_migrations": 1,
      "dirty_cap_updates": 1
    },
    "subtrees": {
      "/": {"rank": 0, "state": "ACTIVE"},
      "/export": {"rank": 1, "state": "ACTIVE"}
    },
    "total_inodes": 3,
    "active_clients": ["client1", "client2"]
  }
}
```

---

## 제약 조건

- 연산 수: $1 \le Q \le 5,000$
- MDS 랭크 수: $1 \le M \le 16$
- 파일 경로 깊이: $1 \le \text{depth} \le 32$
- 지원 연산: `CREATE_INODE`, `SPLIT_SUBTREE`, `REQUEST_CAP`, `WRITE_DATA`, `FLUSH_CAPS`
- 표준 라이브러리만을 사용하여 구현해야 함
