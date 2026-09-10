# 리눅스 커널 Fanotify 파일시스템 이벤트 알림, 동기 접근 권한(Permission) 제어 및 큐 병합 엔진

## 1. 개요 및 배경

엔터프라이즈 리눅스 환경의 보안 침해 방지 시스템(EDR, 안티바이러스, Falco, CrowdStrike Falcon)이나 파일 무결성 모니터링(FIM) 도구들은 악성코드나 인가되지 않은 프로세스가 민감한 바이너리를 실행하거나 시스템 설정 파일을 조작하는 것을 **실시간으로 탐지하고 차단**해야 합니다.

전통적인 리눅스 `inotify` 서브시스템은 파일 수정(`IN_MODIFY`)이나 생성(`IN_CREATE`)이 일어난 **'사후(Post-hoc)'**에만 알림을 줄 수 있을 뿐, 파일이 열리는 순간 프로세스를 일시 중지시키고 악성 여부를 검사하여 실행을 차단(Pre-execution Blocking)하는 능력이 전무했습니다. 또한 마운트 포인트나 전체 파일시스템 단위의 감시가 불가능하여 수만 개의 디렉토리마다 개별 워치(Watch)를 등록해야 하는 치명적인 한계가 있었습니다.

이를 극복하기 위해 리눅스 커널 2.6.36에 도입되고 5.1+에 대폭 현대화된 **Fanotify (Filesystem Access Notification, `fs/notify/fanotify/`)**는 다음 세 가지 혁신적인 기능을 제공합니다:
1. **동기적 접근 권한 제어 (Permission Events)**: 프로세스가 파일을 실행(`FAN_OPEN_EXEC_PERM`)하거나 열 때(`FAN_OPEN_PERM`), VFS 커널 계층에서 호출 프로세스를 대기 상태(`wait_event_interruptible`)로 정지시키고, 유저스페이스 보안 데몬에게 익명 파일 디스크립터(Anonymous FD)를 전달하여 검사를 요청합니다. 데몬이 `FAN_ALLOW`를 회신하면 프로세스가 재개되고, `FAN_DENY`를 회신하면 즉시 `-EPERM`(Access Denied)으로 차단됩니다.
2. **이벤트 병합(Event Merging / Coalescing)**: 동일 프로세스가 동일 파일에 연속적으로 수많은 쓰기/수정(`FAN_MODIFY`)을 발생시킬 때, 큐 메모리 고갈을 방지하기 위해 단일 이벤트로 병합(Coalesce)하여 큐 부하를 획기적으로 줄입니다.
3. **큐 오버플로우 관리 (`FAN_Q_OVERFLOW`)**: 이벤트 큐가 최대 용량(`max_queue_size`)에 도달하면 신규 비동기 알림을 드롭하고 오버플로우 이벤트를 게시하여 감사 중단을 알립니다.
4. **계층적 마크 및 무시 마스크 (Marks & Ignored Masks)**: 개별 아이노드(`FAN_MARK_INODE`), 마운트 포인트(`FAN_MARK_MOUNT`), 전체 파일시스템(`FAN_MARK_FILESYSTEM`) 단위로 감시 대상을 설정하고, 임시 파일이나 로그의 노이즈를 억제하는 `FAN_MARK_IGNORED_MASK`를 지원합니다.

당신은 리눅스 보안 에이전트의 커널 인터페이스를 가상화하기 위해, Fanotify의 마크 매칭, 동기 권한 가로채기, 비동기 알림 큐 병합 및 오버플로우 상태 머신을 정밀하게 모사하는 **리눅스 커널 Fanotify 파일 보안 엔진**을 설계해야 합니다.

---

## 2. 시스템 아키텍처 및 이벤트 흐름

```
       [ 사용자 프로세스 P (open / exec / write / modify) ]
                               │
                               ▼
        [ 리눅스 VFS 레이어: fsnotify_file_perm / fsnotify_open ]
                               │
              ┌────────────────┴────────────────┐
              ▼                                 ▼
   [ 동기 권한 이벤트 (PERM) ]       [ 비동기 알림 이벤트 (NOTIF) ]
  (FAN_OPEN_EXEC_PERM 등)            (FAN_MODIFY, FAN_CLOSE_WRITE)
              │                                 │
   프로세스 P 대기 상태로 정지        연속 중복 이벤트 병합 검사
              │                                 │
              ▼                       ┌─────────┴─────────┐
    [ 보안 데몬 검사 요청 ]          ▼                   ▼
              │                   [병합 성공]         [신규 큐잉]
              ▼                   (카운트 증가)   (max_queue_size 검사)
      [ 데몬 룰 조회 ]                                    │
              │                                  ┌────────┴────────┐
      ┌───────┴───────┐                          ▼                 ▼
      ▼               ▼                     [정상 인큐]     [FAN_Q_OVERFLOW]
 [FAN_ALLOW]     [FAN_DENY]                                  (용량 초과 경보)
      │               │
  프로세스 P       프로세스 P
  실행 재개        차단 (-EPERM)
```

---

## 3. 핵심 규칙 및 알고리즘 명세

