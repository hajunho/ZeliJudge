# 문제 286: 리눅스 VFS 디렉터리 엔트리 캐시(dcache) & RCU-walk 및 네거티브 덴트리 블룸 가드 엔진 (Linux VFS Dentry Cache, RCU-walk & Negative Dentry Bloom Guard Engine)

## 문제 설명

리눅스 커널의 가상 파일 시스템(VFS, Virtual File System)에서 파일 경로 해석(`path_lookupat()`)은 시스템 콜 빈도가 가장 높은 핵심 연산 중 하나입니다. `/usr/local/bin/python`과 같은 경로를 열 때마다 디스크 블록을 직접 읽어 디렉터리를 탐색한다면 파일 I/O 성능이 파멸적으로 저하됩니다.

이를 방지하기 위해 리눅스 커널은 경로의 각 컴포넌트(디렉터리 및 파일명)를 메모리에 캐싱하는 **덴트리 캐시(Dentry Cache, `struct dentry`)**와 고유 번호를 가진 **아이노드(`struct inode`)** 분리 아키텍처를 운용합니다.

커널 VFS 서브시스템의 핵심 메커니즘은 다음과 같습니다:

1. **2단계 경로 순회 (RCU-walk vs Ref-walk)**:
   - **RCU-walk (빠른 경로)**: 락을 전혀 획득하지 않고 참조 횟수(`d_count`)도 올리지 않은 채 RCU 읽기 임계 영역에서 순수 포인터 추적만으로 디렉터리 트리를 질주합니다. 각 덴트리의 시퀀스 락(`d_seq`)을 검증하며, 순회 도중 동시 쓰기(파일 생성/삭제)로 시퀀스가 불일치하거나 블로킹이 필요해지면 `unlazy_walk()`를 호출하여 **Ref-walk**로 안전하게 폴백(Fallback)합니다.
   - **Ref-walk (느린 경로)**: 각 덴트리마다 락(`d_lock`)과 참조 카운트를 안전하게 증가시키며 순회합니다.
2. **네거티브 덴트리 (Negative Dentry, `d_inode == NULL`)**:
   - 존재하지 않는 파일에 대한 `open()`이나 `stat()` 호출 시 매번 디스크를 뒤지는 오버헤드를 막기 위해, 커널은 "이 파일은 존재하지 않음"을 나타내는 **네거티브 덴트리**를 dcache에 생성합니다.
   - **부활(Resurrection)**: 네거티브 덴트리가 존재하는 경로에 실제로 새 파일이 생성되면, 새 덴트리를 할당하지 않고 기존 네거티브 덴트리에 새 `inode`를 연결하여 양성(Positive) 덴트리로 재활용합니다.
   - **삭제(Unlink)**: 파일이 삭제되면 덴트리를 즉시 해제하지 않고 `inode` 참조를 끊어 네거티브 덴트리로 전환합니다.
3. **네거티브 덴트리 폭증(Bloat)과 DoS 취약점**:
   - 컴파일러(GCC/Clang)의 방대한 헤더 인클루드 경로 탐색이나 웹 취약점 스캐너의 무작위 파일 프로빙 공격은 수백만 개의 네거티브 덴트리를 양산하여 커널 슬랩(Slab) 메모리를 고갈시키는 심각한 성능 저하를 초래합니다.
   - 커널은 LRU 리스트와 슬랩 슈링커(`prune_dcache_sb()`)를 통해 메모리 압박 시 오래된 네거티브 덴트리를 회수합니다.
4. **블룸 가드 (Bloom Guard 방어 메커니즘)**:
   - 무작위 일회성 스캔 공격에 의한 슬랩 메모리 오염을 막기 위해, 한 번도 요청된 적 없는 완전히 차가운(Cold) 미스 경로는 즉시 네거티브 덴트리로 캐싱하지 않고, 재차 요청이 확인된 반복 미스 경로만 선별적으로 캐싱합니다.

