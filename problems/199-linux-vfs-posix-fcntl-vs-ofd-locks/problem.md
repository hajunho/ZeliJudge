# Problem 199: 리눅스 VFS 파일 잠금: POSIX fcntl의 묵시적 잠금 해제(Silent Lock Drop) 결함과 Open File Description (OFD) 락 동시성

## 문제 설명

임베디드 트랜잭션 데이터베이스(SQLite WAL 모드)와 고성능 멀티스레드 스토리지 엔진을 운영하는 코어 인프라 엔지니어링 팀은 멀티스레드 환경에서 원인 불명의 데이터베이스 파일 오염(`DATABASE_CORRUPTION`)과 트랜잭션 깨짐 사태를 마주했습니다.

분석 결과, 유닉스 표준으로 수십 년간 널리 사용되어 온 **POSIX 레코드 잠금(`fcntl` `F_SETLK`)의 치명적인 API 설계 결함**이 원인이었습니다.

### 1. POSIX fcntl 잠금의 치명적 설계 결함: 묵시적 잠금 해제(Silent Lock Drop)
POSIX 표준에서 `fcntl(fd, F_SETLK, ...)`으로 설정된 레코드 잠금(Byte-Range Lock)은 파일 디스크립터(`fd`)가 아니라 **프로세스 ID(`PID`)와 아이노드(`inode`)의 쌍**에 귀속됩니다:
- 스레드 A가 `fd_1 = open("db.sqlite")`을 열고 0~4096 바이트 영역에 배타적 쓰기 잠금(`F_WRLCK`)을 획득했습니다.
- 동일한 프로세스의 스레드 B가 헬퍼 라이브러리나 플러그인을 통해 우연히 `fd_2 = open("db.sqlite")`을 열어 헤더 정보를 읽은 뒤 `close(fd_2)`를 호출했습니다.
- **리눅스 커널의 동작**: POSIX 규격에 따라 커널은 프로세스가 해당 아이노드에 대해 열어둔 **어떤 fd라도 닫히면(`close`), 해당 프로세스가 소유한 그 파일의 모든 POSIX 잠금을 아무런 경고 없이 조용히 일괄 해제(Silent Lock Drop)**합니다!
- 스레드 A는 자신이 여전히 배타 잠금을 쥐고 있다고 믿고 작업을 이어가지만, 커널에서는 락이 이미 증발해 버렸습니다.
- 그 사이 다른 프로세스나 스레드가 해당 영역의 잠금을 낚아채고 동시 쓰기를 감행하여 **데이터베이스 파일이 회복 불가능하게 파괴**되는 대참사(`DATABASE_CORRUPTION_POSIX_SILENT_LOCK_DROP`)가 발생합니다.

### 2. 고전 `flock(2)`의 한계: 전체 파일 직렬화 병목
`flock(fd, LOCK_EX)`은 오픈 파일 설명자(Open File Description)에 바인딩되어 `close(fd_2)`에 의해 풀리지 않는 안전성을 가지지만, **바이트 범위 잠금(Record Lock)이 불가능하고 파일 전체만 잠글 수 있습니다**.
- 데이터베이스의 서로 다른 페이지(예: 0~4KB, 4~8KB)에 대해 여러 스레드가 동시에 안전하게 쓰기 작업을 수행하지 못하고 무조건 직렬화(`FLOCK_COARSE_GRAINED_SERIALIZATION_BOTTLENECK`)되어 멀티코어 처리량이 바닥으로 추락합니다.

### 3. 리눅스 3.15의 구원: Open File Description (OFD) 락
리눅스 3.15 커널에서 도입된 **Open File Description (OFD) 잠금(`F_OFD_SETLK`)**은 POSIX 락과 flock의 장점만을 결합했습니다:
- 잠금의 소유권이 `PID`가 아닌 **오픈 파일 설명자(`struct file`)**에 귀속됩니다.
- 프로세스 내 다른 fd를 몇 번을 열고 닫아도 **기존 OFD 잠금은 절대 영향받지 않고 100% 보존**됩니다.
- 파일의 특정 바이트 범위(Byte-Range)만을 정밀하게 잠글 수 있어, SQLite WAL 모드처럼 여러 스레드가 서로 다른 데이터 프레임에 대해 **완전한 병렬 동시 쓰기(`OPTIMAL_OFD_LOCK_RECORD_CONCURRENCY`)**를 안전하게 수행할 수 있습니다.

