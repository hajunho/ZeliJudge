# 401: 리눅스 커널 가상화 — KVM Dirty Ring Buffer 실시간 마이그레이션 및 비트맵 스캔 확장성 엔진

## 1. 개요 (Overview)

클라우드 데이터센터에서 가상 머신(VM)을 다운타임 없이 다른 물리 호스트로 이동시키는 **실시간 마이그레이션(Live Migration)** 은 워크로드 리밸런싱과 무중단 인프라 유지보수의 핵심 기술입니다. 실시간 마이그레이션 동안 하이퍼바이저는 vCPU들이 메모리에 쓰는 변경 사항(**더티 페이지: Dirty Pages**)을 지속적으로 추적하여 대상 호스트로 반복 전송(Pre-copy phase)해야 합니다.

전통적인 KVM 가상화 방식인 **전역 비트맵 로깅 (`ioctl(KVM_GET_DIRTY_LOG)`)** 은 다음과 같은 치명적인 확장성 문제를 안고 있었습니다:
1. **메모리 크기에 비례하는 $O(N)$ 오버헤드**: 1TB RAM을 가진 대규모 VM의 경우 1회 스캔마다 32MB 크기의 비트맵을 커널에서 유저 공간(QEMU)으로 통째로 복사(`copy_to_user`)하고, 페이지 테이블 엔트리를 다시 쓰기 보호(Write-Protect)해야 합니다.
2. **글로벌 락 및 Stop-The-World 스파이크**: 비트맵을 추출하고 초기화하는 동안 모든 vCPU가 전역 락에 걸려 멈추는 밀리초(ms) 단위의 레이턴시 스파이크가 발생하여 게스트 데이터베이스 성능을 파괴했습니다.

리눅스 커널 5.11에 도입된 **KVM Dirty Ring Buffer (`virt/kvm/dirty_ring.c`, `KVM_DIRTY_LOG_RING_BUFFER_SIZE`)** 는 거대한 전역 비트맵을 폐기하고, 각 vCPU마다 독립된 고정 크기 **원형 링 버퍼(Circular Ring Buffer)** 를 할당하는 획기적인 아키텍처입니다:
- vCPU가 게스트 프레임(GFN)에 쓰기를 수행하면, 하드웨어 EPT/PML이 해당 GFN을 vCPU의 전용 링 버퍼에 즉시 $O(1)$로 푸시합니다.
- 링 버퍼가 가득 차면(`tail - head == ring_size`), 해당 vCPU는 `KVM_EXIT_DIRTY_RING_FULL`로 유저 공간에 일시 탈출합니다.
- 유저 공간 마이그레이션 스레드는 링에서 더티 GFN 목록을 수집(Reap)하여 네트워크로 전송하고, `ioctl(KVM_RESET_DIRTY_RINGS)`를 통해 헤드 포인터를 전진시켜 vCPU를 재개합니다.
- 과도한 쓰기를 유발하는 특정 vCPU만 자연스럽게 쓰로틀링(Throttling)되며, 타 vCPU는 락 경합 없이 정상 속도로 실행됩니다.

본 문제에서는 KVM Dirty Ring의 생산자(vCPU)-소비자(유저 공간) 링 버퍼 메커니즘, 링 포화 시 탈출 및 쓰로틀링, 수집(Reap)과 재설정(Reset) 2단계 커밋 프로토콜, 다중 vCPU 격리 시뮬레이션 엔진을 설계 및 구현합니다.

---

## 2. KVM Dirty Ring 아키텍처 다이어그램

