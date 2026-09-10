# 리눅스 커널 Device Mapper dm-thin 가상 프로비저닝, CoW 스냅샷 및 스페이스 맵 할당자 엔진

## 1. 개요 및 배경

엔터프라이즈 클라우드 인프라(Kubernetes, OpenStack, Docker `devicemapper`, Proxmox VE)에서 수백 대의 가상머신(VM)이나 컨테이너를 구동할 때, 각 인스턴스마다 수십~수백 GB의 블록 스토리지를 사전에 물리 디스크에 전부 고정 할당(Thick Provisioning)하는 것은 치명적인 스토리지 낭비(실제 사용률 10~20%, 낭비율 80% 이상)를 초래합니다.

이를 해결하기 위해 리눅스 커널 3.2에 도입된 **Device Mapper Thin Provisioning (`dm-thin`)**은 거대한 단일 물리 데이터 풀(Data Pool)을 공유하면서, 실제 데이터가 기록되는 시점에만 고정 크기의 청크(Chunk, 예: 64KB~1GB)를 동적으로 할당하는 **가상 프로비저닝(Thin Provisioning)** 아키텍처를 제공합니다.

`dm-thin`의 핵심 기술 혁신은 다음과 같습니다:
1. **스페이스 맵(Space Map)과 참조 카운팅**: 물리 데이터 청크마다 참조 카운트(`ref_count`)를 추적하여, 0(미할당), 1(단독 소유), 2 이상(스냅샷 간 CoW 공유) 상태를 관리합니다.
2. **트랜잭셔널 메타데이터 B-Tree**: 각 가상 볼륨(Thin Device)의 가상 청크 인덱스($v\_chunk$)를 물리 청크 인덱스($p\_chunk$)로 변환하는 2단계 매핑 트리를 영속적으로 유지합니다.
3. **즉각적 스냅샷(Instant Snapshot)과 CoW 분기(CoW Break)**: 메타데이터 트리 복사만으로 $O(1)$ 시간에 스냅샷을 생성하며, 공유된 청크에 새로운 쓰기가 발생할 때만 새 물리 청크를 할당하여 복사(Copy-on-Write)합니다.
4. **디스카드(TRIM / Discard) 공간 회수**: 게스트 파일시스템에서 파일 삭제 시 발생하는 `REQ_OP_DISCARD` 명령을 수신하여 가상 매핑을 해제하고, 참조 카운트가 0이 된 물리 청크를 즉시 프리 풀(Free Pool)로 반환합니다.
5. **공간 고갈(Out-of-Data-Space, OODS) 방어**: 물리 풀이 100% 소진되었을 때 즉시 I/O 에러(`-ENOSPC`)를 반환하거나 I/O를 큐에 보류(`queue_if_no_space`)하며, 동적 풀 확장(`EXTEND_POOL`) 시 지연된 I/O를 순차적으로 플러시합니다.

당신은 엔터프라이즈 클라우드 스토리지 시스템의 안정성을 검증하기 위해, `dm-thin`의 물리 청크 스페이스 맵, 가상-물리 매핑, CoW 스냅샷 및 공간 고갈 처리 상태 머신을 정밀하게 모사하는 **리눅스 dm-thin 가상 스토리지 엔진**을 구현해야 합니다.

---

## 2. 시스템 아키텍처 및 메타데이터 계층

```
                      [ 가상 볼륨 Thin Devices (I/O 요청) ]
                      thin1 (dev_id: 1)         snap1 (dev_id: 2)
                             │                         │
                             ▼                         ▼
                     [ Virtual Chunk Index (v_chunk: 0, 1, 2...) ]
                                     │
                 ┌───────────────────┴───────────────────┐
                 │    Persistent Data Transaction B-Tree │
                 │      v_chunk -> p_chunk Mapping       │
                 └───────────────────┬───────────────────┘
                                     │
                     [ Space Map (dm_space_map_data) ]
                     p_chunk: [0]  [1]  [2]  [3]  [4] ...
                     ref_cnt:  2    1    0    1    0  ...
                               │    │    │
              ┌────────────────┘    │    └────────────┐
              ▼                     ▼                 ▼
         [공유 청크]            [단독 소유]        [프리 청크 풀]
     (thin1, snap1 공유)       (thin1 단독)       (신규 할당 가능)
                                     │
                                     ▼
                   [ 물리 데이터 디바이스 (Data Device) ]
                   Chunk 0 (64KB), Chunk 1 (64KB), Chunk 2 (64KB)...
```

