# 고성능 스토리지 엔진: LSM-Tree 레벨드 컴팩션(Leveled Compaction)과 톰스톤 가비지 컬렉션 이론

## 1. B-Tree vs LSM-Tree 아키텍처 비교
전통적인 관계형 데이터베이스(MySQL InnoDB)의 B-Tree는 단일 페이지 단위 In-Place Update를 수행하므로, 쓰기 작업 시 디스크 헤더가 여러 블록을 오가는 Random I/O 병목이 발생합니다.

반면 LSM-Tree(RocksDB, Cassandra)는:
- **메모리(MemTable)**에 데이터를 Skiplist 형태로 모아두었다가
- 일정 크기(예: 64MB)에 도달하면 디스크에 연속된 불변(Immutable) 파일인 **SSTable(Sorted String Table)**로 순차 플러시(Sequential Write)합니다.
- 그 결과 초당 수십만~수백만 건의 고속 쓰기가 가능합니다.

---

## 2. 증폭(Amplification) 3대 트레이드오프
LSM-Tree 엔진 설계의 핵심은 3대 증폭 지표의 균형입니다:
1. **쓰기 증폭(Write Amplification, WA)**: 유저가 1바이트 쓸 때 디스크에 실제로 기록되는 총 바이트 수.
2. **읽기 증폭(Read Amplification, RA)**: 유저가 1개 키를 읽을 때 디스크에서 조회해야 하는 SSTable 및 블록 수.
3. **공간 증폭(Space Amplification, SA)**: 유효 데이터 크기 대비 디스크에 점유된 물리 용량 비율. 오래된 버전과 삭제 묘비가 쌓일수록 SA가 급증합니다.

레벨드 컴팩션(Leveled Compaction)은 $L_1$부터 각 계층의 키 범위를 겹치지 않게 유지하여 읽기 증폭과 공간 증폭을 획기적으로 낮추는 방식입니다.

---

## 3. 톰스톤(Tombstone)과 유령 데이터 부활(Zombie Resurrection)
LSM-Tree에서 데이터를 삭제할 때 가장 치명적인 위험은 톰스톤의 성급한 제거입니다:
- 만약 $L_1$에서 `key="user:42"`를 삭제하여 톰스톤을 기록했습니다.
- 하위 $L_3$에는 3일 전에 쓴 옛날 `user:42` 데이터가 아직 남아 있습니다.
- 만약 $L_1 \to L_2$ 컴팩션 도중 "이 톰스톤은 이제 지워도 되겠지" 하고 톰스톤을 디스크에서 없애버린다면:
- 나중에 클라이언트가 `GET user:42`를 요청했을 때, $L_1, L_2$를 통과한 후 $L_3$에 도달하여 **3일 전 삭제되었던 데이터가 마법처럼 다시 살아나 반환되는 치명적인 데이터 오염(Data Corruption)**이 발생합니다!
- 따라서 톰스톤은 반드시 하위 모든 계층에 해당 키가 단 하나도 남아있지 않음이 보장될 때만 안전하게 소멸시킬 수 있습니다.