당신은 리눅스 VFS의 덴트리 캐시, RCU-walk 경로 순회, 네거티브 덴트리 라이프사이클 및 블룸 가드 방어 엔진을 완벽히 시뮬레이션해야 합니다.

---

## 입력 형식 (JSON)

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다.

```json
{
  "config": {
    "max_negative_dentries": 16,
    "bloom_guard": true
  },
  "operations": [
    {
      "step": 1,
      "op": "CREATE_FILE",
      "path": "/etc/hosts",
      "is_dir": false
    },
    {
      "step": 2,
      "op": "LOOKUP_PATH",
      "path": "/etc/hosts",
      "mode": "RCU_WALK",
      "concurrent_seq_change": []
    },
    {
      "step": 3,
      "op": "UNLINK_FILE",
      "path": "/etc/hosts"
    },
    {
      "step": 4,
      "op": "SHRINK_DCACHE",
      "count": 5
    },
    {
      "step": 5,
      "op": "GET_SNAPSHOT"
    }
  ]
}
```

### 연산 종류
1. `CREATE_FILE`: 지정된 경로에 디렉터리 또는 파일을 생성합니다. 경로상의 디렉터리가 없으면 자동 생성합니다. 해당 경로에 이미 네거티브 덴트리가 존재할 경우 양성 덴트리로 부활(Resurrect)시킵니다.
2. `LOOKUP_PATH`: 경로를 순회합니다. `mode`는 `RCU_WALK` 또는 `REF_WALK`입니다. `concurrent_seq_change`에 순회 경로 상의 덴트리 ID가 포함되어 있으면 시퀀스 불일치로 간주하여 `unlazy_fallback: true`로 기록하고 `REF_WALK`로 전환합니다. 존재하지 않는 파일 발견 시 `bloom_guard` 정책에 따라 네거티브 덴트리를 생성하거나 건너뜁니다.
3. `UNLINK_FILE`: 기존 양성 덴트리의 아이노드를 제거하여 네거티브 덴트리로 전환하고 LRU에 등록합니다.
4. `SHRINK_DCACHE`: 슬랩 메모리 회수를 시뮬레이션하여 가장 오래된 네거티브 덴트리 `count`개를 LRU에서 제거(Prune)합니다.
5. `GET_SNAPSHOT`: 총 덴트리 수, 양성/음성 덴트리 수, LRU 순서 및 통계 메트릭 스냅샷을 반환합니다.

---

## 출력 형식 (JSON)

표준 출력(stdout)으로 다음 스키마를 만족하는 단일 줄 JSON 객체를 출력합니다.

```json
{
  "operations_log": [
    {
      "step": 1,
      "op": "CREATE_FILE",
      "path": "/etc/hosts",
      "dentry_id": "d_2",
      "inode_id": 3,
      "is_dir": false
    },
    {
      "step": 2,
      "op": "LOOKUP_PATH",
      "path": "/etc/hosts",
      "found": true,
      "inode_id": 3,
      "hit_type": "POSITIVE_DENTRY_HIT",
      "final_dentry": "d_2",
      "walked_dentries": ["d_root", "d_1", "d_2"],
      "unlazy_fallback": false
    }
  ],
  "final_state": {
    "total_dentries": 3,
    "positive_dentries_count": 3,
    "negative_dentries_count": 0,
    "negative_lru_order": [],
    "metrics": {
      "lookups_total": 1,
      "rcu_walk_success": 1,
      "rcu_walk_fallback_unlazy": 0,
      "positive_dentry_hits": 1,
      "negative_dentry_hits": 0,
      "negative_dentries_created": 0,
      "negative_dentries_pruned": 0
    }
  }
}
```

---

## 제약 조건

- 최대 네거티브 덴트리 용량: $1 \le \text{max\_negative\_dentries} \le 64$
- 연산 수: $1 \le M \le 50$
- 경로 문자열 길이: $1 \le |\text{path}| \le 128$
- 루트 덴트리 ID는 항상 `d_root`, 루트 아이노드 번호는 `1`입니다.
