# 문제 237: 데이터베이스 크래시 복구: 부분 쓰기(Torn Page Write) 참사와 InnoDB Doublewrite Buffer vs PostgreSQL Full Page Writes(FPW) vs NVMe 원자적 쓰기

## 1. 개요 및 배경 (Incident Scenario)

대규모 결제 트랜잭션을 처리하는 엔터프라이즈 데이터베이스 클러스터에서 데이터센터 순간 정전(Power Outage)이 발생한 후, 서버가 재부팅되었으나 데이터베이스 엔진이 크래시 복구(Crash Recovery / Redo Log Replay)에 실패하며 기동이 중단되는 전산 참사(`TORN_PAGE_WRITE_PERMANENT_CORRUPTION`)가 발생했습니다.

DBA는 WAL(Write-Ahead Logging / Redo Log)이 디스크에 `fsync`되어 있었으므로 당연히 ARIES 복구 알고리즘에 의해 트랜잭션이 완벽히 복구될 것이라 믿었습니다. 그러나 데이터베이스 로그에는 다음과 같은 에러가 찍혀 있었습니다:
`[ERROR] InnoDB: Page [page id: space=42, page_number=1024] log sequence number is in the future, checksum mismatch! Corrupted page detected, cannot apply redo log.`

원인은 물리 저장장치와 데이터베이스 페이지 크기의 불일치로 인한 **찢어진 페이지 쓰기(Torn Page Write / Partial Write)**였습니다:

```
[The Physical Reality of Torn Page Writes]

Database Page (InnoDB 16KB Page)
+-------------------+-------------------+-------------------+-------------------+
| Sector 1 (4KB)    | Sector 2 (4KB)    | Sector 3 (4KB)    | Sector 4 (4KB)    |
| [New Data Written]| [New Data Written]| [OLD DATA REMAINS]| [OLD DATA REMAINS]|
+-------------------+-------------------+-------------------+-------------------+
          |                   |                   ^
          +---------+---------+                   |
                    |                             |
      (Power Cut occurred right here!) ───────────┘
```

### 왜 표준 WAL/Redo Log만으로 복구할 수 없는가?
1. **물리적 원자성 한계 (Hardware Sector Size vs DB Page Size)**:
   - 일반적인 운영체제 및 저장장치(SATA/NVMe SSD)의 하드웨어 원자적 쓰기 단위(Atomic Write Unit)는 **4KB(4096바이트)** 섹터입니다.
   - 그러나 관계형 데이터베이스의 최소 I/O 블록 단위는 **MySQL InnoDB는 16KB**, **PostgreSQL은 8KB**입니다.
   - 16KB 페이지를 디스크에 플러시하던 중 8KB만 기록된 시점에 전원이 끊기면, 디스크 상의 페이지는 앞의 8KB는 새 데이터, 뒤의 8KB는 과거 데이터가 섞인 기형적인 **반쪽짜리 쓰레기 페이지(Torn Page)**가 됩니다.
2. **Physiological Redo Log의 전제 붕괴**:
   - 데이터베이스의 Redo 로그는 용량을 아끼기 위해 16KB 페이지 전체를 매번 기록하지 않고, "어느 슬롯에 어떤 바이트를 변경했다"는 델타(Delta) 변경분만을 기록합니다.
   - 델타 변경분을 재적용(Replay)하려면 **"베이스 페이지 자체가 과거의 어느 한 시점 상태로 온전하게 존재해야 한다"**는 물리적 무결성 전제가 필수적입니다.
   - 베이스 페이지 자체가 찢겨 손상되어 있으면 델타를 덮어씌우는 순간 B+Tree 인덱스 포인터가 깨져 테이블스페이스 전체가 파괴되므로, 커널은 복구를 강제 포기합니다.

### 데이터베이스 엔진들의 방어 아키텍처
1. **MySQL InnoDB Doublewrite Buffer (`innodb_doublewrite`)**:
   - 더티 페이지를 테이블스페이스(`.ibd`)에 랜덤 쓰기하기 전에, 디스크의 연속된 공간인 **Doublewrite Buffer**에 먼저 순차 쓰기하고 `fsync`합니다.
   - 그 후 `.ibd`에 기록하다 정전으로 찢어지더라도, 복구 시 Doublewrite Buffer에서 온전한 16KB 원본 페이지를 가져와 복원한 뒤 Redo Log를 안전하게 재생합니다(`OPTIMAL_DOUBLEWRITE_BUFFER_CRASH_RECOVERY`). 단, 페이지를 2번 기록하므로 쓰기 증폭 계수가 2.0배가 됩니다.
2. **PostgreSQL Full Page Writes (`full_page_writes = on`)**:
   - 체크포인트 이후 페이지가 메모리에서 처음 수정될 때, 델타가 아니라 **8KB 전체 페이지 이미지(Full Page Image, FPI)**를 WAL에 기록합니다.
   - 크래시 복구 시 찢어진 페이지가 발견되면 WAL에 보관된 온전한 8KB 이미지를 덮어써서 복원합니다(`OPTIMAL_POSTGRESQL_FULL_PAGE_WRITE_RECOVERY`).
3. **엔터프라이즈 NVMe 하드웨어 16KB 원자적 쓰기 (Atomic Write Units, AWUPF)**:
   - 최신 엔터프라이즈 NVMe SSD는 16KB/32KB 하드웨어 원자적 쓰기를 보장하므로, Torn Page가 물리적으로 발생하지 않아 Doublewrite Buffer를 안전하게 끄고 쓰기 증폭을 1.0배로 낮출 수 있습니다(`OPTIMAL_NVME_HARDWARE_ATOMIC_WRITE_RECOVERY`).

