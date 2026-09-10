# 문제 #279: 지워도 지워지지 않는 데이터와 디스크 낭비를 어떻게 해결할까요?!: 고성능 스토리지 엔진 LSM-Tree 레벨드 컴팩션(Leveled Compaction) 및 톰스톤(Tombstone) 가비지 컬렉션 엔진

## 1. 개요 (Story & Context)
초당 수십만 건의 쓰기 트랜잭션을 처리하는 최신 분산 데이터베이스(RocksDB, Apache Cassandra, ScyllaDB, TiKV)는 B-Tree의 무작위 디스크 I/O 병목을 회피하기 위해 **LSM-Tree(Log-Structured Merge-Tree)** 아키텍처를 핵심 스토리지 엔진으로 채택하고 있습니다.

LSM-Tree에서는 모든 `INSERT`, `UPDATE`, 심지어 `DELETE`조차도 디스크의 기존 데이터를 직접 덮어쓰거나 지우지 않고, 메모리(MemTable)와 디스크(SSTable)에 순차적으로 새로운 버전의 로그를 덧붙이는(Append-Only) 방식으로 처리됩니다:
- 삭제 요청이 들어오면 기존 데이터를 물리적으로 지우는 대신, **삭제 묘비(Tombstone Marker, `TOMBSTONE`)**라는 특별한 키-값 레코드를 새로 기록합니다.
- 이때 문제가 발생합니다! 오래된 버전의 레코드들이 디스크의 하위 계층(Level)에 그대로 방치된 채 쌓여가고, 삭제 묘비들 또한 디스크 공간을 차지하면서 디스크 용량이 무한정 팽창(Space Amplification)하고 읽기 증폭(Read Amplification)이 심화됩니다.

이 문제를 해결하고 스토리지 공간을 정돈하는 엔진의 핵심 서브시스템이 바로 **레벨드 컴팩션(Leveled Compaction)**과 **톰스톤 가비지 컬렉션(Tombstone GC)**입니다:
1. **계층 구조(Levels $L_0, L_1, L_2, \dots, L_{\max}$)**:
   - $L_0$: MemTable이 디스크로 플러시된 파일들로, 키 범위가 서로 겹칠 수 있습니다(Overlapping Key Ranges). $L_0$의 파일 개수가 `l0_compaction_trigger`에 도달하면 컴팩션이 발동됩니다.
   - $L_1 \sim L_k$: 각 계층 내부의 SSTable 파일들은 서로 **키 범위가 엄격히 겹치지 않도록(Non-Overlapping)** 정렬 유지됩니다.
2. **컴팩션 우선순위 점수(Compaction Score)**:
   - $L_0$ 점수: $\text{count}(L_0) / \text{l0\_compaction\_trigger}$
   - $L_i (i \ge 1)$ 점수: $\text{current\_size}(L_i) / \text{target\_size}(L_i)$
   - 점수가 1.0 이상인 계층 중 가장 점수가 높은 계층을 선정하여 하위 계층($L_i \to L_{i+1}$)으로 컴팩션을 병합 수행합니다.
3. **선택적 겹침 병합(Overlapping Merge-Sort)**:
   - $L_i$의 대상 파일 키 범위 $[min\_key, max\_key]$와 교차하는 $L_{i+1}$의 파일들만을 정확히 선별하여 함께 다중 병합 정렬(Multi-way Merge)합니다. 겹치지 않는 $L_{i+1}$의 파일들은 디스크 I/O 없이 온전히 보존됩니다!
4. **시퀀스 번호 기반 중복 제거(Sequence Deduplication)**:
   - 동일한 키를 가진 여러 버전 중 가장 최신 시퀀스 번호(`seq`)를 가진 레코드 하나만 남기고 이전 버전들을 모두 영구 폐기합니다.
5. **톰스톤 안전 폐기 조건(Tombstone GC Safety)**:
   - 삭제 묘비(`TOMBSTONE`)는 아무 때나 지울 수 없습니다!
   - 만약 하위 레벨($L_{i+2} \dots L_{\max}$)에 동일한 키의 옛날 버전이 아직 살아있다면, 묘비를 지워버리는 순간 옛날 데이터가 되살아나는 유령 데이터(Zombie Resurrection) 버그가 터집니다!
   - 톰스톤은 **하위 모든 레벨에 해당 키가 전혀 존재하지 않거나, 병합 대상 레벨이 최하위 레벨($L_{i+1} = L_{\max}$)일 때만** 안전하게 디스크에서 완전히 소멸(Drop)시킬 수 있습니다!

여러분은 RocksDB 스토리지 엔진의 코어 엔지니어로서, 레벨드 컴팩션과 톰스톤 가비지 컬렉션을 완벽하게 구현해야 합니다!

---

## 2. 입출력 규격 및 처리 규칙

### 2.1 계층별 컴팩션 점수 산출
- $L_0$: $\text{score}(L_0) = \frac{\text{len}(L_0)}{\text{l0\_compaction\_trigger}}$
- $L_i (i \ge 1)$: $\text{score}(L_i) = \frac{\sum \text{entries in } L_i}{\text{level\_targets}[L_i]}$
- 점수가 $\ge 1.0$인 계층 중 가장 높은 점수의 계층을 선택하여 컴팩션을 진행합니다. $\ge 1.0$인 계층이 없으면 `"NO_COMPACTION"`.

### 2.2 병합 및 톰스톤 폐기 규칙
- 대상 레벨 $L_i$의 파일과 키 범위가 겹치는 $L_{i+1}$의 파일들을 병합 정렬합니다.
- 동일 키에 대해 가장 높은 `seq`를 가진 엔트리만 유지합니다.
- 최신 엔트리가 `TOMBSTONE`인 경우:
  - $L_{i+1}$이 최하위 레벨이거나, $L_{i+2} \dots L_{\max}$의 어떤 파일에도 해당 키가 존재하지 않으면 $\to$ 톰스톤을 폐기(`tombstones_dropped += 1`).
  - 하위 레벨에 동일 키가 존재하면 $\to$ 톰스톤을 유지하여 출력 SSTable에 기록(`tombstones_retained += 1`).
- 병합된 결과 엔트리들을 `target_file_size` 단위로 분할하여 새로운 SSTable 파일(`L{i+1}_merged_1`, `L{i+1}_merged_2`...)을 생성합니다.
