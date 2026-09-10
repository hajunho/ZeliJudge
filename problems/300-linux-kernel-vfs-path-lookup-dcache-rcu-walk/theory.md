# 리눅스 커널 VFS 경로 조회와 dcache RCU-Walk 아키텍처 (Linux VFS Path Lookup & dcache RCU-Walk Architecture)

## 1. 개요: 초당 수천만 번의 파일 경로 조회를 처리하는 비결

모든 리눅스 시스템에서 프로세스가 실행하는 시스템 콜(`open`, `stat`, `execve`, `chdir`)의 첫 번째 단계는 사용자가 전달한 문자열 경로(예: `/usr/bin/python3`)를 디스크 상의 파일 메타데이터인 **아이노드(inode)**로 변환하는 **경로 해석(Path Resolution - `fs/namei.c`)**입니다.

과거 유닉스 커널은 경로의 각 디렉터리를 지날 때마다 스핀락(Spinlock)이나 세마포어를 걸고 디렉터리 엔트리의 참조 카운트(`d_count`)를 원자적으로 증가시켰습니다. 그러나 64코어, 128코어 이상의 현대 대형 서버에서는 루트(`/`)나 `/usr`, `/lib` 같은 공통 부모 디렉터리의 참조 카운트 변수에 수백 개의 코어가 동시에 원자적 쓰기(Atomic Increment/Decrement)를 시도하여, 극심한 **캐시 라인 바운싱(Cache Line Bouncing)**과 버스 병목으로 시스템이 마비되었습니다.

이를 해결하기 위해 알 비로(Al Viro)와 닉 피긴(Nick Piggin)은 2011년 리눅스 2.6.38 커널에 **RCU-walk (`LOOKUP_RCU`)**라는 혁신적인 락리스 동시성 아키텍처를 도입했습니다.

---

## 2. RCU-Walk와 시퀀스 락 (Seqlock)의 원리

RCU-walk는 **"아무런 락도 걸지 않고, 참조 카운트도 올리지 않으며, 읽기 전용으로 포인터를 따라간다"**는 대담한 철학을 가집니다:

```
Process on Core 0                    Concurrent Process on Core 1
[read_seqcount_begin(&dentry->d_seq)]
              │
    Read child pointer & inode
              │                      [write_seqlock(&dir->i_rwsem)]
              │                      Rename / Unlink dentry!
              │                      [dentry->d_seq += 1 (Odd: Locked)]
              │                      ...
              │                      [dentry->d_seq += 1 (Even: Unlocked)]
              ▼
[read_seqcount_retry(&dentry->d_seq)]
  └─ seq changed or odd? ───► Invalidate RCU! Fallback to unlazy_walk()!
```

### 2.1 시퀀스 카운터 검증 (Seqlock Validation)
- 디렉터리 엔트리(`dentry`)가 수정(Rename, Unlink, Create)되지 않고 안정된 상태일 때 시퀀스 번호는 항상 **짝수(Even)**입니다.
- 수정이 시작되면 홀수(Odd)가 되고, 수정이 끝나면 다음 짝수로 올라갑니다.
- RCU-walk 탐색자는 시작할 때의 짝수 시퀀스를 기록해두고, 다음 단계로 넘어가기 직전에 현재 시퀀스와 일치하는지(`!read_seqcount_retry()`) 확인합니다.
- 만약 누군가 도중에 디렉터리를 변경했다면 시퀀스가 변경되었거나 홀수이므로 즉시 불일치를 감지합니다.

---

## 3. 참조 기반 폴백 (Ref-Walk: `unlazy_walk()`)의 트리거

RCU-walk는 대부분의 평화로운 읽기 상황을 100% 락리스로 처리하지만, 다음과 같은 복잡하거나 불안정한 상황을 만나면 즉시 안전한 **Ref-walk (`unlazy_walk`)**로 폴백합니다:

1. **dcache 미스 (Cache Miss)**: 메모리 캐시에 디렉터리가 없어 디스크 블록 드라이버(ext4, btrfs)를 읽어야 할 때 (RCU 컨텍스트는 수면/블로킹이 불가하므로 즉시 탈출).
2. **심볼릭 링크 (Symlink Encountered)**: 심볼릭 링크의 문자열 경로를 읽고 목적지를 재귀 탐색할 때.
3. **동시 변경 감지 (Seqlock Mismatch)**: 디렉터리 이름 변경 등으로 덴트리 포인터가 무효화되었을 때.
4. **마운트 포인트 교차 (Mount Crossing)**: 다른 파일 시스템 볼륨으로 진입할 때.

---

## 4. 음수 덴트리 (Negative Dentry)와 DoS 방어

해커나 악성 프로그램이 존재하지 않는 수백만 개의 무작위 파일 경로(`/var/www/xxxx.php`)를 조회하면, 일반적인 파일 시스템은 매번 디스크의 디렉터리 블록을 전부 스캔하여 파일이 없음을 확인해야 하므로 심각한 I/O DoS 공격이 성립합니다.

리눅스 VFS는 파일이 존재하지 않는다는 사실 자체를 캐싱하는 **음수 덴트리(`dentry->d_inode == NULL`)**를 dcache 해시 테이블에 저장합니다.
후속 조회가 들어오면 RCU-walk 상태에서 단 몇 나노초 만에 dcache에서 음수 덴트리를 발견하고 즉시 `ENOENT`를 반환하여 디스크와 CPU를 완벽하게 보호합니다.
