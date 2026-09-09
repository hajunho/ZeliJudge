# #150 웹소켓 연결이 1분마다 뚝뚝 끊겨요?!: L4/L7 방화벽의 침묵의 유휴 커넥션 드롭(Silent Drop)과 WebSocket Ping/Pong 하트비트 vs TCP Keep-Alive (WebSocket Ping/Pong Heartbeat vs Silent Connection Drop)

## 1. 실무 장애 시나리오: "가만히 놔뒀을 뿐인데 매수 주문만 누르면 웹소켓이 터져요?!"

실시간 암호화폐 거래소 '젤리익스체인지'의 프론트엔드/백엔드 개발팀은 사용자가 호가창을 켜두고 잠시 다른 탭을 보다가 돌아왔을 때, 매수 주문 버튼을 누르면 화면이 멈추고 주문이 실패한다는 치명적인 CS 제보를 받았습니다:

```
WebSocket connection to 'wss://api.zeli.io/ws/order' failed: 
WebSocket is already in CLOSING or CLOSED state. (Code 1006 Abnormal Closure)
```

이상한 점은 **클라이언트 브라우저도, 백엔드 서버도 연결을 끊으라고 `close()`를 호출한 적이 없었다는 것**입니다.  
서버의 로그를 확인해 보니:
* 브라우저는 12:00:00부터 12:01:30까지 자신이 여전히 연결되어 있는 줄(`readyState === WebSocket.OPEN`) 알고 있었습니다.
* 그런데 12:01:30에 사용자가 매수 주문 버튼을 누르자마자, 즉시 `Connection Reset by Peer (RST)`가 날아오며 1006 비정상 종료가 터졌습니다.

분명 3-Way Handshake를 맺고 연결을 유지하고 있었는데, **아무런 FIN 패킷도 오가지 않은 상태에서 도대체 누가 연결을 끊어버린 것일까요?**

긴급 소집된 네트워크 엔지니어 지우 님이 참사의 원인을 짚어냈습니다:

> "여러분! 클라이언트와 백엔드 서버 사이에는 수많은 네트워크 중계 장비(AWS NAT Gateway, L4 로드밸런서, 기업 방화벽 등)가 있습니다!  
> 이 장비들은 메모리 관리를 위해 **연결 추적 테이블(Conntrack Table)**을 관리하는데, **60초 동안 양방향으로 패킷이 하나도 오가지 않으면 '죽은 연결'로 간주하고 테이블에서 해당 세션을 조용히 삭제(Silent Drop)**합니다!  
> 문제는 이 과정에서 **클라이언트나 서버 어느 쪽에도 FIN이나 RST 패킷을 날려주지 않는다는 점**입니다!  
> 양쪽 모두 연결이 살아있다고 착각하는 **좀비 커넥션(Zombie Connection)** 상태에 빠져 있다가, 유저가 90초 뒤 주문 패킷을 보내자 방화벽이 '너 누구야?'라며 그제서야 TCP RST를 날려 폭사시킨 겁니다!"

주니어 개발자 진우가 물었습니다:  
"그럼 OS 레벨의 `TCP Keep-Alive`를 켜면 해결되나요?"

> "안 됩니다! 리눅스 커널의 기본 `tcp_keepalive_time`은 무려 7200초(2시간)라 60초 유휴 타임아웃을 막지 못합니다. 게다가 AWS ALB나 Nginx 같은 **L7 리버스 프록시 환경에서는 TCP 연결이 프록시 경계에서 분리되므로 클라이언트의 TCP Keep-Alive가 백엔드까지 전달되지 못하고 흡수 소멸**합니다!  
> WebSocket 사양(RFC 6455)에 정의된 **애플리케이션 레벨 Ping/Pong 하트비트(Opcode 0x9 Ping / 0xA Pong)**를 써야 합니다!  
> 25초마다 경량 Ping 프레임을 주고받아 방화벽의 유휴 타이머를 계속 0초로 리셋하고, 회선이 단절되었을 때는 수초 내에 좀비 커넥션을 감지하여 안전하게 재연결(Reconnect)해야 합니다!"

Ping/Pong 하트비트를 적용하자, 1시간 동안 아무런 주문을 넣지 않아도 호가창 웹소켓은 100% 무중단으로 생존하였고 매수 주문은 즉시 성공했습니다.

---

## 2. 핵심 이론: 유휴 커넥션 드롭과 RFC 6455 Ping/Pong

### (1) L4 방화벽의 침묵의 유휴 커넥션 소각 (Silent Drop)
* NAT 게이트웨이 및 L4 방화벽은 유한한 메모리를 보호하기 위해 Conntrack Table 엔트리에 유휴 타임아웃(Idle Timeout, 보통 60초~350초)을 적용합니다.
* 트래픽이 없으면 아무런 알림(FIN/RST) 없이 조용히 매핑을 소거합니다.
* 양쪽 엔드포인트는 연결이 살아있다고 믿는 **좀비 커넥션(Zombie Connection)**에 빠지며, 이후 첫 패킷 전송 시 `TCP RST`를 받고 1006 에러로 즉사합니다.

### (2) TCP Keep-Alive의 한계
* **주기 문제**: 기본값이 7200초(2시간)로 방화벽 60초 만료를 방어하기에 너무 깁니다.
* **L7 프록시 차단**: Nginx, Envoy, ALB 등 L7 프록시는 TCP 연결을 프록시 기준으로 분리하므로, OS 레벨 Keep-Alive 패킷이 프록시 너머로 통과하지 못합니다.

