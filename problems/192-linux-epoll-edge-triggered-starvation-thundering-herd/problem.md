# Problem 192: 리눅스 네트워크 I/O 멀티플렉싱: epoll 엣지 트리거(ET) 소켓 기아(Starvation)와 썬더링 허드(Thundering Herd) 컨텍스트 스위칭 폭풍 방어

## 문제 설명

수십만 동시 연결(C100K/C1000K)을 처리하는 고성능 API 게이트웨이(Nginx, Envoy) 및 분산 게임 서버를 운영하는 플랫폼 엔지니어링 팀은 멀티코어 서버 배포 후 두 가지 치명적인 병목 현상을 마주했습니다.

1. **엣지 트리거(Edge-Triggered, `EPOLLET`) 미완료 데이터 유실 고착 참사**:
   - 시스템 호출 오버헤드를 줄이기 위해 기본 레벨 트리거(`EPOLLLT`) 대신 엣지 트리거(`EPOLLET`)를 도입했습니다.
   - 그러나 특정 클라이언트의 HTTP 요청이나 WebSocket 메시지가 처리 도중 멈춰서며, 클라이언트가 타임아웃될 때까지 **영구히 응답을 받지 못하는 기아(Starvation) 현상**이 빈번하게 발생했습니다.
   - 분석 결과, 애플리케이션이 `epoll_wait()` 통지를 받고 `read()`를 단 1회(예: 4KB)만 호출한 뒤 반환했을 때, 소켓 수신 버퍼에 남은 잔여 데이터(예: 12KB)는 상태 전이(State Transition, Edge)가 발생하지 않아 **리눅스 커널이 영원히 새 epoll 이벤트를 통지하지 않는 엣지 트리거 데이터 트랩** 때문이었습니다.
2. **멀티스레드 썬더링 허드(Thundering Herd) CPU 스위칭 폭풍**:
   - 16~32개의 워커 스레드가 동일한 리슨 소켓(`listen_fd`)에 대해 각자의 epoll 인스턴스에서 대기(`epoll_wait()`)하고 있을 때, 단 1건의 신규 클라이언트 연결이 도착했음에도 **모든 워커 스레드가 일제히 깨어나는 썬더링 허드(Thundering Herd)** 현상이 일어났습니다.
   - 실제 연결 수락(`accept()`)은 오직 1개 스레드만 성공하고 나머지 15~31개 스레드는 `EAGAIN`/`EWOULDBLOCK` 에러를 반환하며 불필요한 컨텍스트 스위칭과 CPU 캐시 오염을 일으켜 CPU 사용률이 100%로 치솟았습니다.
3. **탐욕적 루프(Greedy Loop)의 다른 소켓 기아 문제**:
   - 엣지 트리거의 잔여 데이터 문제를 해결하기 위해 `read()`를 `EAGAIN`이 반환될 때까지 무한 루프로 비우려(Drain) 하자, 악의적인 대용량 업로드 클라이언트나 고속 스트리밍 연결이 루프를 독점하여 동일 워커 스레드가 관리하는 수천 개의 다른 정상 소켓들이 서비스 기아에 빠지는 부작용이 발생했습니다.

엔지니어링 팀은 리눅스 4.5에서 도입된 **`EPOLLEXCLUSIVE`** 플래그와 **바운디드 드레인(Bounded Drain & Fair Yield)** 아키텍처를 시뮬레이션하여 프로덕션 이벤트 루프의 무결성을 검증하고자 합니다.

---

## 핵심 시스템 파라미터 및 동작 모드

### 1. 트리거 모드 (`epoll_trigger_mode`)
- `LEVEL_TRIGGERED`: 수신 버퍼에 읽을 데이터가 남아있는 한, 매번 `epoll_wait()` 호출 시 이벤트가 반복 통지됩니다. 단일 `read()` 후에도 다음 턴에서 안전하게 재통지됩니다.
- `EDGE_TRIGGERED`: 데이터가 도착하여 버퍼 상태가 변할 때(상태 전이 엣지) 단 1회만 통지됩니다. 수신 버퍼를 완전히 비우지 않고 루프를 빠져나오면, 새 데이터가 유입되기 전까지 이벤트가 절대 발생하지 않아 잔여 데이터가 고착됩니다.

### 2. 썬더링 허드 방어 플래그 (`use_epollexclusive`)
- `false`: 단일 리슨 소켓에 신규 연결 이벤트 발생 시, 해당 소켓을 감시 중인 모든 워커 스레드가 전원 기상(Thundering Herd)합니다.
- `true` (`EPOLLEXCLUSIVE`): 커널 레벨에서 단 1개의 워커 스레드만 배타적으로 깨워 불필요한 컨텍스트 스위칭을 완벽히 차단(0건)합니다.

### 3. 드레인 정책 (`drain_policy`)
- `NAIVE_SINGLE_READ`: 버퍼에서 단 1회 고정 청크(최대 4KB)만 읽고 반환. 엣지 트리거 모드에서 잔여 바이트가 남을 시 즉각 기아 발생.
- `GREEDY_INFINITE_LOOP`: `EAGAIN`을 만날 때까지 단일 소켓을 끝까지 읽음.
- `BOUNDED_DRAIN`: 연결당 정해진 바운드 예산(예: 64KB)까지만 읽고 다음 연결로 공평하게 양보(Fair Yield)하여 다중 소켓 기아를 방지하면서도 잔여 버퍼를 남기지 않음.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다.

```json
{
  "system": {
    "epoll_trigger_mode": "EDGE_TRIGGERED",
    "use_epollexclusive": true,
    "worker_threads": 8,
    "max_read_budget_bytes": 65536
  },
  "events": [
    {
      "timestamp_ms": 0.0,
      "type": "NEW_CONNECTION",
      "connection_id": "c1"
    },
    {
      "timestamp_ms": 5.0,
      "type": "DATA_ARRIVE",
      "connection_id": "c1",
      "bytes": 20480
    },
    {
      "timestamp_ms": 10.0,
      "type": "EPOLL_DISPATCH_AND_READ",
      "worker_id": "w0",
      "drain_policy": "BOUNDED_DRAIN"
    }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 JSON 형식 결과를 출력합니다.

```json
{
  "status": "SUCCESS",
  "metrics": {
    "total_epoll_waits": 1,
    "thundering_herd_wakeups": 0,
    "bytes_read_total": 20480,
    "starved_connections_count": 0,
    "unhandled_lingering_bytes": 0,
    "active_connections_count": 1,
    "verdict": "OPTIMAL_EPOLLEXCLUSIVE_BOUNDED_ET"
  },
  "events_log": [
    {
      "time_ms": 0.0,
      "event": "ACCEPT_EVENT",
      "connection_id": "c1",
      "woken_threads": 1
    }
  ]
}
```

### 판정 규칙 (Verdict Rules)
1. `thundering_herd_wakeups > 10`:
   - `status = "FAILED"`, `verdict = "THUNDERING_HERD_CONTEXT_SWITCH_STORM"`
2. `starved_connections_count > 0` 또는 `unhandled_lingering_bytes > 0`:
   - `status = "FAILED"`, `verdict = "EDGE_TRIGGERED_SOCKET_STARVATION_DATA_TRAPPED"`
3. 기아 0건, 썬더링 허드 10건 이하로 안전하게 완료된 경우:
   - `status = "SUCCESS"`, `verdict = "OPTIMAL_EPOLLEXCLUSIVE_BOUNDED_ET"`
