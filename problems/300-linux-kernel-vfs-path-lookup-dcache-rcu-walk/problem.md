# 리눅스 커널 VFS 경로 조회 및 dcache RCU-Walk 대 Ref-Walk 엔진 (Linux Kernel VFS Path Lookup & dcache RCU-Walk vs Ref-Walk Engine)

## 문제 설명

리눅스 커널의 **가상 파일 시스템(VFS - Virtual File System)**은 파일 경로를 해석(`path_lookupat()`, `lookup_fast()`, `lookup_slow()`)할 때 수백 개의 CPU 코어가 동시에 동일한 디렉터리 트리를 탐색하더라도 병목이 발생하지 않도록 세계 최고 수준의 고성능 동시성 아키텍처를 구현하고 있습니다.

핵심 메커니즘은 **디렉터리 엔트리 캐시(dcache - `fs/dcache.c`)**를 활용한 2단계 경로 해석 모델입니다:
1. **RCU-Walk 모드 (`LOOKUP_RCU`)**:
   - 락(Lock)을 전혀 획득하지 않고, 객체의 참조 카운트(`d_count`)조차 증가시키지 않는 완벽한 락리스(Lockless) 초고속 경로 탐색입니다.
   - 각 dentry의 **시퀀스 카운터(Sequence Counter - `seqlock`)**를 검증(`read_seqcount_begin()` / `read_seqcount_retry()`)하여 동시적 변경이 없었는지를 사후 검증합니다.
2. **Ref-Walk 모드 (참조 기반 폴백 - `unlazy_walk()` / `LOOKUP_REF`)**:
   - dcache에 항목이 없거나(Cache Miss),
   - 심볼릭 링크(Symlink)를 만나 대상을 역참조해야 하거나,
   - 동시적인 디렉터리 이름 변경/삭제(Rename)로 인해 시퀀스 카운터 검증에 실패할 경우,
   - 커널은 즉시 RCU-walk를 포기하고 안전한 Ref-Walk 모드로 폴백(`unlazy_walk`)하여 dentry 참조 카운트를 취득하고 디렉터리 뮤텍스를 통해 안전하게 조회를 완료합니다.

또한 VFS는 존재하지 않는 파일에 대한 불필요한 디스크 I/O를 원천 차단하기 위해 **음수 덴트리 캐싱(Negative Dentry Caching - `d_is_negative()`)**을 수행하며, 무한 루프 심볼릭 링크를 방지하기 위해 최대 40개의 심볼릭 링크 홉(`MAXSYMLINKS = 40`) 제한을 강제(`ELOOP`)합니다.

본 문제에서는 리눅스 커널 `fs/namei.c` 및 `fs/dcache.c`의 실제 핵심 알고리즘을 충실히 모델링한 VFS 경로 해석 시뮬레이터를 구현합니다.

---

## 동작 명세

### 1. VFS 트리 및 dcache 캐시 구조
- 각 파일 및 디렉터리는 고유한 `inode_id`와 시퀀스 번호(`seq`, 초기 짝수 2)를 가집니다.
- dcache 해시 테이블은 `(parent_inode, component_name) -> (node, seq)` 형태로 매핑됩니다.
- 존재하지 않는 파일 탐색 시 `(parent_inode, component_name) -> (None, 0)` 형태의 음수 덴트리(Negative Dentry)가 dcache에 등록됩니다.

### 2. RCU-Walk 탐색 규칙
- 경로 조회가 시작될 때 기본적으로 `RCU_WALK` 모드로 시작합니다.
- 각 경로 요소(Component)를 탐색할 때:
  1. `cached = dcache.get((parent_inode, comp))` 조회.
  2. 만약 캐시에 존재하지 않으면(Cache Miss):
     - `unlazy_walk_fallbacks += 1`, `dcache_misses += 1`.
     - 즉시 `REF_WALK` 모드로 전이하여 실제 디렉터리 자식 목록을 직접 탐색합니다.
     - 실제 디렉터리에 존재하면 dcache에 등록하고 계속 진행하며, 존재하지 않으면 음수 덴트리를 등록하고 `ENOENT`를 반환합니다.
  3. 캐시에 존재하지만 `child is None`이면:
     - `negative_dentry_hits += 1` 증가 후 즉시 `ENOENT` 반환.
  4. 시퀀스 락 검증:
     - `child.seq != cached_seq`이거나 `child.seq % 2 != 0` (홀수: 동시 변경 진행 중)인 경우:
     - 시퀀스 불일치가 감지되어 즉시 `unlazy_walk_fallbacks += 1` 후 `REF_WALK` 모드로 전환하여 안전하게 재검증합니다.
  5. 시퀀스 일치 시 `dcache_hits += 1` 증가 후 다음 요소로 이동합니다.

### 3. 심볼릭 링크 처리 및 ELOOP 검출
- 탐색 도중 노드가 심볼릭 링크(`is_symlink == True`)인 경우:
  - `symlinks_resolved += 1`.
  - 심볼릭 링크 홉 횟수가 `max_symlinks`를 초과하면 즉시 `ELOOP` 오류를 반환합니다.
  - RCU-walk 모드였다면 즉시 `unlazy_walk_fallbacks += 1` 후 `REF_WALK` 모드로 전환합니다.
  - 심볼릭 링크의 목적지(`symlink_target`)가 `/`로 시작하면 절대 경로로 교체하고, 상대 경로이면 부모 디렉터리 경로를 기준으로 결합하여 경로 해석 루프를 재개합니다.

### 4. `.` 및 `..` 부모 디렉터리 순회
- 경로 요소가 `.`이면 현재 디렉터리를 유지합니다.
- 경로 요소가 `..`이면 부모 디렉터리 노드(`curr_node.parent`)로 거슬러 올라갑니다 (루트의 부모는 루트 자신).

---

## 입력 형식

JSON 형식으로 표준 입력에 전달됩니다.

```json
{
  "config": {
    "max_symlinks": 40
  },
  "operations": [
    {"type": "ADD_PATH", "path": "/var/log/nginx/access.log", "is_dir": false},
    {"type": "LOOKUP", "path": "/var/log/nginx/access.log"},
    {"type": "LOOKUP", "path": "/var/log/nginx/missing.log"},
    {"type": "LOOKUP", "path": "/var/log/nginx/missing.log"}
  ]
}
```

---

## 출력 형식

```json
{
  "history": [
    {"path": "/var/log/nginx/access.log", "inode_id": 5, "is_dir": false, "mode_completed": "RCU_WALK", "status": "SUCCESS"},
    {"path": "/var/log/nginx/missing.log", "status": "ENOENT", "mode_completed": "REF_WALK"},
    {"path": "/var/log/nginx/missing.log", "status": "ENOENT", "mode_completed": "RCU_WALK"}
  ],
  "stats": {
    "total_lookups": 3,
    "rcu_walk_successes": 1,
    "unlazy_walk_fallbacks": 1,
    "dcache_hits": 10,
    "dcache_misses": 1,
    "negative_dentry_hits": 1,
    "symlinks_resolved": 0,
    "eloop_errors": 0
  }
}
```
