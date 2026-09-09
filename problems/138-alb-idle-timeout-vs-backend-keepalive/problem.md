# 간헐적으로 502 Bad Gateway가 떠요?!: 로드밸런서(ALB) Idle Timeout vs 백엔드 Keep-Alive Timeout 불일치 레이스 컨디션

## 1. 실무 시나리오

당신은 AWS 클라우드 환경에서 대규모 전자상거래 플랫폼의 인프라와 백엔드를 운영하는 SRE(Site Reliability Engineer)입니다.

현재 시스템은 인터넷 유저의 트래픽을 **AWS ALB(Application Load Balancer)**가 먼저 받아 백엔드 서버(Node.js / Spring Boot)로 분산 전달하는 전형적인 L7 리버스 프록시 구조로 구성되어 있습니다.  
서버의 CPU 사용률은 10% 미만으로 한가하며, 메모리 누수도 없고, 백엔드 애플리케이션의 `error.log`에는 어떤 에러도 찍히지 않습니다.

그런데 이상하게도 **1분에 서너 번씩, 유저들에게 간헐적인 "502 Bad Gateway" 에러가 불규칙하게 발생**하여 고객센터로 불만이 쏟아지고 있습니다!

```
[클라이언트 유저] ──► [AWS ALB (Idle Timeout: 60s)] ──► [백엔드 서버 (Keep-Alive: 60s)]
                                                    💥 엇갈리는 FIN 패킷과 RST 충돌!
                                                    💥 백엔드 로그 0줄, 유저는 502 에러!
```

ALB 액세스 로그와 TCP 패킷을 정밀 분석한 결과, 기가 막힌 원인이 밝혀졌습니다:
1. ALB의 유휴 타임아웃(`alb_idle_timeout_ms = 60,000ms`)과 백엔드의 지속 연결 타임아웃(`backend_keepalive_timeout_ms = 60,000ms`)이 **동일하게 설정**되어 있었습니다.
2. 이전 요청이 끝나고 정확히 60초가 지난 순간, 백엔드 서버는 커넥션을 정리하기 위해 커널 소켓을 닫고 `FIN` 패킷을 ALB를 향해 전송했습니다.
3. 하지만 네트워크 지연 시간(2ms) 동안 이 `FIN` 패킷이 아직 ALB에 도달하지 않은 바로 그 찰나(59.999초 경과 시점), ALB는 "이 커넥션은 아직 60초가 안 지났으니 살아있다!"고 판단하여 **새로운 유저 요청을 방금 닫힌 커넥션으로 전송**해 버렸습니다!
4. 백엔드 서버 커널은 이미 `close()`된 소켓으로 데이터가 인입되자 즉시 **`TCP RST`(Reset)**를 날려버렸고, ALB는 요청이 거절당하자 유저에게 즉시 **502 Bad Gateway**를 뿜어낸 것입니다!

당신은 로드밸런서와 백엔드 간의 HTTP Keep-Alive 커넥션 풀 라이프사이클을 정밀 시뮬레이션하여, 타임아웃 불일치로 인한 502 레이스 컨디션 충돌 횟수를 감지하고, "백엔드 Keep-Alive Timeout > ALB Idle Timeout" 황금률을 검증하는 저지 솔루션을 구현해야 합니다.

---

## 2. 시스템 및 커넥션 풀 시뮬레이션 규칙

### (1) 커넥션 상태 및 라이프사이클
- ALB는 백엔드 서버와 수립된 TCP 지속 연결(Keep-Alive)들을 커넥션 풀(`connections`)에 보관합니다.
- 각 커넥션은 다음 속성을 가집니다:
  - `conn_id`: 커넥션 고유 번호 (1부터 순차 증가)
  - `state`: `"IDLE"` (유휴), `"BUSY"` (요청 처리 중), `"CLOSED"` (종료)
  - `busy_until_time`: 현재 진행 중인 요청의 완료 예정 시점
  - `last_activity_time`: 마지막으로 데이터 송수신(요청 완료)이 이루어진 시점
  - `backend_close_time`: 백엔드가 유휴 만료로 소켓을 닫고 `FIN`을 보내는 시점 ($last\_activity\_time + backend\_keepalive\_timeout\_ms$)
  - `backend_fin_reach_alb_time`: 백엔드의 `FIN` 패킷이 ALB에 도달하는 시점 ($backend\_close\_time + network\_latency\_ms$)
  - `alb_close_time`: ALB가 유휴 만료로 커넥션을 능동 폐기하는 시점 ($last\_activity\_time + alb\_idle_timeout\_ms$)

### (2) 요청 도착 시 커넥션 풀 업데이트 및 탐색
새로운 요청이 $T_{arr}$ (`arrival_time_ms`)에 도착했을 때:
1. **기존 커넥션 상태 갱신**:
   - `state == "BUSY"`이고 $busy\_until\_time \le T_{arr}$인 커넥션은 `"IDLE"` 상태로 복귀합니다.
   - `"IDLE"` 커넥션 중 $alb\_close\_time \le T_{arr}$인 경우: ALB가 유휴 타임아웃으로 커넥션을 먼저 닫습니다 (`state = "CLOSED"`, `alb_initiated_closes += 1`).
   - `"IDLE"` 커넥션 중 $backend\_fin\_reach\_alb\_time \le T_{arr}$인 경우: 백엔드가 보낸 `FIN`이 ALB에 이미 도착했으므로 커넥션을 닫습니다 (`state = "CLOSED"`, `backend_initiated_closes += 1`).