### 3.1 Fanotify 마크 매칭 규칙
- `marks` 목록은 감시 대상 경로(`path`), 마크 범위(`mark_type`: `"INODE"`, `"MOUNT"`, `"FILESYSTEM"`), 감시 이벤트 마스크(`mask`), 무시할 이벤트 마스크(`ignored_mask`)를 포함합니다.
- VFS 이벤트 발생 시:
  1. `ignored_mask` 검사: 이벤트 타입이 `ignored_mask`에 포함되어 있고 경로가 일치하면(MOUNT는 접두사 일치, INODE는 완전 일치, FILESYSTEM은 전체), 감시 대상에서 **즉시 제외(무시)**됩니다.
  2. `mask` 검사: 이벤트 타입이 `mask`에 포함되어 있고 경로 규칙(INODE: 경로 일치, MOUNT: 경로 접두사 일치, FILESYSTEM: 전체 일치)을 만족하면 Fanotify 모니터링 대상으로 확정됩니다.

### 3.2 동기 권한 제어 파이프라인 (`_PERM`)
- `op`가 `OPEN_EXEC` (`FAN_OPEN_EXEC_PERM`), `OPEN_PERM` (`FAN_OPEN_PERM`), `ACCESS_PERM` (`FAN_ACCESS_PERM`) 등 권한 검사 이벤트인 경우:
  - `perm_requests_received` 1 증가.
  - `daemon_rules` 딕셔너리에서 해당 `path`의 판정을 조회합니다:
    - `"FAN_DENY"`: `perm_denied` 1 증가, VFS 결과는 `"EPERM_BLOCKED"`.
    - `"FAN_ALLOW"` (또는 미등록 기본값): `perm_allowed` 1 증가, VFS 결과는 `"SUCCESS"`.
  - 권한 이벤트는 프로세스 동기 블로킹이므로 비동기 `event_queue`에 적재되지 않고 즉시 완료 처리됩니다.

### 3.3 비동기 알림 및 큐 병합 파이프라인 (NOTIF)
- `op`가 `MODIFY` (`FAN_MODIFY`), `CLOSE_WRITE` (`FAN_CLOSE_WRITE`), `ACCESS` (`FAN_ACCESS`) 등 비동기 알림 이벤트인 경우:
  - **이벤트 병합 (Event Merging)**:
    - `event_queue`가 비어있지 않고, **직전 큐의 마지막 이벤트**가 동일한 `path`, 동일한 `pid`, 동일한 `fan_type`을 가지는 경우:
      - 신규 큐 엔트리를 생성하지 않고 기존 엔트리의 `count`를 1 증가시킵니다.
      - `stats.events_merged` 1 증가 (`event: "FANOTIFY_EVENT_MERGED"`).
  - **신규 큐잉 및 오버플로우 검사**:
    - 병합되지 않은 경우, 현재 큐 길이 `len(event_queue)`를 검사합니다:
      - `len(event_queue) >= max_queue_size`:
        - 큐 용량이 초과되었으므로 이벤트를 드롭합니다.
        - `overflow_active` 플래그가 거짓인 경우, 단 한 번 `FAN_Q_OVERFLOW` 이벤트를 기록하고 `stats.queue_overflow_count`를 1 증가시킵니다.
      - `len(event_queue) < max_queue_size`:
        - 큐에 신규 이벤트 엔트리(`{"pid", "path", "fan_type", "count": 1}`)를 인큐합니다.
        - `stats.notif_events_queued` 1 증가 (`event: "FANOTIFY_NOTIF_ENQUEUED"`).

### 3.4 데몬 이벤트 큐 드레인 (`DAEMON_READ_EVENTS`)
- 유저스페이스 데몬이 `count`개의 이벤트를 큐에서 꺼내 처리(pop)합니다.
- 큐 크기가 `max_queue_size` 미만으로 내려가면 `overflow_active` 상태가 해제됩니다.

---

## 4. 입출력 형식 및 제약 조건

### 입력 형식 (JSON)
```json
{
  "group_config": {
    "notification_class": "FAN_CLASS_CONTENT",
    "max_queue_size": 10
  },
  "marks": [
    {
      "path": "/usr/bin",
      "mark_type": "MOUNT",
      "mask": ["FAN_OPEN_EXEC_PERM"],
      "ignored_mask": []
    }
  ],
  "daemon_rules": {
    "/usr/bin/rootkit": "FAN_DENY",
    "/usr/bin/python3": "FAN_ALLOW"
  },
  "events": [
    { "type": "VFS_ACCESS", "pid": 2001, "path": "/usr/bin/python3", "op": "OPEN_EXEC" },
    { "type": "VFS_ACCESS", "pid": 2002, "path": "/usr/bin/rootkit", "op": "OPEN_EXEC" }
  ]
}
```

### 출력 형식 (JSON)
```json
{
  "stats": {
    "perm_requests_received": 2,
    "perm_allowed": 1,
    "perm_denied": 1,
    "notif_events_queued": 0,
    "events_merged": 0,
    "queue_overflow_count": 0,
    "vfs_calls_completed": 2
  },
  "queue_status": {
    "current_queue_depth": 0,
    "max_queue_size": 10,
    "overflow_active": false
  },
  "event_logs": [ ... ]
}
```
