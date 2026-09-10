# 이론적 배경: 리눅스 커널 VFS dcache, RCU-walk 및 네거티브 덴트리 방어 기법

## 1. 리눅스 가상 파일 시스템(VFS) 4대 핵심 객체

리눅스 커널의 VFS 계층은 서로 다른 파일 시스템(ext4, XFS, Btrfs, NFS, procfs 등)을 단일한 유닉스 파일 인터페이스로 추상화합니다:

1. **슈퍼블록 (`struct super_block`)**: 마운트된 특정 파일 시스템 전체의 메타데이터 및 블록 크기 정보.
2. **아이노드 (`struct inode`)**: 파일의 물리적 실체 (권한, 크기, 수정 시간, 블록 주소 포인터). 파일명을 포함하지 않습니다.
3. **덴트리 (`struct dentry`)**: 경로 이름의 컴포넌트(디렉터리명, 파일명)와 아이노드를 연결하는 메모리 캐시 객체.
4. **파일 객체 (`struct file`)**: 프로세스가 `open()`하여 보유한 열린 파일의 인스턴스 (현재 오프셋 `f_pos`, 접근 플래그 등).

---

## 2. RCU-walk vs Ref-walk (경로 순회의 최적화)

리눅스 2.6 시절까지 경로 순회는 매 디렉터리 단계마다 덴트리의 스핀락(`d_lock`)을 획득하고 참조 카운트(`d_count`)를 원자적 명령(`lock xadd`)으로 증가시켰습니다. 멀티코어 환경에서 수십 개의 스레드가 `/etc/passwd`나 `/dev/null` 같은 동일한 경로를 동시에 열면, CPU 간 L1/L2 캐시 라인 바운싱으로 인해 막대한 확장성 병목이 발생했습니다.

리눅스 2.6.38에서 알 비롤(Al Viro)과 닉 피곳(Nick Piggin)은 **RCU-walk (`LOOKUP_RCU`)**를 도입했습니다:

```
[ User Space: open("/var/log/syslog") ]
                   |
                   v
   +---------------------------------------+
   | RCU-walk (Lockless / Zero atomic ops) |
   | - rcu_read_lock()                     |
   | - Traverse dentry->d_child using d_seq|
   +---------------------------------------+
            /                      \
    (No Mutation)             (Concurrent Mutation / Block Needed)
          v                                v
   [ Fast Success! ]              [ unlazy_walk() Fallback ]
                                  - Transition to Ref-walk
                                  - Acquire d_lock & bump d_count
```

- **시퀀스 락 검증 (`read_seqcount_retry`)**: 덴트리 순회 시작 시의 시퀀스 번호와 종료 시의 번호가 일치하면, 순회 도중 아무도 디렉터리를 변경하지 않았음이 보증되므로 락 없이 즉시 경로 해석이 완료됩니다.
- **`unlazy_walk()` 폴백**: 순회 도중 부모 디렉터리에 새 파일이 추가/삭제되어 시퀀스가 홀수(쓰기 진행 중)이거나 변경된 경우, 커널은 안전하게 참조 카운트를 올리는 전통적인 **Ref-walk**로 전환하여 레이스 컨디션을 방지합니다.

---

## 3. 네거티브 덴트리(Negative Dentry)의 양날의 검

- **순기능 (Performance Booster)**:
  `gcc -I/inc1 -I/inc2 ... foo.c`를 실행하면 컴파일러는 수십 개의 디렉터리에서 `stdio.h`를 찾기 위해 엄청난 횟수의 `stat()`을 호출합니다. 존재하지 않는 헤더 파일 경로에 대해 매번 ext4 저널과 디스크를 뒤진다면 컴파일 속도가 10배 이상 느려집니다. 네거티브 덴트리는 파일 부재(`ENOENT`)를 메모리에 캐싱하여 디스크 I/O를 완벽히 회피합니다.
- **역기능 (The Negative Dentry Bloat & DoS)**:
  악의적인 공격자가 `/var/www/nonexistent_<random_uuid>.html` 형태로 무작위 요청을 초당 수만 건씩 쏟아부으면, 커널 메모리의 `dentry_cache` 슬랩이 수 기가바이트 규모로 팽창하여 실제 유효한 파일의 캐시를 밀어내고 시스템을 OOM(Out of Memory) 상태로 몰아넣습니다.

---

## 4. 슬랩 슈링커(`prune_dcache_sb`)와 블룸 가드(Bloom Guard)

1. **LRU 슬랩 슈링커**:
   - 모든 네거티브 덴트리는 파일 시스템의 언마운트 가능한 LRU 리스트에 연결됩니다.
   - 커널 메모리가 부족해지면 백그라운드 데몬 `kswapd`가 `prune_dcache_sb()`를 호출하여 참조 카운트가 0인 오래된 네거티브 덴트리부터 메모리를 회수합니다.
   - `/proc/sys/vm/vfs_cache_pressure` 설정값에 따라 페이지 캐시 대비 덴트리 캐시의 회수 우선순위를 제어합니다.
2. **블룸 가드 (Bloom Filter Defense)**:
   - 클라우드 네이티브 및 컨테이너 환경에서는 악의적 프로빙 공격을 차단하기 위해 dcache 앞단에 블룸 필터(Bloom Filter)를 배치합니다.
   - 무작위 일회성 요청은 블룸 필터에만 기록되고 dcache 슬랩 메모리를 소비하지 않으며, 동일 경로가 2회 이상 질의되어 국소성(Locality)이 입증된 경우에만 정식 네거티브 덴트리로 승격시킵니다.
