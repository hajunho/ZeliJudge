# 문제 250 이론: Linux Kernel 버디 할당자, 메모리 컴팩션 투 포인터 스캐너 및 Proactive Compaction 아키텍처

---

## 1. 버디 할당자(Buddy Allocator)와 외부 단편화(External Fragmentation)

리눅스 커널은 물리 메모리를 효율적으로 관리하기 위해 버디 시스템을 사용합니다. 메모리 존(ZONE_NORMAL) 내의 모든 페이지는 Order 0(4KB)부터 Order 10(4MB)까지의 프리 리스트(Free List)에 연결되어 있습니다.

```
+--------------------------------------------------------------------+
| ZONE_NORMAL Physical Memory Layout (Page Frame Numbers)            |
+--------------------------------------------------------------------+
| Order 0 | [4K][4K][4K]... (Free memory is fragmented into pieces)  |
| Order 9 | [NONE] ◄── Contiguous 2MB block cannot be found!         |
+--------------------------------------------------------------------+
```

서버가 오랫동안 실행되면 수많은 작은 파일 읽기, 네트워크 패킷 버퍼링, 프로세스 생성/소멸로 인해 메모리 곳곳에 구멍이 뚫립니다. 전체 여유 메모리가 수십 GB에 달하더라도, **연속된 512개의 4KB 페이지(Order-9, 2MB)**를 단 하나도 찾지 못하는 상태를 **외부 단편화**라고 부릅니다.

---

## 2. 메모리 컴팩션(Memory Compaction)의 내부 동작 원리

메모리 컴팩션(`mm/compaction.c`)은 파편화된 메모리를 정리하여 고차수(Higher Order) 연속 블록을 만들어내는 커널 서브시스템입니다.

```
     Zone Start                                            Zone End
     ┌────────────────────────────────────────────────────────┐
     │ [M1] [M2] [ ] [M3] [ ] [ ] [M4] [ ] [ ] [ ] [ ] [ ]   │
     └────────────────────────────────────────────────────────┘
       ▲                                                 ▲
       │ migrate_scanner (이동 대상 탐색)                 │ free_scanner (빈 슬롯 탐색)
       └───────────────►                 ◄───────────────┘
```

### 투 포인터 스캐너 (Two-Pointer Scanner)
1. **`migrate_scanner`**: 존의 시작 PFN에서 높은 번호로 전진하며, 다른 곳으로 이주시킬 수 있는 이동 가능 페이지(`MIGRATE_MOVABLE`, 익명 메모리 또는 페이지 캐시)를 찾습니다.
2. **`free_scanner`**: 존의 끝 PFN에서 낮은 번호로 후진하며, 이동 대상 페이지를 받아들일 빈 슬롯(Free Page)을 찾습니다.
3. **페이지 복사 및 페이지 테이블 수정**: 대상 페이지의 내용을 복사하고, 프로세스의 가상 주소 매핑(PTE)을 갱신한 뒤, 모든 CPU 코어에 IPI(Inter-Processor Interrupt)를 날려 TLB를 무효화(`flush_tlb_others_ipi`)합니다.
4. 두 포인터가 서로 교차(Meet)하면 컴팩션이 완료되고, 비워진 영역이 하나의 거대한 연속 Order-9 블록으로 합쳐집니다.

---

## 3. 프로덕션 장애 요인 분석 (Production Failure Modes)

### (1) `transparent_hugepage/defrag = always`로 인한 Direct Compaction 스톨
- 애플리케이션 스레드가 2MB 거대 페이지를 할당받으려 할 때 Order-9 프리 블록이 없으면, 백그라운드가 아닌 **할당 요청 스레드 자신이 직접** `compact_zone()`을 동기식으로 실행합니다.
- 수 기가바이트의 메모리를 스캔하고 페이지를 복사하는 동안 스핀락 경합과 TLB Flush IPI 대기로 인해 해당 스레드가 수 초간 정지(Freeze)됩니다.
- **해결책**:
  ```bash
  echo defer > /sys/kernel/mm/transparent_hugepage/defrag
  # 또는
  echo madvise > /sys/kernel/mm/transparent_hugepage/defrag
  ```
  `defer` 모드로 설정하면 즉시 4KB 페이지로 폴백 할당하여 응답 지연을 방지하고, 컴팩션은 백그라운드 데몬(`kcompactd`)에게 위임합니다.

### (2) 이동 불가(Unmovable) 슬랩 침범에 의한 Pageblock 고정(Pinning)
- 리눅스 커널은 2MB 단위의 페이지블록마다 `migratetype`을 부여합니다:
  - `MIGRATE_UNMOVABLE`: 커널 슬랩, 소켓 버퍼, dentry, inode 캐시 (이동 불가).
  - `MIGRATE_MOVABLE`: 유저 프로세스 익명 메모리, 페이지 캐시 (컴팩션 가능).
- **치명적 결함**: `min_free_kbytes`가 작으면 커널은 슬랩 할당 시 여유 공간이 부족하여 `MIGRATE_MOVABLE` 페이지블록을 빌려와 슬랩을 할당합니다.
- 2MB 페이지블록 안에 단 1개의 4KB 언무버블 슬랩 객체만 박혀 있어도, 컴팩션 스캐너는 그 블록 전체를 건너뛸 수밖에 없습니다. 모든 페이지블록이 오염되면 컴팩션 성공률이 0%로 추락합니다.
- **해결책**:
  ```bash
  sysctl -w vm.min_free_kbytes=1048576  # 1GB 이상 확보하여 폴백 차단
  ```

### (3) `vm.compaction_proactiveness`의 딜레마
- Linux 5.0+에 도입된 선제적 컴팩션 데몬(`kcompactd`)은 외부 단편화 점수(`extfrag_index`)를 기반으로 주기적으로 메모리를 정돈합니다.
- `vm.compaction_proactiveness` (기본값 20):
  - 0으로 설정하면 선제적 컴팩션이 꺼져 메모리 할당 시 Direct Compaction이 폭발합니다.
  - 90~100으로 설정하면 단편화가 미미한 상태에서도 CPU를 상시 100% 사용하여 정상 워크로드를 방해합니다.
  - **권장값**: `20 ~ 50` 사이로 튜닝하여 백그라운드 선제 정돈과 CPU 사용량의 균형을 유지해야 합니다.

---

## 4. 실무 커널 진단 런북 (Production Diagnostic Runbook)

1. **외부 단편화 현황 확인**:
   ```bash
   cat /proc/buddyinfo
   cat /proc/pagetypeinfo
   ```
2. **컴팩션 통계 및 지연 확인**:
   ```bash
   grep compact /proc/vmstat
   # compact_stall: Direct Compaction 진입 횟수 (0에 가까워야 함)
   # compact_fail: 컴팩션 실패 횟수
   # compact_success: 컴팩션 성공 횟수
   ```
3. **프로덕션 추천 커널 파라미터**:
   ```bash
   sysctl -w vm.compaction_proactiveness=30
   sysctl -w vm.min_free_kbytes=1048576
   echo defer > /sys/kernel/mm/transparent_hugepage/defrag
   ```
