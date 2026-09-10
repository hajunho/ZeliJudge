# 문제 284: LSM-Tree 레벨드 컴팩션 & 톰스톤 가비지 컬렉션 엔진 (LSM-Tree Leveled Compaction & Tombstone GC Engine)

## 문제 설명

구글의 LevelDB와 메타(Meta)의 RocksDB, 그리고 분산 NewSQL인 TiKV, CockroachDB 등 현대의 고성능 스토리지 엔진은 **LSM-Tree (Log-Structured Merge-tree)** 아키텍처를 기반으로 설계되었습니다. LSM-Tree는 임의 쓰기(Random Write)를 순차 쓰기(Sequential Write)로 변환하여 극단적인 쓰기 성능을 제공하지만, 데이터가 여러 계층(Level)에 걸쳐 중복 저장되므로 공간 낭비와 읽기 지연(Read Amplification)을 유발합니다.

이를 해결하기 위해 스토리지 엔진은 백그라운드에서 주기적으로 여러 SSTable(Sorted String Table)을 병합 정렬하는 **레벨드 컴팩션(Leveled Compaction)**을 수행합니다:

1. **계층 구조와 파일 특성**:
   - **Level 0 ($L_0$)**: 메모리의 MemTable이 가득 차 디스크로 플러시된 불변(Immutable) SSTable들입니다. 파일 간 키 범위가 서로 겹칠 수(Overlap) 있습니다.
   - **Level $1 \sim L_{\max}$**: 각 레벨 내의 SSTable들은 **서로 키 범위가 겹치지 않도록 엄격히 분할(Non-overlapping & Partitioned)**되어 있습니다.
   - 각 레벨의 용량 한계:
     - $L_0$: 파일 개수 기준 (예: `l0_threshold = 4`개 파일 초과 시 컴팩션 트리거)
     - $L_i (i \ge 1)$: 바이트 크기 기준 $\text{target}(L_i) = \text{l1_target_bytes} \times \text{multiplier}^{i-1}$
2. **컴팩션 점수(Score) 계산 및 레벨 선정**:
   - $L_0$ 점수: $\text{file_count} / \text{l0_threshold}$
   - $L_i$ 점수 ($i \ge 1$): $\text{total_bytes}(L_i) / \text{target_bytes}(L_i)$
   - 점수가 $1.0$ 이상인 레벨 중 가장 점수가 높은 레벨이 컴팩션 소스 레벨($L_{\text{src}}$)로 선정됩니다. (동점 시 상위 레벨 우선)
3. **중복 범위 탐색 및 다분기 병합(Multi-way Merge)**:
   - $L_0$ 컴팩션: $L_0$의 모든 파일을 선택합니다.
   - $L_i$ 컴팩션 ($i \ge 1$): 해당 레벨의 첫 번째 SSTable을 선택합니다.
   - 선택된 파일들의 전체 키 범위 $[K_{\min}, K_{\max}]$와 겹치는 $L_{i+1}$의 모든 SSTable을 찾아 함께 읽어 들입니다.
   - 동일한 키가 여러 개 존재할 경우 가장 최신 시퀀스 번호(`seq`)를 가진 항목만 남깁니다 (Deduplication).
4. **톰스톤 가비지 컬렉션(Tombstone GC & Bottommost Purge)**:
   - LSM-Tree에서 삭제는 즉시 데이터를 지우는 것이 아니라 삭제 표시인 **톰스톤(Tombstone, `is_tombstone=True`)**을 기록하는 쓰기 작업입니다.
   - 만약 컴팩션 대상 키의 구버전 데이터가 더 깊은 레벨($L > L_{i+1}$)에 여전히 존재한다면, 톰스톤을 절대 삭제해서는 안 됩니다! 톰스톤을 삭제하면 하위 레벨의 지워졌어야 할 구버전 데이터가 되살아나는 **유령 데이터 부활(Phantom Resurrection)** 버그가 발생하기 때문입니다.
   - 더 깊은 레벨($L > L_{i+1}$)에 해당 키가 전혀 존재하지 않을 때에만 톰스톤을 디스크에서 완전히 영구 소멸(Purge)시킬 수 있습니다.
