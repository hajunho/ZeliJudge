# Linux Kernel VFS 경로 해석: RCU-walk, Ref-walk, Seqlock 및 마운트 교차 엔진

## 문제 설명

리눅스 커널의 가상 파일 시스템(VFS, Virtual File System, `fs/namei.c`, `fs/dcache.c`)에서 **경로 해석(Path Lookup)**은 `open(2)`, `stat(2)`, `execve(2)` 등 모든 파일 I/O 시스템 콜의 관문입니다. 초대규모 멀티코어 서버 환경에서는 초당 수억 회의 경로 조회가 발생하므로, 전통적인 락 획득(Spinlock)이나 원자적 참조 카운트(`dget()`) 증가는 극심한 캐시 라인 바운싱(Cache line bouncing)과 CPU 병목을 유발합니다.

이를 극복하기 위해 리눅스 커널은 혁신적인 **2단계 하이브리드 경로 해석 아키텍처**를 채택하고 있습니다:
1. **고속 경로: RCU-walk (`LOOKUP_RCU`)**:
   - `rcu_read_lock()` 보호 하에 락이나 참조 카운트 증가 없이 순수 포인터 추적만으로 덴트리(Dentry) 트리를 초고속 탐색합니다.
   - 각 덴트리와 부모 디렉토리의 일관성은 **시퀀스 락(Sequence Lock, `dentry->d_seq`)**을 통해 검증합니다.
   - 읽기 도중 동시 쓰기(`rename`, `unlink`, 마운트 등)로 인해 시퀀스 번호가 불일치하거나 심볼릭 링크를 마주하면, 즉시 안전한 느린 경로로 전환합니다.
2. **느린 경로: Ref-walk (Unlazy Walk, `unlazy_walk()`)**:
   - RCU-walk가 중단된 지점에서 참조 카운트를 안전하게 획득(`dget()`)하고, `dentry->d_lock`을 잠근 뒤 정밀 검증을 수행합니다.
   - 파일시스템 마운트 경계(`mounted_root`) 교차 및 심볼릭 링크 확장(`MAX_NESTED_LINKS` 순환 검사)을 처리합니다.

```
                             +-------------------------------+
                             |    경로 해석 요청 (예: /a/b/c)  |
                             +-------------------------------+
                                             |
                                             v
                           +-----------------------------------+
                           | 1단계: RCU-walk (Lockless 고속 탐색)|
                           +-----------------------------------+
                                             |
                         +-------------------+-------------------+
                         |                                       |
                 [d_seq 일치 & 정상]                     [경합/마운트/심링크]
                         |                                       |
                         v                                       v
                  다음 컴포넌트 이동                       unlazy_walk()
                         |                               (RCU -> REF 전환)
                         v                                       |
                  최종 파일 도달                                  v
                                             +-----------------------------------+
                                             | 2단계: Ref-walk (참조 카운트 획득) |
                                             +-----------------------------------+
                                                                 |
                                                                 v
                                                          최종 파일 도달
```

본 문제에서는 리눅스 커널 VFS의 RCU-walk / Ref-walk 전환 메커니즘을 모사하는 **이산 VFS 경로 해석 및 덴트리 캐시 엔진**을 구현해야 합니다.

---

## 핵심 메커니즘 및 명세

### 1. VFS 구조체
- **Inode (`ino`)**: 고유 번호, 모드, 디렉토리 여부(`is_dir`), 심볼릭 링크 대상(`symlink_target`).
- **Dentry (`name`, `parent`, `inode`, `d_seq`)**:
  - 이름, 부모 덴트리 포인터, 아이노드 포인터.
  - `d_seq`: 시퀀스 락 카운터 (0에서 시작하며 디렉토리 내 자식 생성/삭제/이름변경 시 증가).
  - `children`: 하위 자식 덴트리 매핑 (`name -> Dentry`).
  - `mounted_root`: 해당 덴트리에 파일시스템이 마운트된 경우, 마운트된 루트 덴트리를 가리킴.

