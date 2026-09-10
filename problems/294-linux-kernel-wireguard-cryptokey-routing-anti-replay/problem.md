# Problem #294: Linux Kernel WireGuard Cryptokey Routing & Anti-Replay Sliding Window

## 1. 개요 및 배경 (Overview & Background)

IPsec과 OpenVPN 같은 기존 VPN 프로토콜은 방대한 설정, 복잡한 보안 연결(SA/SP), 그리고 커널 네트워크 라우팅 테이블과 암호화 계층이 분리되어 있어 설정 오류와 성능 저하, 심각한 보안 홀을 초래했습니다.

리눅스 커널 5.6에 공식 병합된 **WireGuard**(`drivers/net/wireguard`)는 "암호화와 라우팅의 완전한 융합"을 목표로 설계된 차세대 고성능 보안 터널링 프로토콜입니다.
WireGuard의 핵심 혁신은 크게 세 가지로 요약됩니다:

1. **암호키 라우팅 (Cryptokey Routing)**:
   - 각 피어(Peer)는 고유한 공개키(Public Key)와 해당 피어가 소유할 수 있는 IP 서브넷 목록인 `AllowedIPs`를 가집니다.
   - **송신(TX)**: 커널은 목적지 IP에 대해 모든 피어의 `AllowedIPs`를 대상으로 최장 접두사 일치(Longest Prefix Match, LPM)를 수행하여 전송할 피어를 결정하고 암호화합니다.
   - **수신(RX)**: 패킷 복호화 후 내부 출발지 IP(Inner Source IP)가 해당 피어의 `AllowedIPs`에 속하지 않는다면, 즉각 스푸핑 공격(`CRYPT_KEY_ROUTING_SPOOFED_SRC`)으로 간주하여 커널 내부에서 즉시 폐기(Drop)합니다.

2. **안티 리플레이 슬라이딩 윈도우 (Anti-Replay Sliding Window)**:
   - 네트워크 상에서 암호화된 유효 패킷을 도청하여 재전송하는 리플레이 공격을 방어하기 위해, 각 패킷마다 64비트 단조 증가 카운터(`counter`)를 부여합니다.
   - 수신측은 64비트 크기의 슬라이딩 비트맵 윈도우(`rx_window_bitmap`)와 현재까지 수신한 최대 카운터(`rx_max_counter`)를 유지합니다.
   - 이미 수신된 카운터는 비트 검사로 즉각 차단(`REPLAY_ATTACK_DUPLICATE`)하며, 윈도우 범위를 벗어난 오래된 패킷은 지연 공격(`COUNTER_TOO_OLD`)으로 차단합니다.

3. **무상태성 엔드포인트 동적 로밍 (Dynamic Endpoint Roaming)**:
   - 모바일 기기가 Wi-Fi에서 5G LTE로 이동하면서 공인 IP가 변경되더라도, 유효한 암호화 서명이 검증된 패킷이 도착하면 피어의 외부 엔드포인트(`endpoint`)를 자동으로 갱신합니다.

```
+-------------------------------------------------------------------------------+
|                       WireGuard Cryptokey Routing & Anti-Replay                |
+-------------------------------------------------------------------------------+
  [ Inbound Wire Packet ] (UDP :51820)
            |
    [ Session Lookup ] ---> Matched Peer P
            |
    [ Anti-Replay Check ]
        - Counter <= 0?  --> Drop (ZERO_COUNTER)
        - Counter > Max? --> Slide Window, Accept & Mark
        - Max - Counter >= 64? --> Drop (COUNTER_TOO_OLD)
        - Bit already set?    --> Drop (REPLAY_ATTACK_DUPLICATE)
            |
    [ Decrypt Inner Packet ]
            |
    [ Cryptokey Routing Check ]
        - Inner Src IP in P.AllowedIPs?
              |-- NO  --> Drop (CRYPT_KEY_ROUTING_SPOOFED_SRC)
              \-- YES --> [ Roaming Check ] -> Update P.Endpoint
                             v
                    [ Upper IP Stack ]
```

이 문제에서는 리눅스 커널의 WireGuard 드라이버 엔진을 정밀 시뮬레이션하여, 암호키 라우팅, 슬라이딩 윈도우 리플레이 방어, 엔드포인트 로밍, 세션 리키(Rekey) 상태 머신을 구현합니다.

---

## 2. 입출력 규격 (Input & Output Specification)

### 입력 형식 (Standard Input)
표준 입력(stdin)으로 JSON 객체가 주어집니다.
```json
{
  "config": {
    "replay_window_size": 64,
    "rekey_after_time_s": 120.0,
    "rekey_after_packets": 500,
    "reject_after_time_s": 180.0
  },
  "peers": [
    {
      "peer_id": "peer_frankfurt",
      "public_key": "pk_fra",
      "allowed_ips": ["10.0.1.0/24"],
      "endpoint": "198.51.100.10:51820"
    }
  ],
  "events": [
    {
      "type": "HANDSHAKE",
      "time_s": 0.0,
      "peer_id": "peer_frankfurt",
      "session_id": "sess_fra_01"
    },
    {
      "type": "TX",
      "time_s": 1.0,
      "dst_ip": "10.0.1.10",
      "payload_len": 1420
    },
    {
      "type": "RX",
      "time_s": 2.0,
      "src_endpoint": "198.51.100.10:51820",
      "inner_src_ip": "10.0.1.10",
      "inner_dst_ip": "10.0.2.1",
      "counter": 1,
      "session_id": "sess_fra_01"
    }
  ]
}
```

