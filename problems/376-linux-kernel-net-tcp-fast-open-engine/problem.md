# #376 - 리눅스 커널 네트워크 TCP Fast Open (TFO / RFC 7413): 0-RTT 핸드셰이크 데이터 교환, 암호화 쿠키 생성·검증 및 SYN 플러드 방어 엔진

## 📖 문제 배경과 역사적 맥락

> *"전통적인 TCP 3-Way Handshake는 연결 수립에 최소 1-RTT의 지연 시간(Latency)을 강제한다. 웹 검색, HTTP/HTTPS API 호출, 짧은 RPC 트랜잭션과 같은 단기 연결(Short-lived Connections) 환경에서 이 1-RTT 지연은 전체 응답 시간의 50% 이상을 차지한다. TCP Fast Open(RFC 7413)은 암호학적으로 안전한 서버 쿠키를 통해 최초 SYN 패킷에 애플리케이션 데이터를 함께 실어 보내는 0-RTT 데이터 교환을 구현함으로써 웹 왕복 시간을 획기적으로 단축시켰다."*  
> — **Linux Kernel Network Subsystem (`net/ipv4/tcp_fastopen.c`, RFC 7413)**

초기 인터넷 환경에서는 대용량 파일 전송(FTP)이나 지속적인 원격 세션(Telnet)이 주를 이루었으나, 현대의 분산 클라우드 및 마이크로서비스 아키텍처에서는 수많은 단기 HTTP/RPC 연결이 폭발적으로 생성됩니다. 기존 TCP에서는 클라이언트가 `SYN`을 보내고, 서버의 `SYN-ACK`를 받아 `ACK`를 전송한 뒤에야 비로소 요청 데이터를 보낼 수 있어, 물리적 거리에 따른 광속 한계(RTT)가 서비스 응답성의 절대적 병목이 되었습니다.

구글과 리눅스 커널 커뮤니티가 공동 개발하고 IETF 표준으로 채택된 **TCP Fast Open(TFO / RFC 7413)**은 다음과 같은 혁신적 구조로 1-RTT 지연을 제거했습니다:

```
                  [전통적 TCP: 1-RTT 지연]
Client                                                 Server
  |                        SYN                           |
  |----------------------------------------------------->|
  |                      SYN-ACK                         |
  |<-----------------------------------------------------|
  |                    ACK + HTTP GET                    |
  |----------------------------------------------------->| (1-RTT 후 첫 데이터 전달)
  |                     HTTP 200 OK                      |
  |<-----------------------------------------------------|

                [TCP Fast Open (TFO): 0-RTT 데이터 교환]
Client                                                 Server
  | (Cookie 보유) SYN + TFO Option + HTTP GET [0-RTT]    |
  |----------------------------------------------------->| (즉시 소켓 수신 큐에 데이터 전달!)
  |             SYN-ACK (Acking SYN + Data)              |
  |<-----------------------------------------------------|
  |                 ACK / HTTP 200 OK                    |
  |<====================================================>|
```

### TCP Fast Open의 핵심 아키텍처 및 보안 메커니즘
1. **암호화 쿠키(TFO Cookie) 발급 및 검증**:
   - 증폭 디도스(Amplification Attack) 및 IP 스푸핑을 방지하기 위해, 클라이언트는 최초 연결 시 데이터 없이 빈 TFO 옵션(`COOKIE_REQUEST`)을 보내 16바이트 암호화 쿠키를 발급받습니다.
   - 서버는 비밀 키(`server_primary_key`)와 클라이언트 IP를 결합하여 암호학적 해시(SipHash-2-4 / AES-128) 쿠키를 생성합니다.
2. **0-RTT 데이터 수락 및 소켓 큐 전달**:
   - 쿠키를 캐싱한 클라이언트가 `SYN + Data`를 보내면, 서버는 쿠키의 유효성을 검증한 후 3-Way Handshake가 완료되기 전이라도 즉시 데이터를 소켓 수신 버퍼에 전달하여 애플리케이션이 즉시 처리를 시작하게 합니다.