---

## 3. 핵심 규칙 및 알고리즘 명세

### 3.1 물리 풀 및 가상 디바이스 상태
- **물리 데이터 풀**: 총 `total_data_chunks`개의 물리 청크($p\_chunk \in [0, \text{total\_data\_chunks}-1]$)를 갖습니다.
- **Space Map**: 각 물리 청크의 참조 카운트를 정수 배열 `space_map`으로 추적합니다.
  - `space_map[p] == 0`: 비어있는 청크 (`free_chunks` 큐에 존재).
  - `space_map[p] == 1`: 특정 가상 디바이스가 단독 소유 중인 청크.
  - `space_map[p] > 1`: 원본 볼륨과 하나 이상의 스냅샷이 CoW로 공유 중인 청크.
- **가상 디바이스(Thin Device)**: 각 디바이스는 가상 청크 $v\_chunk$에서 물리 청크 $p\_chunk$로의 매핑 딕셔너리(`mappings`)를 유지합니다.

### 3.2 입출력(I/O) 연산 처리 파이프라인

1. **읽기 (`READ`)**:
   - `v_chunk`가 `mappings`에 존재하는 경우:
     - 적중(`result: "HIT"`), 해당 `p_chunk` 반환, `read_hits` 1 증가.
   - `v_chunk`가 `mappings`에 존재하지 않는 경우 (희소 블록):
     - 가상 프로비저닝의 특성에 따라 물리 디스크 읽기 없이 0으로 채워진 블록을 반환(`result: "SPARSE_ZERO"`, `p_chunk: null`), `read_sparse_zeroes` 1 증가.

2. **쓰기 (`WRITE`)**:
   - **기존에 매핑된 경우 (`v_chunk in mappings`)**:
     - 대상 $p = \text{mappings}[v\_chunk]$의 $\text{space\_map}[p] == 1$인 경우:
       - 단독 소유 청크이므로 물리 디스크의 해당 위치에 제자리 덮어쓰기(`action: "OVERWRITE_IN_PLACE"`), `write_in_place` 1 증가.
     - $\text{space\_map}[p] > 1$인 경우 (**Copy-on-Write / CoW Break**):
       - 스냅샷과 공유 중인 블록이므로 분기해야 합니다.
       - 프리 청크가 없는 경우:
         - `error_if_no_space == true`: 즉시 에러(`action: "ERROR_ENOSPC"`, `reason: "COW_BREAK_NO_SPACE"`), `write_enospc_errors` 1 증가.
         - `error_if_no_space == false`: I/O를 대기열에 저장(`action: "DEFERRED_QUEUE"`, `reason: "COW_BREAK_NO_SPACE"`), `write_deferred` 1 증가.
       - 프리 청크가 있는 경우:
         - 가장 낮은 번호의 프리 청크 $p_{\text{new}}$를 pop.
         - $\text{space\_map}[p_{\text{new}}] = 1$, $\text{space\_map}[p] -= 1$.
         - `mappings[v_chunk] = p_new`, `write_cow_breaks` 1 증가 (`action: "COW_BREAK_ALLOC"`).
   - **기존에 매핑되지 않은 경우 (`v_chunk not in mappings`)**:
     - 신규 청크 할당(New Allocation)이 필요합니다.
     - 프리 청크가 없는 경우:
       - `error_if_no_space == true`: 즉시 에러(`action: "ERROR_ENOSPC"`, `reason: "POOL_EXHAUSTED"`), `write_enospc_errors` 1 증가.
       - `error_if_no_space == false`: I/O를 대기열에 저장(`action: "DEFERRED_QUEUE"`, `reason: "POOL_EXHAUSTED"`), `write_deferred` 1 증가.
     - 프리 청크가 있는 경우:
       - 가장 낮은 번호의 프리 청크 $p_{\text{new}}$를 pop.
       - $\text{space\_map}[p_{\text{new}}] = 1$.
       - `mappings[v_chunk] = p_new`, `provisioned_chunks` 1 증가, `write_new_alloc` 1 증가 (`action: "NEW_ALLOCATION"`).