본 문제에서는 데이터베이스 엔진 설정, 전원 차단 시점 및 하드웨어 원자적 쓰기 단위에 따른 크래시 복구 성공 여부와 데이터 오염을 시뮬레이션합니다.

---

## 2. 입력 형식 (Input Specification)

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "config": {
    "engine": "INNODB",
    "doublewrite_enabled": true,
    "full_page_writes_enabled": true,
    "nvme_atomic_write_unit_kb": 4,
    "page_size_kb": 16
  },
  "workload": {
    "dirty_pages_count": 5000,
    "power_cut_during_flush": true,
    "power_cut_offset_kb": 8,
    "redo_log_delta_entries": 12000
  }
}
```

### 필드 설명
- `config`:
  - `engine` (str): 데이터베이스 엔진 (`"INNODB"`, `"POSTGRESQL"`, `"RAW_WAL_ONLY"`)
  - `doublewrite_enabled` (bool): InnoDB Doublewrite Buffer 활성화 여부
  - `full_page_writes_enabled` (bool): PostgreSQL Full Page Writes 활성화 여부
  - `nvme_atomic_write_unit_kb` (int): SSD 하드웨어 원자적 쓰기 보장 단위 (KB, 일반 드라이브: 4, 엔터프라이즈 NVMe AWUPF: 16)
  - `page_size_kb` (int): 데이터베이스 페이지 크기 (KB, InnoDB: 16, PostgreSQL: 8)
- `workload`:
  - `dirty_pages_count` (int): 플러시 대상 더티 페이지 수
  - `power_cut_during_flush` (bool): 페이지 디스크 기록 중 돌발 전원 차단 발생 여부
  - `power_cut_offset_kb` (int): 페이지 기록 중 전원이 차단된 오프셋 (KB)
  - `redo_log_delta_entries` (int): 대기 중인 Redo Log 델타 레코드 수

---

## 3. 출력 형식 (Output Specification)

표준 출력(stdout)으로 다음 JSON 구조를 반환해야 합니다:

```json
{
  "status": "SUCCESS",
  "verdict": "OPTIMAL_DOUBLEWRITE_BUFFER_CRASH_RECOVERY",
  "metrics": {
    "torn_pages_detected": 1,
    "pages_restored": 1,
    "crash_recovery_success": true,
    "data_corruption": false,
    "write_amplification_factor": 2.0,
    "hardware_atomic_guaranteed": false
  }
}
```

### 판정(Verdict) 및 상태(Status) 규칙
1. **하드웨어 원자적 쓰기 (`nvme_atomic_write_unit_kb >= page_size_kb`)**:
   - 하드웨어가 16KB 원자적 쓰기를 보장하므로 정전 시에도 Torn Page가 물리적으로 발생하지 않음
   - `status`: `"SUCCESS"`, `verdict`: `"OPTIMAL_NVME_HARDWARE_ATOMIC_WRITE_RECOVERY"`, `write_amplification_factor`: 1.0, `hardware_atomic_guaranteed`: `true`
2. **정전 발생 및 보호 메커니즘 부재**:
   - `power_cut_during_flush == true`이고 (`engine == "RAW_WAL_ONLY"` 또는 InnoDB에서 `doublewrite_enabled == false` 또는 PostgreSQL에서 `full_page_writes_enabled == false`):
     - Torn Page가 발생하여 델타 Redo 로그 재적용 실패, 영구 데이터 손상
     - `status`: `"FAILED"`, `verdict`: `"TORN_PAGE_WRITE_PERMANENT_CORRUPTION"`, `crash_recovery_success`: `false`, `data_corruption`: `true`
3. **정전 발생 및 보호 메커니즘 정상 작동**:
   - InnoDB + `doublewrite_enabled == true`:
     - Doublewrite Buffer에서 온전한 16KB 페이지를 복원 후 Redo 적용 완료
     - `status`: `"SUCCESS"`, `verdict`: `"OPTIMAL_DOUBLEWRITE_BUFFER_CRASH_RECOVERY"`, `write_amplification_factor`: 2.0
   - PostgreSQL + `full_page_writes_enabled == true`:
     - WAL의 Full Page Image에서 8KB 페이지 복원 후 Redo 적용 완료
     - `status`: `"SUCCESS"`, `verdict`: `"OPTIMAL_POSTGRESQL_FULL_PAGE_WRITE_RECOVERY"`, `write_amplification_factor`: 1.35
4. **정전 미발생 정상 플러시**:
   - 보호 메커니즘 비활성화 상태: `status`: `"WARNING"`, `verdict`: `"NO_CRASH_BUT_TORN_WRITE_VULNERABLE"`
   - 보호 메커니즘 활성화 상태: `status`: `"SUCCESS"`, `verdict`: `"CLEAN_FLUSH_PROTECTED_STATE"`

---

## 4. 예제 입출력

### 예제 1 (입력)
```json
{
  "config": {
    "engine": "INNODB",
    "doublewrite_enabled": true,
    "full_page_writes_enabled": true,
    "nvme_atomic_write_unit_kb": 4,
    "page_size_kb": 16
  },
  "workload": {
    "dirty_pages_count": 5000,
    "power_cut_during_flush": true,
    "power_cut_offset_kb": 8,
    "redo_log_delta_entries": 12000
  }
}
```

### 예제 1 (출력)
```json
{
  "status": "SUCCESS",
  "verdict": "OPTIMAL_DOUBLEWRITE_BUFFER_CRASH_RECOVERY",
  "metrics": {
    "torn_pages_detected": 1,
    "pages_restored": 1,
    "crash_recovery_success": true,
    "data_corruption": false,
    "write_amplification_factor": 2.0,
    "hardware_atomic_guaranteed": false
  }
}
```