5. **쓰기 증폭(Write Amplification, WA) 측정**:
   - 컴팩션으로 인해 디스크에 다시 쓰여진 누적 바이트 수를 사용자가 실제로 기록한 원본 데이터 바이트 수로 나눈 비율을 추적합니다:
     $$WA = \frac{\text{Total Bytes Written to Disk}}{\text{User Bytes Written}}$$

당신은 RocksDB의 레벨드 컴팩션, 톰스톤 안전 제거 및 포인트 쿼리 엔진을 정확히 시뮬레이션하는 프로그램을 작성해야 합니다.

---

## 입력 형식 (JSON)

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다.

```json
{
  "config": {
    "max_levels": 4,
    "l0_threshold": 4,
    "l1_target_bytes": 500,
    "level_multiplier": 5,
    "target_file_size": 250
  },
  "operations": [
    {
      "step": 1,
      "op": "FLUSH_MEMTABLE",
      "entries": [
        {"key": "user:1", "val": "Alice", "seq": 1, "is_tombstone": false},
        {"key": "user:2", "val": "Bob", "seq": 2, "is_tombstone": false}
      ]
    },
    {
      "step": 2,
      "op": "COMPACT"
    },
    {
      "step": 3,
      "op": "GET",
      "key": "user:1"
    },
    {
      "step": 4,
      "op": "GET_SNAPSHOT"
    }
  ]
}
```

### 연산 종류
1. `FLUSH_MEMTABLE`: 주어진 키-값 엔트리들을 $L_0$의 새로운 불변 SSTable(`SST-xxxx`)로 플러시합니다. 각 엔트리의 바이트 크기는 `len(key) + len(val) + 8` (`val`이 null/None일 경우 0)로 계산합니다.
2. `COMPACT`: 점수 $\ge 1.0$인 레벨을 찾아 단일 컴팩션 단계를 수행합니다. 점수가 기준 미만이면 컴팩션을 수행하지 않습니다.
3. `GET`: 특정 키에 대한 포인트 조회를 수행합니다. $L_0$은 역순(최신 파일 우선)으로 조회하고, $L_1 \sim L_{\max}$는 파일의 키 범위 $[K_{\min}, K_{\max}]$를 확인하여 탐색합니다.
4. `GET_SNAPSHOT`: 각 레벨별 파일 수, 총 바이트, 용량, 점수 및 쓰기 증폭률, 톰스톤 제거 통계 스냅샷을 반환합니다.

---

## 출력 형식 (JSON)

표준 출력(stdout)으로 다음 스키마를 만족하는 단일 줄 JSON 객체를 출력합니다. 모든 부동소수점 수치는 소수점 둘째 자리까지 반올림(`round(x, 2)`)합니다.

```json
{
  "operations_log": [
    {
      "step": 1,
      "op": "FLUSH_MEMTABLE",
      "file_id": "SST-0001",
      "level": 0,
      "min_key": "user:1",
      "max_key": "user:2",
      "size_bytes": 48,
      "entry_count": 2
    },
    {
      "step": 2,
      "op": "COMPACT",
      "compaction_performed": true,
      "details": {
        "source_level": 0,
        "target_level": 1,
        "input_file_ids": ["SST-0001"],
        "output_file_ids": ["SST-0002"],
        "read_bytes": 48,
        "written_bytes": 48
      }
    },
    {
      "step": 3,
      "op": "GET",
      "key": "user:1",
      "found": true,
      "val": "Alice",
      "seq": 1,
      "level_found": 1,
      "file_id": "SST-0002",
      "is_tombstone": false,
      "sst_seeks": 1
    }
  ],
  "final_state": {
    "levels": [
      {
        "level": 0,
        "file_count": 0,
        "total_bytes": 0,
        "target_capacity": 4,
        "score": 0.0,
        "file_ranges": []
      }
    ],
    "metrics": {
      "user_bytes_written": 48,
      "total_bytes_written": 96,
      "total_bytes_read": 48,
      "write_amplification": 2.0,
      "compactions_executed": 1,
      "tombstones_purged": 0,
      "tombstones_preserved": 0
    }
  }
}
```

---

## 제약 조건

- 레벨 수: $3 \le \text{max\_levels} \le 6$
- $L_0$ 파일 임계치: $2 \le \text{l0\_threshold} \le 10$
- 연산 수: $1 \le M \le 50$
- 키 문자열 길이: $1 \le |\text{key}| \le 64$
- 엔트리 시퀀스 번호: 단조 증가하는 양의 정수