### 2. 연산 명세
1. `CREATE`:
   - 파라미터: `path`, `is_dir` (기본 `false`), `symlink_target` (기본 `null`)
   - 부모 디렉토리를 탐색하고 신규 아이노드 및 덴트리를 생성합니다.
   - 부모 덴트리의 `d_seq`를 1 증가시킵니다.
   - 반환: `{"status": "CREATED", "path": path, "ino": ino, "is_dir": is_dir, "symlink_target": symlink_target}`
2. `RENAME`:
   - 파라미터: `old_path`, `new_path`
   - 기존 덴트리를 새 위치로 이동하고 이름을 변경합니다.
   - 원본 부모 덴트리, 이동 대상 덴트리, 대상 부모 덴트리의 `d_seq`를 각각 1 증가시켜 동시 RCU 경로 해석을 무효화합니다.
   - 반환: `{"status": "RENAMED", "old_path": ..., "new_path": ...}`
3. `MOUNT`:
   - 파라미터: `path`
   - 대상 디렉토리 덴트리에 새 루트 덴트리를 연결(`mounted_root`)하고 `d_seq`를 1 증가시킵니다.
   - 반환: `{"status": "MOUNTED", "path": path, "mounted_ino": ...}`
4. `LOOKUP_PATH`:
   - 파라미터: `path`, `simulate_rcu_fail_at` (기본 `null`), `follow_symlinks` (기본 `true`)
   - 루트(`/`)부터 시작하여 컴포넌트별로 경로를 탐색합니다.
   - 모드: 초기에는 `"RCU"`로 시작합니다.
     - 컴포넌트 이름이 `simulate_rcu_fail_at`과 일치하면, 시퀀스락 불일치로 간주하여 모드를 즉시 `"REF"`로 전환하고 `fell_back_to_ref = true`, `ref_steps += 1`을 기록합니다.
     - 일치하지 않고 `"RCU"` 상태이면 `rcu_steps += 1`을 기록합니다.
     - 이미 `"REF"` 모드이면 `ref_steps += 1`을 기록합니다.
   - 마운트 교차: 현재 덴트리에 `mounted_root`가 존재하면, 마운트된 루트로 진입하며 `mount_crossings += 1`, 모드를 `"REF"`로 전환합니다 (`fell_back_to_ref = true`).
   - 상대경로: `.`는 현재 위치 유지, `..`는 부모 덴트리로 이동.
   - 심볼릭 링크: 대상 아이노드가 심볼릭 링크이고 `follow_symlinks = true`이면:
     - `symlinks_followed += 1`, 모드를 `"REF"`로 전환합니다.
     - 누적 링크 수가 `max_nested_links`를 초과하면 즉시 `{"status": "ELOOP_SYMLINK_LOOP", "failed_at": comp, "stats": ...}`를 반환합니다.
     - 대상 경로(`symlink_target`)가 `/`로 시작하면 루트부터 재귀 해석하고, 아니면 현재 디렉토리 기준 상대 해석합니다.
   - 탐색 성공 시: `{"status": "FOUND", "ino": ..., "is_dir": ..., "dentry_name": ..., "stats": stats}`
   - 컴포넌트 부재 시: `{"status": "NOT_FOUND", "failed_at": comp, "curr_path": ..., "stats": stats}`

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 전달됩니다:
```json
{
  "config": {
    "max_nested_links": 10
  },
  "operations": [
    { "op": "CREATE", "path": "/etc", "is_dir": true },
    { "op": "CREATE", "path": "/etc/passwd", "is_dir": false },
    { "op": "LOOKUP_PATH", "path": "/etc/passwd" },
    { "op": "LOOKUP_PATH", "path": "/etc/passwd", "simulate_rcu_fail_at": "passwd" }
  ]
}
```

## 출력 형식

표준 출력(stdout)으로 각 연산의 수행 결과를 담은 JSON 배열을 공백 없이(compact) 출력합니다.

---

## 제약 사항

- 경로 깊이 $D \le 50$
- $1 \le \text{max\_nested\_links} \le 40$
- 연산 수 $N \le 5000$
- 시간 복잡도: 각 경로 해석 $O(D)$ 이내.