3. **SYN 플러드(SYN Flood) 및 자원 고갈 방어**:
   - 검증된 쿠키를 가진 클라이언트라도 대량의 `SYN + Data`를 폭주시켜 서버 메모리를 고갈시키는 것을 방지하기 위해, 서버는 미완료 TFO 연결 전용 큐 크기(`max_fastopen_queue`)를 엄격히 제한합니다.
   - 큐가 가득 찬 경우, 서버는 TFO 데이터를 즉시 폐기하고 기존의 일반 3-Way Handshake로 폴백(`FALLOC_QUEUE_FULL`)하여 안전성을 보장합니다.
4. **무중단 서버 키 로테이션(Key Rotation)**:
   - 주기적인 보안 키 교체 시 이전 키(`server_backup_key`)로 생성된 쿠키를 임시 허용(`TFO_0RTT_SUCCESS_BACKUP_KEY`)하되, SYN-ACK 응답에 새로운 프라이머리 키로 서명된 신규 쿠키를 실어 보내 클라이언트 캐시를 갱신합니다.
5. **미들박스 블랙홀 탐지 및 폴백(Blackhole Detection)**:
   - 구형 방화벽이나 NAT 미들박스가 SYN 패킷의 페이로드를 비정상으로 간주하여 패킷을 드롭하는 경우, 클라이언트는 재전송 실패 임계치(`blackhole_threshold`)를 감지하여 TFO를 비활성화하고 표준 SYN으로 즉각 복구합니다.

본 과제에서는 리눅스 커널의 TCP Fast Open 프로토콜 상태 머신을 정밀하게 모델링하는 시뮬레이션 엔진을 구현합니다.

---

## 📥 입력 형식 (Input Specification)

입력은 표준 입력(Standard Input)으로 단일 JSON 객체가 주어집니다:

```json
{
  "config": {
    "server_primary_key": "k3y_alpha_999",
    "server_backup_key": null,
    "max_fastopen_queue": 2,
    "blackhole_threshold": 2
  },
  "initial_state": {
    "current_queue_len": 0,
    "client_cookie_cache": {},
    "consecutive_drops": 0,
    "tfo_disabled": false
  },
  "events": [
    {
      "type": "COOKIE_REQUEST",
      "params": {
        "client_ip": "192.168.1.10"
      }
    },
    {
      "type": "SYN_DATA_TRANSMIT",
      "params": {
        "conn_id": "c1",
        "client_ip": "192.168.1.10",
        "data_bytes": 1024,
        "network_drop": false
      }
    },
    {
      "type": "SYN_DATA_TRANSMIT",
      "params": {
        "conn_id": "c2",
        "client_ip": "192.168.1.10",
        "data_bytes": 2048,
        "network_drop": false
      }
    },
    {
      "type": "COMPLETE_HANDSHAKE",
      "params": {
        "conn_id": "c1"
      }
    }
  ]
}
```

### 파라미터 및 동작 규칙:
1. `config`:
   - `server_primary_key`: 서버 프라이머리 암호화 키 (문자열, 기본값 `"secr3t_k3y_pr1mary"`).
   - `server_backup_key`: 키 로테이션 시 이전 백업 키 (문자열 또는 `null`, 기본값 `null`).
   - `max_fastopen_queue`: 동시 미완료 TFO 핸드셰이크 큐 상한 (정수, 기본값 `10`).
   - `blackhole_threshold`: 미들박스 드롭 연속 발생 시 TFO 비활성화 임계치 (정수, 기본값 `2`).
2. `initial_state`:
   - `current_queue_len`: 현재 미완료 TFO 큐 길이 (기본값 `0`).
   - `client_cookie_cache`: 클라이언트 IP별 캐시된 쿠키 사전 (기본값 `{}`).
   - `consecutive_drops`: 연속 패킷 드롭 횟수 (기본값 `0`).
   - `tfo_disabled`: 클라이언트 측 TFO 비활성화 플래그 (기본값 `false`).
3. **쿠키 생성 함수 (`generate_tfo_cookie`)**:
   - HMAC-SHA256 알고리즘을 사용하며, 키와 클라이언트 IP를 UTF-8 인코딩하여 해시한 후 앞의 16자리 16진수 문자열(`h.hexdigest()[:16]`)을 취합니다.
