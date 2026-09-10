# Bcachefs 차세대 CoW 파일 시스템의 이론적 구조와 리눅스 커널 아키텍처 (fs/bcachefs/)

## 1. CoW 파일 시스템의 20년 진화: ext4 -> Btrfs/ZFS -> Bcachefs

전통적인 저널링 파일 시스템(ext4, XFS)은 디스크 블록을 제자리에 덮어쓰는 제자리 쓰기(In-place Write) 방식과 메타데이터 저널링(JBD2)에 의존했습니다. 이는 성능이 우수하지만 데이터 체크섬, 즉각적인 무복사 스냅샷, 데이터 압축을 구현하기 어렵다는 한계가 있었습니다.

이를 극복하기 위해 등장한 2세대 CoW 파일 시스템이 바로 **Btrfs**와 **OpenZFS**입니다. 그러나 이들 역시 구조적 아키텍처의 한계를 안고 있었습니다:
- **Btrfs의 한계**: 트리 구조가 지나치게 복잡하고(Extent Tree, Checksum Tree, Inode Tree, Subvolume Tree 등 수많은 독립 트리가 얽힘), fsync 지연을 해결하기 위한 Tree-Log 코드가 비대해져 잠금 경합(Lock Contention)과 충돌 복구 시 버그가 빈번했습니다.
- **ZFS의 한계**: 거대한 메모리 캐시(ARC)와 독자적인 DMU(Data Management Unit) 레이어를 커널 외부 모델로 구현하여 리눅스 VFS 및 페이지 캐시와의 통합이 부자연스럽고 CDDL 라이선스 문제로 커널 메인라인에 포함되지 못했습니다.

이러한 배경 속에서 **Bcachefs**는 10년 이상의 연구 끝에 리눅스 커널 6.7에 정식 입성하였습니다.

---

## 2. Bcachefs의 핵심 설계 철학: 순수 B-트리 키-값 스토리지

Bcachefs는 파일 시스템 내부의 모든 엔티티를 단 하나의 통일된 **64비트 정렬 키(`struct bpos`)**와 **가변 길이 값(`struct bkey_val`)**으로 추상화합니다.

### 1. `bpos`의 3차원 좌표계
$$bpos = (	ext{inode: 64-bit}, 	ext{offset: 64-bit}, 	ext{snapshot\_id: 32-bit})$$
- `inode`: 파일의 고유 식별자.
- `offset`: 파일 내부의 논리적 오프셋 (섹터 또는 KB 단위).
- `snapshot_id`: 해당 데이터가 속한 스냅샷 네임스페이스.

이 세 값의 사전식 순서(Lexicographical Ordering)로 B-트리 키가 정렬되므로, 파일 데이터 탐색, 스냅샷 분기, 디렉토리 엔트리 탐색이 모두 동일한 고성능 B-트리 순회 알고리즘으로 단일화됩니다.

---

## 3. 버킷 할당자와 포인터 세대 관리 (Bucket Allocator & Generations)

Bcachefs의 블록 할당은 플래시 메모리(NVMe SSD)의 물리적 지우기 블록(Erase Block) 특성에 최적화된 **버킷(Bucket)** 단위를 기본으로 합니다:
- 각 버킷은 고유의 `generation`(세대 번호)을 가집니다.
- 데이터 포인터는 `(device, bucket_id, offset, generation)`으로 구성됩니다.
- 가비지 컬렉션(GC)이나 버킷 비우기가 발생하면 버킷의 `generation`이 1 증가합니다. 만약 오래된 댕글링 포인터가 해당 버킷을 참조하려 해도 세대 번호 불일치로 즉시 무효화되므로, Use-After-Free 류의 스토리지 데이터 손상을 하드웨어 수준에서 방지합니다.

---

## 4. 무복사 스냅샷 계층 트리 (Snapshot Tree Fallback)

Bcachefs의 스냅샷은 세계에서 가장 진보된 계층적 포인터 폴백 구조를 가집니다:
1. **스냅샷 생성 비용 0**: 스냅샷을 생성할 때 어떠한 B-트리 복제도 일어나지 않습니다. 단순히 스냅샷 트리에 `new_snapshot_id -> parent_snapshot_id` 노드 하나만 삽입됩니다.
2. **CoW 분기 쓰기 (Branching Write)**: 스냅샷 1에서 특정 블록을 수정하면, 키 `(inode, offset, 1)`에 새로운 익스텐트가 기록됩니다. 원본 스냅샷 0의 키 `(inode, offset, 0)`은 변경되지 않고 온전히 보존됩니다.
3. **상속 조회 (Ancestor Fallback)**: 스냅샷 1에서 읽기 요청 시, 먼저 `(inode, offset, 1)`을 찾고, 없으면 부모인 0을 찾아 원본 데이터를 읽습니다.

---

## 5. 저널 링버퍼와 충돌 복구 (Journal & Crash Consistency)

Bcachefs는 B-트리 노드의 변경 사항을 디스크 트리에 즉시 반영(Sync)하는 대신, 컴팩트한 **순환 저널 링버퍼(Journal Ring Buffer)**에 먼저 순차 추가(Append-Only)합니다:
- 디스크 쓰기 I/O를 순차 쓰기(Sequential Write)로 변환하여 초고속 fsync 지연 시간을 달성합니다.
- 전원 차단 등 비정상 크래시 발생 시, 마지막으로 유효하게 체크포인트된 `flushed_seq`부터 저널 헤드까지의 로그를 단 1회의 선형 스캔으로 리플레이(Replay)하여 완벽한 B-트리 정합성을 복구합니다.

Bcachefs는 견고성, 속도, 다기능성을 모두 갖춘 현대 리눅스 커널 파일 시스템 기술의 최고봉입니다.