3. **스냅샷 생성 (`SNAPSHOT`)**:
   - `origin_id` 볼륨의 현재 `mappings` 전체를 복사하여 `snap_id` 디바이스를 생성합니다.
   - 복사된 모든 물리 청크 $p$에 대해 $\text{space\_map}[p] += 1$을 수행합니다.
   - `snapshots_created` 1 증가 (`event: "SNAPSHOT"`).

4. **디스카드/트림 (`DISCARD`)**:
   - `v_chunk`가 `mappings`에 존재하면 매핑에서 제거하고 `provisioned_chunks`를 1 감소시킵니다.
   - 해당 물리 청크 $p$의 $\text{space\_map}[p] -= 1$을 수행합니다.
   - 만약 $\text{space\_map}[p] == 0$이 되면, 물리 풀로 완전히 환원되어 `free_chunks`에 추가되고 오름차순 정렬됩니다 (`freed_to_pool: true`).
   - `discards_processed` 1 증가.

5. **풀 확장 (`EXTEND_POOL`)**:
   - 물리 풀에 `additional_chunks`개의 신규 청크를 추가합니다. `total_data_chunks`가 증가하고, 신규 청크 번호들이 `free_chunks`에 등록됩니다.
   - `pool_extensions` 1 증가.
   - 만약 보류 중인 `deferred_writes` 큐에 I/O가 있다면, FIFO 순서대로 즉시 깨어나 가용한 신규 청크를 할당받아 쓰기를 완료(Flushed)합니다.

6. **워터마크 모니터링 (Low-Watermark Warning)**:
   - 풀 사용률 $\frac{\text{used}}{\text{total}} \times 100 \ge \text{low\_watermark\_pct}$가 되는 순간 단 한 번 경보 이벤트(`WARNING_LOW_WATERMARK`)가 기록되고 `low_watermark_events`가 1 증가합니다.
   - 디스카드로 인해 사용률이 임계치 미만으로 떨어지면 워터마크 트리거 상태가 리셋되어 향후 다시 초과 시 재경보할 수 있습니다.

---

## 4. 입출력 형식 및 제약 조건

### 입력 형식 (JSON)
```json
{
  "pool_config": {
    "chunk_size_kb": 64,
    "total_data_chunks": 10,
    "low_watermark_pct": 70,
    "error_if_no_space": true
  },
  "devices": {
    "thin1": { "max_v_chunks": 100 }
  },
  "events": [
    { "type": "WRITE", "dev_id": "thin1", "v_chunk": 0 },
    { "type": "SNAPSHOT", "origin_id": "thin1", "snap_id": "snap_thin1" },
    { "type": "WRITE", "dev_id": "thin1", "v_chunk": 0 }
  ]
}
```

### 출력 형식 (JSON)
```json
{
  "pool_status": {
    "total_physical_chunks": 10,
    "used_physical_chunks": 2,
    "free_physical_chunks": 8,
    "utilization_pct": 20.0,
    "shared_chunks_count": 0,
    "exclusive_chunks_count": 2,
    "overprovisioning_ratio": 0.2
  },
  "stats": {
    "read_hits": 0,
    "read_sparse_zeroes": 0,
    "write_in_place": 0,
    "write_new_alloc": 1,
    "write_cow_breaks": 1,
    "write_enospc_errors": 0,
    "write_deferred": 0,
    "discards_processed": 0,
    "snapshots_created": 1,
    "pool_extensions": 0,
    "low_watermark_events": 0
  },
  "deferred_queue_remaining": 0,
  "devices": {
    "thin1": {
      "provisioned_chunks": 1,
      "mapped_chunks_count": 1,
      "mappings": { "0": 1 }
    },
    "snap_thin1": {
      "provisioned_chunks": 1,
      "mapped_chunks_count": 1,
      "mappings": { "0": 0 }
    }
  },
  "event_logs": [ ... ]
}
```