4. `events`의 5가지 사건:
   - `COOKIE_REQUEST`:
     - 파라미터: `client_ip`.
     - 동작: 프라이머리 키로 새 쿠키 생성 후 `client_cookie_cache[client_ip]`에 저장.
     - 상태: `COOKIE_ISSUED`.
   - `SYN_DATA_TRANSMIT`:
     - 파라미터: `conn_id`, `client_ip`, `data_bytes`, `network_drop` (불리언).
     - 동작:
       1. 만약 `tfo_disabled == true`: TFO가 비활성화되어 있으므로 일반 3WHS로 폴백. `total_fallbacks += 1`, 상태: `FALLBACK_TFO_DISABLED`.
       2. 그렇지 않고 `network_drop == true` (미들박스 차단): `blackhole_failures += 1`. 만약 `blackhole_failures >= blackhole_threshold`이면 `tfo_disabled = true`. 상태: `SYN_DATA_DROPPED`.
       3. 패킷 정상 도착 시: `blackhole_failures = 0`.
          - 클라이언트가 제공한 쿠키가 프라이머리 키와 일치(`is_valid`)하는지, 또는 백업 키와 일치(`is_backup_valid`)하는지 검사.
          - 둘 다 일치하지 않으면: 프라이머리 키로 새 쿠키를 발급하여 클라이언트 캐시에 저장하고 일반 3WHS로 폴백. `total_fallbacks += 1`, 상태: `FALLBACK_INVALID_COOKIE`.
          - 쿠키는 유효하나 `current_queue_len >= max_fastopen_queue`: SYN 플러드 방어를 위해 데이터를 폐기하고 일반 3WHS로 폴백. `total_syn_floods_mitigated += 1`, `total_fallbacks += 1`, 상태: `FALLBACK_QUEUE_FULL`.
          - 쿠키 유효 및 큐 여유 있음: 0-RTT 성공! `current_queue_len += 1`, `active_tfo_connections.add(conn_id)`, `total_0rtt_successes += 1`, `total_0rtt_bytes += data_bytes`.
            - 만약 백업 키로 수락된 경우: 클라이언트 캐시를 프라이머리 키로 갱신하고 상태는 `TFO_0RTT_SUCCESS_BACKUP_KEY`.
            - 프라이머리 키로 수락된 경우: 상태는 `TFO_0RTT_SUCCESS`.
   - `COMPLETE_HANDSHAKE`:
     - 파라미터: `conn_id`.
     - 동작: 해당 연결이 0-RTT 활성 큐에 존재하면 제거하고 `current_queue_len = max(0, current_queue_len - 1)`, 상태: `HANDSHAKE_COMPLETED_TFO`. 일반 연결이면 상태: `HANDSHAKE_COMPLETED_REGULAR`.
   - `ROTATE_SERVER_KEY`:
     - 파라미터: `new_key`.
     - 동작: `server_backup_key = server_primary_key`, `server_primary_key = new_key`. 상태: `KEY_ROTATED`.
   - `CLIENT_PROBE_RESTORE`:
     - 파라미터: `client_ip`, `probe_success` (불리언).
     - 동작: 프로브 성공(`probe_success == true`) 시 `tfo_disabled = false`, `blackhole_failures = 0`, 상태: `TFO_RESTORED`. 실패 시 상태: `TFO_STILL_DISABLED`.

---

## 📤 출력 형식 (Output Specification)

시뮬레이션 완료 후 최종 TFO 서브시스템 통계를 압축 JSON 문자열(`separators=(',', ':')`, `ensure_ascii=False`)로 표준 출력에 출력합니다:

```json
{
  "final_queue_len": 1,
  "tfo_disabled": false,
  "total_0rtt_successes": 2,
  "total_0rtt_bytes": 3072,
  "total_fallbacks": 0,
  "total_syn_floods_mitigated": 0,
  "client_cookie_cache": {
    "192.168.1.10": "1fc5e079561118f4"
  },
  "history": [
    {
      "epoch": 1,
      "event": "COOKIE_REQUEST",
      "status": "COOKIE_ISSUED",
      "current_queue_len": 0,
      "tfo_disabled": false,
      "blackhole_failures": 0,
      "detail": "Cookie 1fc5e079561118f4 issued to 192.168.1.10"
    }
  ]
}
```

---

## 🎯 채점 기준 및 제약 조건

1. 정확성 100%: 8개 모든 테스트케이스의 수치 및 상태 플래그가 완벽히 일치해야 합니다.
2. HMAC-SHA256 기반의 16자리 hex 쿠키 생성 규격을 준수해야 합니다.
3. Windows 환경에서의 UTF-8 인코딩 처리를 준수해야 합니다.