```
+========================================================================================+
|                        KVM Hypervisor vCPU Execution Pipeline                          |
|                                                                                        |
|  [vCPU 0: Guest Memory Write]                [vCPU 1: Guest Memory Write]              |
|  - EPT/PML traps dirty GFN                   - EPT/PML traps dirty GFN                 |
|               ||                                             ||                        |
|               VV (O(1) Push)                                 VV (O(1) Push)            |
|  +---------------------------+               +---------------------------+             |
|  | vCPU 0 Dirty Ring Buffer  |               | vCPU 1 Dirty Ring Buffer  |             |
|  | [tail++: GFN 100, 101...] |               | [tail++: GFN 200, 201...] |             |
|  | (Capacity: ring_size)     |               | (Capacity: ring_size)     |             |
|  +---------------------------+               +---------------------------+             |
+========================================================================================+
         ||                                            ||
         || (Ring Full -> KVM_EXIT_DIRTY_RING_FULL)     ||
         VV                                            VV
+========================================================================================+
|                     User-Space Hypervisor (QEMU / Cloud-Hypervisor)                    |
|                                                                                        |
|  1. REAP Operation: Read entries from head to tail, mark as RESET                     |
|  2. Transmit GFNs over Migration Network Stream                                        |
|  3. RESET Operation: ioctl(KVM_RESET_DIRTY_RINGS) -> Advance head to tail, clear full  |
|  4. Resume vCPU Execution!                                                             |
+========================================================================================+
```

---

## 3. 핵심 수리 및 알고리즘 규칙

### 3.1 링 버퍼 상태 및 포인터 관리
각 vCPU $V$는 크기 $R$의 원형 링을 가집니다:
- $	ext{count} = 	ext{tail} - 	ext{head}$
- 슬롯 인덱스: $	ext{idx} = 	ext{tail} \pmod R$
- 포화 조건: $	ext{count} \ge R$

### 3.2 vCPU 페이지 쓰기 (`VCPU_WRITE`)
1. 유효하지 않은 `vcpu_id`이면 `ERROR_INVALID_VCPU` 반환.
2. $	ext{is\_full} == 	ext{True}$이면:
   - `throttled_write_attempts` 증가.
   - `KVM_EXIT_DIRTY_RING_FULL` 반환.
3. 링 슬롯에 `{"gfn": gfn, "flags": "DIRTY"}`를 기록하고 `tail += 1`.
4. 만약 $	ext{count} \ge R$이 되면 $	ext{is\_full} = 	ext{True}$ 설정 후 `ring_full_exits` 카운터 증가 및 `KVM_EXIT_DIRTY_RING_FULL` 반환.
5. 포화되지 않은 경우 `PUSH_SUCCESS` 반환.

### 3.3 더티 페이지 수집 (`REAP`)
- `vcpu_id` 지정 시 해당 vCPU, 미지정 시 전체 vCPU 대상.
- `head`부터 `tail`까지 순회하며 `DIRTY` 플래그를 가진 모든 GFN을 수집하고 플래그를 `RESET`으로 변경합니다.
- 수집된 GFN 개수만큼 `reaped_dirty_pages` 카운터가 증가합니다.

### 3.4 링 재설정 (`RESET`)
- `head`부터 시작하여 `RESET` 상태인 슬롯들을 `EMPTY`로 초기화하고 `head += 1`을 전진시킵니다.
- `head == tail`이 되면 $	ext{count} = 0$, $	ext{is\_full} = 	ext{False}$가 되어 vCPU의 쓰기 차단이 해제됩니다.

---

## 4. 입출력 형식 (I/O Specification)

### 4.1 입력 형식 (Input Format)
```json
{
  "config": {
    "num_vcpus": 2,
    "ring_size": 2
  },
  "operations": [
    {"action": "VCPU_WRITE", "vcpu_id": 0, "gfn": 100},
    {"action": "VCPU_WRITE", "vcpu_id": 0, "gfn": 101},
    {"action": "VCPU_WRITE", "vcpu_id": 0, "gfn": 102},
    {"action": "REAP", "vcpu_id": 0},
    {"action": "RESET", "vcpu_id": 0}
  ]
}
```

### 4.2 출력 형식 (Output Format)
```json
{
  "total_vcpus": 2,
  "ring_size": 2,
  "stats": {
    "total_page_writes": 3,
    "ring_full_exits": 1,
    "reaped_dirty_pages": 2,
    "reset_operations": 1,
    "throttled_write_attempts": 1
  },
  "migrated_gfns_count": 2,
  "migrated_gfns_total": [100, 101],
  "rings_state": {
    "0": {
      "vcpu_id": 0,
      "head": 2,
      "tail": 2,
      "count": 0,
      "is_full": false,
      "entries": [
        {"gfn": null, "flags": "EMPTY"},
        {"gfn": null, "flags": "EMPTY"}
      ]
    }
  }
}
```
