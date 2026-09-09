# 웹소켓 백프레셔와 송신 버퍼 하이/로우 워터마크 (WebSocket Backpressure & Buffer Watermark)

## 문제 설명

실시간 가상화폐 거래소, 주식 시세 중계기, 대규모 채팅 서버는 **초당 수만~수십만 건의 메시지를 수만 명의 사용자에게 웹소켓(WebSocket)**으로 브로드캐스팅합니다.

이때 서버 아키텍처에서 가장 치명적인 문제는 바로 **"느린 수신자(Slow Consumer)의 저주"**입니다:
- 기가 인터넷을 쓰는 빠른 사용자는 서버가 보내는 메시지를 즉시 소모(Drain)합니다.
- 하지만 지하철이나 터널을 지나며 무선 통신이 불안정한 3G 모바일 사용자는 초당 수 KB도 채 받지 못합니다.

서버가 모든 클라이언트를 대상으로 단순 루프를 돌며 무지성으로 메시지를 전송(`session.sendMessage()`)하면:
1. 느린 사용자의 스마트폰 TCP 수신 버퍼가 가득 차면서 TCP 수신 윈도우가 0이 됩니다 (`rwnd = 0`).
2. 서버의 커널 소켓 송신 버퍼(`SO_SNDBUF`)가 꽉 차서 더 이상 네트워크 패킷을 전송할 수 없게 됩니다.
3. 전송 대기 중인 메시지들이 **서버 애플리케이션 메모리(Netty 송신 큐, JVM 힙 메모리)에 수십만 개씩 적체**됩니다.
4. 결국 거북이 사용자 몇 명 때문에 서버 전체 메모리가 수십 GB로 폭증하여 **OOM Killer에 의해 거래소 서버 전체가 다운**되고 수만 명의 모든 연결이 끊어지는 대참사가 발생합니다.

고성능 네트워크 엔진(Netty 등)은 이 문제를 해결하기 위해 **채널 버퍼 워터마크(Buffer Watermark)**와 **백프레셔(Backpressure) 정책**을 사용합니다.

당신은 웹소켓 서버의 클라이언트별 송신 버퍼 관리 및 백프레셔 엔진을 시뮬레이션해야 합니다.

---

## 시뮬레이션 규칙

### 1. 하이/로우 워터마크와 히스테리시스 (Hysteresis)
각 클라이언트 채널은 송신 버퍼(`buffer_bytes`)와 쓰기 가능 여부 플래그(`is_writable`, 초기값 `true`)를 가집니다:
- **하이 워터마크 도달**:
  - `buffer_bytes > high_watermark`가 되는 순간, `is_writable = false`로 전이됩니다. (서버는 백프레셔를 감지)
- **로우 워터마크 복구**:
  - 클라이언트가 데이터를 읽어가서 `buffer_bytes < low_watermark`가 되는 순간, `is_writable = true`로 복구됩니다.
- **히스테리시스 구간 (`low <= buffer <= high`)**:
  - 기존 상태를 그대로 유지합니다. (경계선 부근에서 상태가 무한 진동하는 것을 방지)

### 2. 백프레셔 4대 정책 및 오버플로우 처리
새 메시지(크기 `size`)를 클라이언트 버퍼에 추가하려 할 때, `buffer_bytes + size > max_capacity`인 경우 서버는 설정된 정책(`policy`)에 따라 처리합니다:

1. **`DISCONNECT` (느린 소비자 강제 퇴출 - 기본값)**:
   - 서버 메모리 보호를 위해 해당 클라이언트를 즉시 강제 연결 종료(`CLIENT_EVICTED reason=BUFFER_OVERFLOW`)합니다.
   - 클라이언트 상태는 `DISCONNECTED`가 되고, 버퍼 큐는 전량 폐기됩니다.
2. **`DROP_LATEST` (새 데이터 드롭)**:
   - 새 메시지를 조용히 폐기(`SEND_DROPPED reason=POLICY_DROP`)하고 `dropped_msgs += 1`을 기록합니다.
3. **`DROP_OLDEST` (오래된 데이터 드롭)**:
   - 새 메시지가 들어갈 공간이 생길 때까지 버퍼 큐 앞단(가장 오래된 메시지)을 차례로 꺼내 폐기(`dropped_msgs += 1`)한 뒤, 새 메시지를 큐에 추가합니다.
4. **`CONFLATE` (최신 키 데이터 덮어쓰기)**:
   - 메시지에 `key`(예: `BTC-USDT`)가 지정되어 있고, 큐 안에 이미 동일한 `key`를 가진 메시지가 대기 중이라면:
     - 큐 크기 순서를 바꾸지 않고 **해당 메시지 자리를 새 메시지로 인플레이스 교체(In-place Replace)**합니다. (`conflated_msgs += 1`)
     - 버퍼 크기는 `delta = new_size - old_size`만큼 증감합니다.
   - 만약 큐에 동일한 `key`가 없거나 `key`가 없다면, `DROP_OLDEST`와 동일하게 오래된 데이터를 비우고 새 메시지를 넣습니다.

