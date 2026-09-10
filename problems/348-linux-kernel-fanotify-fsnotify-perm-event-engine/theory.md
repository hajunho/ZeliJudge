# 리눅스 커널 Fanotify 파일시스템 접근 통지 및 동기 권한 제어 이론 백서

## 1. 리눅스 파일시스템 통지 서브시스템의 진화

리눅스 커널은 유저스페이스에 파일시스템 변경 사항을 알리기 위해 다양한 메커니즘을 발전시켜 왔습니다:

| 서브시스템 | 도입 시기 | 주요 한계 | 핵심 특징 |
|:---:|:---:|:---:|:---:|
| **Dnotify** | Linux 2.4 | 디렉토리 단위만 감시, FD 누수, 시그널(SIGIO) 기반 | 사후 비동기 통지, 오버헤드 큼 |
| **Inotify** | Linux 2.6.13 | 재귀 감시 불가, 마운트 감시 불가, 권한 차단 불가 | 파일/디렉토리 감시, 비동기 이벤트 |
| **Fanotify** | Linux 2.6.36+ (5.1+ 대폭 개선) | 초기 구현의 복잡성 (루트 권한 CAP_SYS_ADMIN 필요) | **동기 권한 차단 (Permission), 마운트/FS 감시, 열린 FD 직접 전달** |

---

## 2. Inotify vs Fanotify: 왜 현대 EDR은 Fanotify를 쓰는가?

### 2.1 TOCTOU (Time-of-Check to Time-of-Use) 경쟁 상태 제거
- `inotify`는 파일 경로 이름 문자열만 전달합니다. 데몬이 이벤트를 받고 해당 경로를 열어 바이러스를 검사하려 할 때, 악의적인 프로세스는 이미 파일을 다른 경로로 심볼릭 링크를 걸거나 내용을 바꿔치기할 수 있습니다.
- `fanotify`는 커널 VFS가 열어둔 원본 파일의 **익명 파일 디스크립터(Anonymous FD)**를 데몬에게 직접 전달합니다. 데몬은 심볼릭 링크 레이스 컨디션 없이 정확히 열린 그 물리 아이노드 파일을 검사합니다.

### 2.2 사전 차단 (Pre-Execution Permission Intercept)
- `fanotify_init` 호출 시 `FAN_CLASS_CONTENT` 또는 `FAN_CLASS_PRE_CONTENT`를 지정하면, `FAN_OPEN_PERM`, `FAN_OPEN_EXEC_PERM` 이벤트를 수신할 수 있습니다.
- 커널은 시스템 콜(`sys_open`, `sys_execve`) 내부에서 호출 스레드를 `wait_event_interruptible`로 정지시킵니다.
- 유저스페이스 백신 데몬이 검사 후 `FAN_ALLOW` 또는 `FAN_DENY`를 `write()`할 때까지 스레드는 멈춰 있으므로, 악성 코드가 단 1바이트의 CPU 인스트럭션도 실행하지 못하도록 100% 차단할 수 있습니다.

---

## 3. 커널 내부 구현 구조 (`fs/notify/fanotify/`)

1. **fsnotify 그룹 (`struct fsnotify_group`)**:
   - 각 fanotify 인스턴스는 커널 내부의 독립적인 그룹 객체입니다.
   - 그룹은 큐 길이 제한(`max_events`), 대기 중인 이벤트 리스트(`notification_list`), 그리고 권한 이벤트를 기다리는 스레드들의 대기 큐(`access_waitq`)를 관리합니다.
2. **이벤트 병합 (Event Merging)**:
   - 빠른 속도로 대량의 데이터가 기록될 때, 수백만 개의 `FAN_MODIFY` 이벤트가 큐에 쌓이면 OOM(Out of Memory)이 발생합니다.
   - Fanotify는 신규 이벤트 삽입 시 직전 이벤트와 파일 아이노드, PID, 이벤트 마스크가 동일한지 검사하여, 일치할 경우 기존 이벤트 레코드에 플래그만 합치고 메모리 할당을 건너뜁니다.
3. **교착 상태(Deadlock) 방지 주의점**:
   - 보안 데몬이 검사를 위해 파일을 열 때, 만약 그 오픈 행위가 다시 자신의 fanotify 그룹에 의해 감시된다면 **데몬 자신이 자신을 기다리는 재귀적 데드락(Deadlock)**에 빠집니다.
   - 이를 방지하기 위해 데몬은 자신에게 전달된 익명 FD만을 사용하거나, 데몬 프로세스의 PID를 이벤트 필터링에서 예외 처리해야 합니다.
