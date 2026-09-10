# 문제 302: 리눅스 커널 eBPF LRU 맵 락 경합 최소화 축출 엔진 (Linux Kernel eBPF Map LRU Eviction & Lockless Hash Table Engine)

## 문제 설명

리눅스 커널 eBPF 서브시스템(`kernel/bpf/bpf_lru_list.c` 및 `kernel/bpf/hashtab.c`)에서 제공하는 `BPF_MAP_TYPE_LRU_HASH`와 `BPF_MAP_TYPE_LRU_PERCPU_HASH`는 초당 수천만 패킷이 인입되는 XDP/TC 네트워킹 및 프로파일링 환경에서 정해진 용량(`max_entries`)을 초과할 때 가장 오래 참조되지 않은 엔트리를 자동으로 축출(Eviction)하는 고성능 해시 테이블입니다.

전통적인 단일 락 기반 LRU 캐시는 모든 코어의 `lookup` 및 `update` 시점마다 글로벌 뮤텍스나 스핀락을 획득해야 하므로, 수십 코어 이상의 대규모 서버에서 극심한 락 경합(Lock Contention)과 캐시 라인 바운싱(Cache Line Bouncing)이 발생하여 처리량이 급락합니다.

리눅스 커널은 이를 해결하기 위해 다음과 같은 고도의 락 경합 최소화 기법을 적용했습니다:
1. **락 없는 참조 비트(`ref` / `BPF_LRU_NODE_ACTIVE`) 갱신**:
   - `lookup` 시 글로벌 LRU 락을 잡지 않고, 해당 노드의 `ref` 플래그만 원자적으로 `True`로 설정합니다.
2. **이중 글로벌 리스트 (Active List & Inactive List)**:
   - 노드는 크게 **비활성 리스트(Inactive List)**와 **활성 리스트(Active List)**로 분리 관리됩니다.
3. **Per-CPU 대기 큐(Pending Lists)**:
   - 신규 삽입 노드는 즉시 글로벌 락을 획득하는 대신 CPU 로컬 대기 큐(`per_cpu_pending`)를 거쳐 일괄 반영(Flush)됩니다.
4. **지연된 축출 및 2차 기회 회전(Second-Chance Rotation)**:
   - 용량 초과 시 비활성 리스트의 꼬리(LRU 위치)부터 스캔합니다.
   - 스캔된 노드의 `ref`가 `True`이면 축출을 면제하고, `ref = False`로 리셋한 뒤 활성 리스트의 헤드로 승격(Promotion)시킵니다.
   - 활성 리스트의 크기가 비활성 리스트보다 커지면 균형 조절(Balancing)을 위해 활성 리스트의 꼬리 노드를 비활성 리스트의 헤드로 강등(Demotion)시킵니다.
   - 스캔된 노드의 `ref`가 `False`이면 해당 노드를 희생자(Victim)로 최종 선택하여 축출합니다.

본 문제에서는 리눅스 커널 eBPF LRU 맵(`bpf_lru_list.c`)의 핵심 축출 및 리스트 관리 메커니즘을 충실히 모델링하여, 다중 CPU 환경의 명령어 스트림을 처리하고 축출된 키 및 최종 맵 상태를 출력하는 **eBPF LRU 맵 엔진**을 구현해야 합니다.

---

## 입력 형식

표준 입력(stdin)으로 다음과 같은 단일 JSON 객체가 주어집니다:

```json
{
  "max_entries": 3,
  "num_cpus": 2,
  "commands": [
    {"op": "UPDATE", "cpu": 0, "key": "A", "value": 100},
    {"op": "UPDATE", "cpu": 0, "key": "B", "value": 200},
    {"op": "UPDATE", "cpu": 1, "key": "C", "value": 300},
    {"op": "LOOKUP", "cpu": 1, "key": "A"},
    {"op": "UPDATE", "cpu": 0, "key": "D", "value": 400}
  ]
}
```

- `max_entries`: 해시 맵의 최대 수용 엔트리 수 ($1 \le \text{max\_entries} \le 1000$).
- `num_cpus`: 시뮬레이션할 CPU 코어 수 ($1 \le \text{num\_cpus} \le 64$).
- `commands`: 순차적으로 실행할 명령어 목록:
  - `op`: 명령어 유형 (`"LOOKUP"`, `"UPDATE"`, `"DELETE"`).
  - `cpu`: 해당 명령어를 실행하는 CPU 코어 ID ($0 \le \text{cpu} < \text{num\_cpus}$).
  - `key`: 대상 키 문자열.
  - `value`: `"UPDATE"` 명령 시 저장할 값 (임의의 JSON 데이터).

---

## 출력 형식

표준 출력(stdout)으로 다음 구조를 갖는 단일 JSON 객체를 한 줄로 출력합니다:

```json
{
  "command_results": [
    {"op": "UPDATE", "key": "A", "result": {"status": "INSERTED", "key": "A", "evicted": null}},
    {"op": "UPDATE", "key": "B", "result": {"status": "INSERTED", "key": "B", "evicted": null}},
    {"op": "UPDATE", "key": "C", "result": {"status": "INSERTED", "key": "C", "evicted": null}},
    {"op": "LOOKUP", "key": "A", "result": {"found": true, "value": 100}},
    {"op": "UPDATE", "key": "D", "result": {"status": "INSERTED", "key": "D", "evicted": "B"}}
  ],
  "final_state": {
    "total_entries": 3,
    "active_list": ["A"],
    "inactive_list": ["D", "C"],
    "evicted_keys": ["B"],
    "table_keys": ["A", "C", "D"]
  }
}
```

- `command_results`: 각 명령어의 실행 결과 리스트.
  - `LOOKUP`: `{"found": bool, "value": any}`
  - `UPDATE`: `{"status": "INSERTED"|"UPDATED", "key": str, "evicted": str|null}`
  - `DELETE`: `{"deleted": bool}`
- `final_state`: 모든 명령어 완료 후의 맵 최종 상태 요약:
  - `total_entries`: 현재 저장된 엔트리 수.
  - `active_list`: 활성 리스트에 존재하는 키 목록 (헤드에서 꼬리 순).
  - `inactive_list`: 비활성 리스트에 존재하는 키 목록 (헤드에서 꼬리 순).
  - `evicted_keys`: 전체 실행 동안 축출된 희생자 키들의 누적 리스트 (축출된 순서대로).
  - `table_keys`: 현재 맵에 존재하는 모든 키의 사전순 정렬 리스트.

---

## 제약 사항

- $1 \le \text{max\_entries} \le 1000$
- $1 \le \text{num\_cpus} \le 64$
- $1 \le \text{commands} \le 5000$
- 메모리 제한: 512 MB
- 실행 시간 제한: 3.0 초