### 3. 클라이언트 데이터 소모 (`DRAIN`)
- 클라이언트가 네트워크를 통해 최대 `bytes`만큼 데이터를 읽어갑니다.
- 버퍼 큐의 맨 앞(FIFO)부터 메시지를 소모하며, 완전히 읽힌 메시지는 큐에서 제거되고 `delivered_msgs += 1`이 됩니다.
- 부분적으로 읽힌 메시지는 잔여 크기만 큐에 남습니다.
- 배수 후 `buffer_bytes < low_watermark`가 되면 `is_writable = true`로 복구됩니다.

---

## 명령어 명세

모든 명령어는 표준 입력(stdin)으로 주어지며, 인자는 `key=value` 형태 또는 공백 구분 위치 인자를 지원합니다.

1. **`CONFIG high_watermark=<int> low_watermark=<int> max_capacity=<int> policy=<str>`**
   - 서버 파라미터를 설정합니다. (기본값: `high=65536, low=32768, max=131072, policy=DISCONNECT`)
   - 정책 종류: `DISCONNECT`, `CONFLATE`, `DROP_OLDEST`, `DROP_LATEST`
   - 출력: `CONFIG_OK high_watermark=<H> low_watermark=<L> max_capacity=<M> policy=<P>`

2. **`CONNECT <client_id>`**
   - 클라이언트를 서버에 연결합니다. (이미 존재하던 클라이언트라면 버퍼를 비우고 재연결)
   - 출력: `CONNECT_OK client_id=<client_id>`

3. **`DISCONNECT <client_id>`**
   - 클라이언트 연결을 수동 종료합니다.
   - 출력: `DISCONNECT_OK client_id=<client_id>`

4. **`SEND client_id=<id> msg_id=<mid> size=<int> [key=<str>]`**
   - 특정 클라이언트에게 메시지를 송신 큐에 넣습니다.
   - 출력 (상황별):
     - 정상 적재: `SEND_OK client_id=<id> msg_id=<mid> buffer_bytes=<B> writable=<true|false>`
     - 드롭: `SEND_DROPPED client_id=<id> msg_id=<mid> reason=POLICY_DROP`
     - 키 병합: `SEND_CONFLATED client_id=<id> msg_id=<mid> key=<key> buffer_bytes=<B>`
     - 강제 퇴출: `CLIENT_EVICTED client_id=<id> reason=BUFFER_OVERFLOW`
     - 미연결 실패: `SEND_FAIL client_id=<id> reason=NOT_CONNECTED`

5. **`BROADCAST msg_id=<mid> size=<int> [key=<str>]`**
   - 현재 연결된 모든 클라이언트에게 알파벳 순으로 메시지를 송신합니다.
   - 출력: `BROADCAST_OK msg_id=<mid> sent=<N> dropped=<D> conflated=<C> evicted=<E>`

6. **`DRAIN client_id=<id> bytes=<int>`**
   - 클라이언트가 버퍼에서 지정된 바이트만큼 데이터를 읽어갑니다.
   - 출력: `DRAIN_OK client_id=<id> drained_bytes=<D> remaining_bytes=<B> delivered=<M> writable=<true|false>`

7. **`STATUS <client_id>`**
   - 클라이언트 채널 상태를 덤프합니다.
   - 출력 형식:
     ```
     --- CLIENT_STATUS <client_id> ---
     STATE: <CONNECTED|DISCONNECTED>
     WRITABLE: <true|false>
     BUFFER_BYTES: <int>
     QUEUED_MSGS: <int>
     DELIVERED_MSGS: <int>
     DROPPED_MSGS: <int>
     CONFLATED_MSGS: <int>
     --- END_STATUS ---
     ```

8. **`RESET`**
   - 모든 설정을 초기화하고 모든 클라이언트를 삭제합니다.
   - 출력: `RESET_OK`

---

## 입출력 예시

### 예시 입력
```
CONFIG high_watermark=65536 low_watermark=32768 max_capacity=131072 policy=DISCONNECT
CONNECT c1
SEND c1 msg_id=m1 size=10240
STATUS c1
DRAIN c1 bytes=10240
STATUS c1
```

### 예시 출력
```
CONFIG_OK high_watermark=65536 low_watermark=32768 max_capacity=131072 policy=DISCONNECT
CONNECT_OK client_id=c1
SEND_OK client_id=c1 msg_id=m1 buffer_bytes=10240 writable=true
--- CLIENT_STATUS c1 ---
STATE: CONNECTED
WRITABLE: true
BUFFER_BYTES: 10240
QUEUED_MSGS: 1
DELIVERED_MSGS: 0
DROPPED_MSGS: 0
CONFLATED_MSGS: 0
--- END_STATUS ---
DRAIN_OK client_id=c1 drained_bytes=10240 remaining_bytes=0 delivered=1 writable=true
--- CLIENT_STATUS c1 ---
STATE: CONNECTED
WRITABLE: true
BUFFER_BYTES: 0
QUEUED_MSGS: 0
DELIVERED_MSGS: 1
DROPPED_MSGS: 0
CONFLATED_MSGS: 0
--- END_STATUS ---
```