- `config`:
  - `replay_window_size` (int, 기본값 64): 슬라이딩 윈도우 비트맵 크기.
  - `rekey_after_time_s` (float, 기본값 120.0): 세션 시작 후 리키 권장 시간(초).
  - `rekey_after_packets` (int, 기본값 500): 송신 패킷 수 리키 권장 임계치.
  - `reject_after_time_s` (float, 기본값 180.0): 세션 시작 후 패킷 거부 만료 시간(초).
- `peers`: 등록된 피어 목록.
  - `peer_id`, `public_key`, `allowed_ips` (CIDR 배열), `endpoint` (IP:Port).
- `events`: 시간순 이벤트 목록.
  - `type`: `"HANDSHAKE"`, `"TX"`, `"RX"`.

### 처리 규칙 (Processing Rules)

1. **핸드셰이크 (`HANDSHAKE`)**:
   - 지정된 피어의 `active_session_id`, `session_start_time`을 갱신합니다.
   - `tx_counter = 0`, `rx_max_counter = 0`, `rx_window_bitmap = 0`으로 리셋합니다.
   - 피어의 `rekey_count += 1`, 엔진 통계 `rekey_handshakes += 1`.

2. **송신 처리 (`TX`)**:
   - `dst_ip`에 대해 모든 피어의 `allowed_ips` CIDR 네트워크 중 **최장 접두사 일치(Longest Prefix Match, LPM)**를 수행합니다. (접두사 길이가 같으면 `peer_id` 사전순 우선)
   - 매칭 피어가 없거나 활성 세션이 없으면 `dropped_unroutable += 1`.
   - 세션 경과 시간 `(time_s - session_start_time) > reject_after_time_s`이면 세션 만료로 드롭 (`dropped_unroutable += 1`).
   - 정상이면 `peer.tx_counter += 1`, `peer.tx_packets += 1`, `tx_forwarded += 1`.
   - `tx_counter >= rekey_after_packets` 또는 경과 시간 $\ge$ `rekey_after_time_s`이면 이벤트에 `rekey_required = true`를 마킹합니다.

3. **수신 처리 (`RX`)**:
   - `session_id` 또는 `src_endpoint`로 피어를 식별합니다. 피어를 찾을 수 없으면 `dropped_unroutable += 1`.
   - **엔드포인트 로밍**: 수신 `src_endpoint`가 피어의 기존 `endpoint`와 다르면 피어의 엔드포인트를 수신된 주소로 즉시 갱신하고 `endpoint_roaming_updates += 1`.
   - **암호키 라우팅 검사**: `inner_src_ip`가 해당 피어의 `allowed_networks` 중 어디에도 포함되지 않으면 스푸핑으로 판정, `dropped_spoofed_src += 1`.
   - **안티 리플레이 슬라이딩 윈도우 검사**:
     - `counter <= 0`: 드롭 (`dropped_counter_too_old += 1`).
     - `counter > rx_max_counter`:
       - `diff = counter - rx_max_counter`
       - `diff < replay_window_size`이면 비트맵을 `diff`만큼 좌측 시프트(`<< diff`)하고 최하위 비트를 1로 설정 (`| 1`).
       - `diff >= replay_window_size`이면 비트맵을 `1`로 초기화.
       - `rx_max_counter = counter`로 갱신.
     - `counter <= rx_max_counter`:
       - `diff = rx_max_counter - counter`
       - `diff >= replay_window_size`이면 너무 오래된 패킷: 드롭 (`dropped_counter_too_old += 1`).
       - `(rx_window_bitmap & (1 << diff)) != 0`이면 이미 수신된 중복 패킷: 드롭 (`dropped_replay_duplicate += 1`).
       - 정상이면 비트맵에 해당 위치 비트 설정 (`rx_window_bitmap |= (1 << diff)`).
   - 모든 검사를 통과하면 `peer.rx_packets += 1`, `rx_accepted += 1`.

4. **상태 판정 (`status`)**:
   - `dropped_replay_duplicate > 0`: `"SECURITY_INCIDENT_REPLAY"`, 이상 항목에 `"REPLAY_ATTACK_DETECTED"` 추가.
   - `dropped_spoofed_src > 0`: `"SECURITY_INCIDENT_SPOOF"` (리플레이가 없을 때), 이상 항목에 `"CRYPTOKEY_ROUTING_SPOOF_ATTEMPT"` 추가.
   - 정상: `"SECURE_OPTIMAL"`.

### 출력 형식 (Standard Output)
단일 행의 표준 JSON 형식으로 출력합니다.
```json
{
  "metrics": {
    "tx_forwarded": 2,
    "rx_accepted": 3,
    "dropped_unroutable": 0,
    "dropped_spoofed_src": 0,
    "dropped_replay_duplicate": 0,
    "dropped_counter_too_old": 0,
    "rekey_handshakes": 1,
    "endpoint_roaming_updates": 0
  },
  "peer_summaries": {
    "peer_frankfurt": {
      "current_endpoint": "198.51.100.10:51820",
      "active_session_id": "sess_fra_01",
      "tx_packets": 2,
      "rx_packets": 3,
      "rx_max_counter": 3,
      "rekey_count": 1
    }
  },
  "diagnostics": {
    "status": "SECURE_OPTIMAL",
    "anomalies": []
  },
  "event_log_sample": []
}
```

---

## 3. 제약 사항 (Constraints)
- `events` 길이: $1 \le N \le 10,000$
- `peers` 수: $1 \le P \le 50$
- `replay_window_size`: 64 (표준 리눅스 커널 비트맵 크기)
- Python 3 표준 라이브러리만 사용합니다 (`json`, `sys`, `ipaddress`).