당신은 리눅스 VFS 잠금 서브시스템을 시뮬레이션하여 POSIX 락의 묵시적 잠금 해제 참사를 재현하고, OFD 락을 통한 안전한 고성능 동시성을 검증해야 합니다.

---

## 핵심 잠금 모드 및 동작 규칙

### 1. 잠금 모드 (`lock_mode`)
- `POSIX_FCNTL_LOCKS`:
  - 락 소유권: `(PID, inode, start, length)`.
  - 동일 프로세스 내 임의의 fd가 `close`되면, 해당 inode에 걸려 있던 그 프로세스의 모든 잠금이 즉시 소멸합니다 (`silent_lock_drops` 카운트 증가).
  - 락이 증발한 상태에서 수행된 쓰기는 보호받지 못하여 `database_corruptions`가 발생하고 `status: FAILED`로 종료됩니다.
- `BSD_FLOCK`:
  - 락 소유권: `(inode)`. 파일 전체를 통째로 잠급니다 (`start=0, length=ALL`).
  - 서로 다른 바이트 범위를 요구하더라도 파일 전체가 충돌하므로 잠금이 거부(`locks_denied`)되며 직렬화 병목을 유발합니다.
- `LINUX_OFD_LOCKS`:
  - 락 소유권: `(file_obj_id, inode, start, length)`.
  - 오픈 파일 설명자 단위로 바이트 범위 잠금이 독립 격리됩니다.
  - 무관한 fd 닫힘에 영향을 받지 않으며, 비충돌 바이트 범위에 대해 완전한 무충돌 동시 쓰기를 보장합니다 (`status: SUCCESS`).

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "system": {
    "lock_mode": "LINUX_OFD_LOCKS"
  },
  "workload": [
    {"op": "OPEN", "wallclock_ms": 0.0, "pid": 100, "thread_id": "tx_writer_1", "path": "/var/lib/db.sqlite"},
    {"op": "OPEN", "wallclock_ms": 5.0, "pid": 100, "thread_id": "temp_reader", "path": "/var/lib/db.sqlite"},
    {"op": "LOCK", "wallclock_ms": 10.0, "pid": 100, "thread_id": "tx_writer_1", "fd": 3, "start": 0, "length": 4096},
    {"op": "CLOSE", "wallclock_ms": 15.0, "pid": 100, "thread_id": "temp_reader", "fd": 4},
    {"op": "WRITE", "wallclock_ms": 20.0, "pid": 100, "thread_id": "tx_writer_1", "fd": 3, "start": 0, "length": 4096, "payload": "SAFE_DATA"}
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 다음 형식의 JSON 객체를 들여쓰기 2칸(`indent=2`)으로 출력합니다:

```json
{
  "status": "SUCCESS",
  "summary": {
    "lock_mode": "LINUX_OFD_LOCKS",
    "total_lock_requests": 1,
    "locks_granted": 1,
    "locks_denied": 0,
    "silent_lock_drops": 0,
    "database_corruptions": 0
  },
  "metrics": {
    "total_lock_requests": 1,
    "locks_granted": 1,
    "locks_denied": 0,
    "silent_lock_drops": 0,
    "concurrent_write_conflicts": 0,
    "database_corruptions": 0,
    "active_locks_remaining": 1,
    "verdict": "OPTIMAL_OFD_LOCK_RECORD_CONCURRENCY"
  },
  "sample_events": [
    {
      "wallclock_ms": 10.0,
      "op": "LOCK",
      "status": "GRANTED",
      "fd": 3,
      "range": [0, 4096]
    }
  ]
}
```