2. **사용 가능한 IDLE 커넥션 탐색**:
   - 커넥션 풀의 `"IDLE"` 커넥션 중 ALB 입장에서 아직 유휴 타임아웃이 지나지 않은($T_{arr} - last\_activity\_time < alb\_idle\_timeout\_ms$) 커넥션이 있는지 확인합니다.
   - **재사용 가능한 커넥션이 있는 경우**:
     - 해당 커넥션을 선택하고 `reused_connections_count += 1`을 기록합니다.
   - **재사용 가능한 커넥션이 없는 경우**:
     - 새로운 TCP 커넥션을 생성하여 풀에 추가하고 `new_connections_created += 1`을 기록합니다.

### (3) 요청 전송 및 502 레이스 컨디션 충돌 판정
- 선택된 커넥션에 요청을 전송하면 커넥션은 `BUSY` 상태가 됩니다.
- 요청 패킷이 백엔드에 도달하는 시점은 $T_{reach} = T_{arr} + network\_latency\_ms$ 입니다.
- 이 요청의 전체 완료 시점은 $T_{comp} = T_{reach} + processing\_time\_ms + network\_latency\_ms$ 이며, $busy\_until\_time = T_{comp}$ 로 설정됩니다.
- **502 레이스 컨디션 충돌 판정**:
  - 만약 커넥션이 **재사용(`is_reused == True`)**되었고,
  - **요청 패킷이 백엔드에 도달한 시점($T_{reach}$)이 백엔드가 소켓을 닫은 시점($backend\_close\_time$)보다 늦다면 ($T_{reach} > backend\_close\_time$)**:
    $	o$ 💥 **502 Bad Gateway 발생!**
    - 백엔드는 이미 닫힌 소켓에 데이터가 들어와 `RST`를 반환합니다.
    - `race_condition_collisions += 1`, `failed_requests_502 += 1` 기록.
    - 커넥션은 즉시 `"CLOSED"` 처리되며 이후 재사용되지 않습니다.
    - 요청 결과는 `status = "502_BAD_GATEWAY_RACE_CONDITION"`이 됩니다.
- **정상 처리 판정**:
  - 충돌이 발생하지 않은 경우:
    - `successful_requests += 1`, `status = "200_OK"`.
    - 요청 완료 시점($T_{comp}$)을 기준으로 `last_activity_time`, `backend_close_time`, `backend_fin_reach_alb_time`, `alb_close_time`이 새롭게 갱신됩니다.

### (4) 최종 시스템 진단 판정 (`overall_verdict`)
- `total_requests == 0`: `"NO_REQUESTS"`
- `failed_requests_502 > 0`: `"BACKEND_TIMEOUT_SHORTER_OR_EQUAL_502_RISK"`
- `timeout_difference_ms > 0` AND `failed_requests_502 == 0`: `"OPTIMAL_BACKEND_TIMEOUT_PROTECTED"`
- `reused_connections_count == 0` AND `total_requests > 1`: `"ZERO_REUSE_SHORT_KEEPALIVE"`
- 그 외: `"HEALTHY_NO_COLLISION"`

---

## 3. 입력 형식 (JSON)

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다:

```json
{
  "alb_idle_timeout_ms": 60000,
  "backend_keepalive_timeout_ms": 60000,
  "network_latency_ms": 2,
  "requests": [
    {"request_id": "req-1", "arrival_time_ms": 0, "processing_time_ms": 100},
    {"request_id": "req-2", "arrival_time_ms": 60103, "processing_time_ms": 50}
  ]
}
```

- `alb_idle_timeout_ms` (int, 기본값 60000): ALB의 유휴 커넥션 만료 타임아웃 (ms).
- `backend_keepalive_timeout_ms` (int, 기본값 60000): 백엔드 서버의 Keep-Alive 유휴 만료 타임아웃 (ms).
- `network_latency_ms` (int, 기본값 2): ALB와 백엔드 간 편도 네트워크 전파 지연 시간 (ms).
- `requests` (list of dict): 유저 요청 목록. 각 항목은 `request_id`, `arrival_time_ms`, `processing_time_ms`를 가짐.

---

## 4. 출력 형식 (JSON)

표준 출력(stdout)으로 다음 구조의 JSON 객체를 인덴트(2칸)를 적용하여 출력합니다:

