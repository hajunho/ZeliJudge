# Theory: Linux Kernel VFS Path Lookup, RCU-walk and Dcache Architecture

## 1. 개요: 초당 수억 번의 open()과 VFS의 확장성 위기

리눅스 커널의 VFS(Virtual File System) 계층에서 파일 경로를 해석하는 `link_path_walk()` 함수(`fs/namei.c`)는 운영체제에서 가장 빈번하게 실행되는 핫 패스(Hot Path) 중 하나입니다.

과거 리눅스 커널은 덴트리(Dentry) 트리를 순회할 때마다 각 덴트리의 원자적 참조 카운트(`dentry->d_lock`, `dget()`)를 갱신했습니다. 그러나 멀티소켓 NUMA 서버에서 수십 개의 CPU 코어가 동일한 `/usr/lib/libc.so`를 동시에 조회할 경우, 동일한 캐시 라인에 원자적 쓰기(Atomic Write)가 집중되어 캐시 일관성 프로토콜(MESI) 트래픽으로 인해 시스템 전체 처리량이 급감하는 **캐시 라인 바운싱(Cache line bouncing)** 참사가 발생했습니다.

리눅스 커널 2.6.38(2011)에서 Al Viro와 Nick Piggin은 이를 완전히 혁신하여, 락과 참조 카운트 조작을 완벽하게 제거한 **RCU-walk (`LOOKUP_RCU`)** 아키텍처를 도입했습니다.

---

## 2. RCU-walk와 Ref-walk의 2단계 하이브리드 아키텍처

```
       [경로 탐색 시작: path_init()]
                     |
                     v
             rcu_read_lock()
             flags |= LOOKUP_RCU
                     |
                     v
             +---------------+
             | 컴포넌트 순회 | <----+
             +---------------+      |
                     |              |
           [시퀀스락 검사: d_seq]     |
                     |              |
         +-----------+-----------+  |
         |                       |  |
     (일치: OK)             (불일치/복잡)
         |                       |
     (마운트/심링크?)            v
         |              unlazy_walk()
         v              flags &= ~LOOKUP_RCU
     (다음 컴포넌트)----+       |
                                v
                        [Ref-walk 느린 경로]
```

### 2.1 RCU-walk: 무잠금(Lockless) 낙관적 동시성 제어
- `rcu_read_lock()`을 획득하고 순회합니다. 메모리 해제는 RCU 그레이스 피리어드(Grace Period) 동안 지연되므로, 덴트리 포인터 역참조가 절대 메모리 오류(Use-After-Free)를 일으키지 않습니다.
- **Seqlock 검증 (`dentry->d_seq`)**:
  - 탐색 전: `seq = read_seqcount_begin(&dentry->d_seq)`
  - 해시 탐색 및 문자열 비교 수행.
  - 탐색 후: `read_seqcount_retry(&dentry->d_seq, seq)`
  - 만약 중간에 `rename`이나 `unlink`가 발생했다면 `d_seq`가 변경되어 불일치가 감지됩니다.

### 2.2 Unlazy Walk: 안전한 Ref-walk로의 폴백
RCU-walk 도중 다음과 같은 상황이 발생하면 RCU 고속 경로를 포기하고 `unlazy_walk()`를 호출합니다:
1. **시퀀스락 불일치**: 동시 디렉토리 변경 감지 시.
2. **심볼릭 링크 탐색**: 링크 대상 경로를 읽기 위해 I/O나 메모리 할당이 필요할 때.
3. **마운트 포인트 교차**: 다른 파일시스템 인스턴스로 넘어가기 위해 마운트 테이블 락이 필요할 때.
4. **권한 거부 또는 블록 계층 I/O 대기**: 디스크에서 덴트리를 로드해야 할 때.

`unlazy_walk()`는 현재 덴트리와 마운트 지점의 참조 카운트를 원자적으로 획득하고 RCU 락을 해제한 뒤, 표준적인 참조 카운트 기반 탐색으로 전환합니다.

---

## 3. 마운트 포인트 교차 및 심볼릭 링크 보안

### 3.1 마운트 교차 (Mount Traversal)
- 어떤 디렉토리 덴트리가 마운트 포인트(`DCACHE_MOUNTED`)인 경우, VFS는 해당 덴트리의 자식이 아니라 마운트된 서브트리의 루트 덴트리(`mnt->mnt_root`)로 포인터를 스위칭합니다.
- 상향 이동(`..`) 시에도 마운트 포인트를 역방향으로 탈출하여 호스트 파일시스템으로 복귀합니다.

### 3.2 심볼릭 링크 루프 방지 (ELOOP)
- 심볼릭 링크는 무한 순환(`a -> b -> a`)할 수 있습니다.
- 리눅스 커널은 `MAX_NESTED_LINKS` (통상 40) 한계를 두어, 중첩 링크 수가 이 값을 초과하면 즉시 `-ELOOP (Too many levels of symbolic links)` 에러를 반환합니다.
