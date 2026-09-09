# [gRPC와 HTTP/2 GOAWAY: 우아한 연결 드레인(Graceful Connection Drain)과 무중단 배포]

## 1. HTTP/1.1 vs HTTP/2 연결 수명주기의 결정적 차이

전통적인 HTTP/1.1 REST 통신에서는 클라이언트가 매 요청마다 연결을 새로 맺거나, `Connection: keep-alive` 상태에서 파드가 죽더라도 로드밸런서가 즉시 다음 요청을 다른 파드로 넘기면 되었습니다. (단일 요청-단일 응답 모델)

하지만 **gRPC가 기반을 두고 있는 HTTP/2**는 전혀 다릅니다:
- **단일 장기 지속 TCP 연결 (Long-Lived Multiplexed Connection)**:
  - 클라이언트는 서버와 단 한 번 TCP 3-Way Handshake 및 TLS 협상을 맺고, 이 연결을 **수 시간~수일 동안 끊지 않고 영구 유지**합니다.
  - 모든 RPC 메서드 호출은 이 단일 TCP 스트림 위에서 가상의 양방향 바이너리 프레임(Stream)으로 다중화되어 날아갑니다.

이로 인해 쿠버네티스 환경에서 파드를 롤링 업데이트할 때 치명적인 문제가 발생합니다:
- 파드가 종료될 때 소켓을 단순 `close()` 해버리면, **해당 커넥션을 타고 흐르던 수백~수천 개의 진행 중인 RPC가 한꺼번에 소켓 리셋(RST_STREAM / ECONNRESET)을 맞고 공중 분해**됩니다!

---

## 2. HTTP/2 RFC 7540 사양: GOAWAY 프레임

HTTP/2 표준(RFC 7540 Section 6.8)은 이 문제를 우아하게 해결하기 위해 **`GOAWAY` 프레임**을 정의했습니다.

```text
+-----------------------------------------------+
| R |                  Last-Stream-ID (31)      |
+-----------------------------------------------+
|                  Error Code (32)              |
+-----------------------------------------------+
|                  Additional Debug Data (*)    |
+-----------------------------------------------+
```

### GOAWAY 프레임의 2대 핵심 역할:
1. **새로운 스트림 생성 금지**:
   - 클라이언트는 GOAWAY를 수신한 즉시, 해당 연결에서 더 이상 새로운 스트림을 생성해서는 안 됩니다.
2. **처리 보장 한계선 통보 (`Last-Stream-ID`)**:
   - 서버는 자신이 처리했거나 처리할 예정인 마지막 스트림 ID(`Last-Stream-ID`)를 클라이언트에 명시합니다.
   - **`Stream ID <= Last-Stream-ID`**: 서버가 책임지고 완료하여 응답을 줄 것이므로 클라이언트는 기다립니다.
   - **`Stream ID > Last-Stream-ID`**: 서버가 손도 대지 않았음이 100% 보장되므로, 클라이언트는 멱등성 걱정 없이 **다른 건강한 서버로 투명하게 재시도(Transparent Retry)**할 수 있습니다!

---

## 3. 왜 '2단계 GOAWAY (2-Phase GOAWAY)'가 필요한가?

단 한 번의 GOAWAY 전송만으로는 레이스 컨디션을 완벽히 방지할 수 없습니다.

### 단일 GOAWAY의 레이스 컨디션 함정:
1. 서버가 파드 종료 시점에 현재까지 받은 마지막 스트림이 5번이라고 해서 `GOAWAY(LastStreamId = 5)`를 쏩니다.
2. 그런데 하필 서버가 GOAWAY를 쏘기 1ms 전에, 클라이언트가 이미 7번 스트림 패킷을 유선망에 실어 보냈습니다!
3. 네트워크 상에서 GOAWAY 패킷과 7번 스트림 패킷이 서로 엇갈려 지나갑니다.
4. 클라이언트 입장에서는 GOAWAY를 받기 전에 정당하게 보낸 요청인데, 서버가 이미 `LastStreamId = 5`를 선언해 버렸기 때문에 7번 스트림의 운명이 불투명해집니다.

### 완벽한 해결책: 2단계 GOAWAY 핸드셰이크
Envoy, gRPC, Nginx 등 프로덕션 레벨의 고성능 프록시는 이 엇갈림을 해결하기 위해 **2-Step GOAWAY**를 사용합니다:

```text
[클라이언트]                                              [gRPC 서버 (SIGTERM 수신!)]
     │                                                               │
     │ <──── 1단계: GOAWAY (LastStreamId = 2^31 - 1) ──────────────── │ (새 스트림 진입 차단!)
     │       (클라이언트는 새 요청을 다른 파드로 우회 시작)                   │
     │                                                               │
     │       [1 RTT 대기: 유선망에 떠돌던 미완료 스트림 모두 수신 대기]       │
     │                                                               │
     │ <──── 2단계: 최종 GOAWAY (LastStreamId = 실제 수신된 최대 ID) ─── │ (최종 경계 확정!)
     │                                                               │
     │       [기존 수신된 스트림들 완주 (Graceful Drain)]                     │
     │                                                               │
     │ ─────────────────────── 모든 작업 완료 후 연결 종료 ───────────► │ (0-Downtime!)
```

1. **Step 1**: 가능한 가장 큰 스트림 ID인 $2^{31}-1$로 1차 GOAWAY를 보냅니다. 클라이언트는 즉시 새 스트림 생성을 멈춥니다.
2. **Step 2**: 서버는 최소 1 RTT(보통 PING 프레임 왕복)를 기다려 이미 네트워크를 타고 오고 있던 패킷들을 마저 수신합니다.
3. **Step 3**: 실제 수신된 최대 ID를 담은 2차 GOAWAY를 보냅니다.
4. **Step 4**: 수신된 스트림들이 모두 완료될 때까지 대기(`Graceful Drain`)한 뒤 연결을 정상 종료합니다.

---

## 4. 실무 프로덕션 적용 가이드 (Kubernetes & gRPC)

1. **쿠버네티스 preStop Hook과 Graceful Stop**:
   ```yaml
   lifecycle:
     preStop:
       exec:
         command: ["/bin/sleep", "5"] # 서비스 엔드포인트에서 제외될 때까지 완충
   ```
2. **gRPC Server `gracefulStop()` API 호출**:
   - Java: `server.shutdown().awaitTermination(30, TimeUnit.SECONDS);`
   - Go: `grpcServer.GracefulStop()`
   - 내부적으로 진행 중인 모든 RPC가 완료될 때까지 기다린 후 소켓을 닫습니다.
3. **클라이언트 사이드 재시도 정책 (Service Config)**:
   - 클라이언트는 `UNAVAILABLE` 상태 코드에 대해 투명 재시도(Transparent Retry)를 기본 활성화하여, 엇갈린 스트림을 무지연 복구하도록 구성합니다.