```json
{
  "summary": {
    "alb_idle_timeout_ms": 60000,
    "backend_keepalive_timeout_ms": 60000,
    "timeout_difference_ms": 0,
    "total_requests": 2,
    "successful_requests": 1,
    "failed_requests_502": 1,
    "new_connections_created": 1,
    "reused_connections_count": 1,
    "race_condition_collisions": 1,
    "alb_initiated_closes": 0,
    "backend_initiated_closes": 0,
    "overall_verdict": "BACKEND_TIMEOUT_SHORTER_OR_EQUAL_502_RISK"
  },
  "sample_results": [
    {
      "request_id": "req-1",
      "connection_id": 1,
      "status": "200_OK",
      "reused": false,
      "arrival_time_ms": 0,
      "finish_time_ms": 104
    },
    {
      "request_id": "req-2",
      "connection_id": 1,
      "status": "502_BAD_GATEWAY_RACE_CONDITION",
      "reused": true,
      "arrival_time_ms": 60103,
      "error_detail": "Request reached backend at 60105ms after backend closed at 60104ms"
    }
  ]
}
```

- `summary`:
  - `timeout_difference_ms`: `backend_keepalive_timeout_ms - alb_idle_timeout_ms`.
  - `total_requests`: 총 요청 수.
  - `successful_requests`: 성공적으로 처리된 요청 수 (200 OK).
  - `failed_requests_502`: 502 레이스 컨디션으로 실패한 요청 수.
  - `new_connections_created`: 신규 수립된 TCP 커넥션 수.
  - `reused_connections_count`: 기존 커넥션을 재사용한 횟수.
  - `race_condition_collisions`: 백엔드 소켓 닫힘과 요청 도착이 엇갈린 충돌 횟수.
  - `alb_initiated_closes`: ALB가 유휴 타임아웃으로 먼저 닫은 커넥션 수.
  - `backend_initiated_closes`: 백엔드가 보낸 FIN을 수신하여 닫힌 커넥션 수.
  - `overall_verdict`: 시스템 진단 결과 문자열.
- `sample_results`: 전체 요청 중 최초 10개 요청의 처리 결과 목록 (`request_results[:10]`).

---

## 5. 입출력 예시

### 예시 1: 동일 타임아웃(60s vs 60s)으로 인한 간헐적 502 Bad Gateway 참사
**입력:**
```json
{
  "alb_idle_timeout_ms": 60000,
  "backend_keepalive_timeout_ms": 60000,
  "network_latency_ms": 2,
  "requests": [
    {"request_id": "req-1", "arrival_time_ms": 0, "processing_time_ms": 100},
    {"request_id": "req-2", "arrival_time_ms": 60103, "processing_time_ms": 50}
  ]
}
```

**출력:**
```json
{
  "summary": {
    "alb_idle_timeout_ms": 60000,
    "backend_keepalive_timeout_ms": 60000,
    "timeout_difference_ms": 0,
    "total_requests": 2,
    "successful_requests": 1,
    "failed_requests_502": 1,
    "new_connections_created": 1,
    "reused_connections_count": 1,
    "race_condition_collisions": 1,
    "alb_initiated_closes": 0,
    "backend_initiated_closes": 0,
    "overall_verdict": "BACKEND_TIMEOUT_SHORTER_OR_EQUAL_502_RISK"
  },
  "sample_results": [
    {
      "request_id": "req-1",
      "connection_id": 1,
      "status": "200_OK",
      "reused": false,
      "arrival_time_ms": 0,
      "finish_time_ms": 104
    },
    {
      "request_id": "req-2",
      "connection_id": 1,
      "status": "502_BAD_GATEWAY_RACE_CONDITION",
      "reused": true,
      "arrival_time_ms": 60103,
      "error_detail": "Request reached backend at 60105ms after backend closed at 60104ms"
    }
  ]
}
```

---

### 예시 2: 황금률 적용 (백엔드 65s > ALB 60s) 완벽 보호
**입력:**
```json
{
  "alb_idle_timeout_ms": 60000,
  "backend_keepalive_timeout_ms": 65000,
  "network_latency_ms": 2,
  "requests": [
    {"request_id": "req-1", "arrival_time_ms": 0, "processing_time_ms": 100},
    {"request_id": "req-2", "arrival_time_ms": 60103, "processing_time_ms": 50}
  ]
}
```

**출력:**
```json
{
  "summary": {
    "alb_idle_timeout_ms": 60000,
    "backend_keepalive_timeout_ms": 65000,
    "timeout_difference_ms": 5000,
    "total_requests": 2,
    "successful_requests": 2,
    "failed_requests_502": 0,
    "new_connections_created": 1,
    "reused_connections_count": 1,
    "race_condition_collisions": 0,
    "alb_initiated_closes": 0,
    "backend_initiated_closes": 0,
    "overall_verdict": "OPTIMAL_BACKEND_TIMEOUT_PROTECTED"
  },
  "sample_results": [
    {
      "request_id": "req-1",
      "connection_id": 1,
      "status": "200_OK",
      "reused": false,
      "arrival_time_ms": 0,
      "finish_time_ms": 104
    },
    {
      "request_id": "req-2",
      "connection_id": 1,
      "status": "200_OK",
      "reused": true,
      "arrival_time_ms": 60103,
      "finish_time_ms": 60157
    }
  ]
}
```