### (3) RFC 6455 웹소켓 Ping / Pong 하트비트
* 웹소켓 제어 프레임 (Opcode `0x9`: Ping, `0xA`: Pong).
* L7 애플리케이션 계층에서 동작하므로 모든 프록시와 방화벽을 투명하게 통과합니다.
* 주기(예: 25초)마다 Ping을 날려 방화벽 Conntrack 유휴 타이머를 지속적으로 0초로 리셋합니다.
* 상대방 서버가 다운되거나 물리 회선이 뽑혔을 때 Pong 타임아웃으로 좀비 상태를 수초 내에 능동 감지하고 재연결을 트리거합니다.

---

## 3. 입출력 규격 및 요구사항

방화벽 유휴 타임아웃, 하트비트 설정(`mode`, `ping_interval_seconds`), 네트워크 프로필(`proxy_type`, 단절 시점) 및 사용자 메시지 이벤트 목록이 주어졌을 때, 방화벽의 Conntrack 소각 여부와 좀비 지속 시간, 사용자 메시지 전송 성공 여부를 시뮬레이션하고 최종 상태를 판정하는 엔진을 구현하세요.

### 입력 형식 (JSON)
```json
{
  "firewall_config": {
    "idle_timeout_seconds": 60.0
  },
  "heartbeat_config": {
    "mode": "NONE",
    "ping_interval_seconds": 25.0,
    "pong_timeout_seconds": 10.0,
    "max_missed_pongs": 2
  },
  "network_profile": {
    "proxy_type": "L7_REVERSE_PROXY",
    "network_severed_at_second": null
  },
  "user_events": [
    {"time_seconds": 10.0, "payload": "SUBSCRIBE_BTC_USDT"},
    {"time_seconds": 90.0, "payload": "BUY_MARKET_ORDER"}
  ]
}
```

* `heartbeat_config.mode`: `"NONE"`, `"TCP_KEEPALIVE"`, `"WEBSOCKET_PING_PONG"`
* `network_profile.proxy_type`: `"L7_REVERSE_PROXY"`, `"L4_TRANSPARENT"`

### 출력 형식 (JSON)
```json
{
  "summary": {
    "heartbeat_mode": "NONE",
    "firewall_idle_timeout_seconds": 60.0,
    "proxy_type": "L7_REVERSE_PROXY",
    "conntrack_alive_at_end": false,
    "client_connected_at_end": false,
    "silent_drop_occurred": true,
    "zombie_duration_seconds": 20.0,
    "user_messages_sent": 2,
    "user_messages_delivered": 1,
    "overall_verdict": "SILENT_DROP_DISASTER"
  }
}
```

### 판정 규칙 (`overall_verdict`)
* `silent_drop_occurred && mode == "NONE"`: `"SILENT_DROP_DISASTER"`
* `silent_drop_occurred && mode == "TCP_KEEPALIVE" && proxy_type == "L7_REVERSE_PROXY"`: `"TCP_KEEPALIVE_L7_PROXY_BYPASS_FAILURE"`
* `mode == "WEBSOCKET_PING_PONG" && messages_delivered == messages_sent && !silent_drop_occurred`: `"WEBSOCKET_PING_PONG_RESILIENT"`
* `!client_alive && network_severed_at is not None`: `"NETWORK_SEVERED_PROMPTLY_DETECTED"`
* 그 외: `"BALANCED_EXECUTION"`

---

## 4. 입출력 예시

### 예시 1: 하트비트 부재로 인한 유휴 침묵 소각 참사

#### 입력
```json
{
  "firewall_config": {"idle_timeout_seconds": 60.0},
  "heartbeat_config": {"mode": "NONE"},
  "network_profile": {"proxy_type": "L7_REVERSE_PROXY"},
  "user_events": [
    {"time_seconds": 10.0, "payload": "SUBSCRIBE_BTC_USDT"},
    {"time_seconds": 90.0, "payload": "BUY_MARKET_ORDER"}
  ]
}
```

#### 출력
```json
{
  "summary": {
    "heartbeat_mode": "NONE",
    "firewall_idle_timeout_seconds": 60.0,
    "proxy_type": "L7_REVERSE_PROXY",
    "conntrack_alive_at_end": false,
    "client_connected_at_end": false,
    "silent_drop_occurred": true,
    "zombie_duration_seconds": 20.0,
    "user_messages_sent": 2,
    "user_messages_delivered": 1,
    "overall_verdict": "SILENT_DROP_DISASTER"
  }
}
```

### 예시 2: WebSocket Ping/Pong 적용으로 100% 무중단 유지

#### 입력
```json
{
  "firewall_config": {"idle_timeout_seconds": 60.0},
  "heartbeat_config": {
    "mode": "WEBSOCKET_PING_PONG",
    "ping_interval_seconds": 25.0,
    "pong_timeout_seconds": 10.0,
    "max_missed_pongs": 2
  },
  "network_profile": {"proxy_type": "L7_REVERSE_PROXY"},
  "user_events": [
    {"time_seconds": 10.0, "payload": "SUBSCRIBE_BTC_USDT"},
    {"time_seconds": 90.0, "payload": "BUY_MARKET_ORDER"}
  ]
}
```

#### 출력
```json
{
  "summary": {
    "heartbeat_mode": "WEBSOCKET_PING_PONG",
    "firewall_idle_timeout_seconds": 60.0,
    "proxy_type": "L7_REVERSE_PROXY",
    "conntrack_alive_at_end": true,
    "client_connected_at_end": true,
    "silent_drop_occurred": false,
    "zombie_duration_seconds": 0.0,
    "user_messages_sent": 2,
    "user_messages_delivered": 2,
    "overall_verdict": "WEBSOCKET_PING_PONG_RESILIENT"
  }
}
```
