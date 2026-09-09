# [파드를 재배포했을 뿐인데 왜 클라이언트의 진행 중이던 결제 스트림 1,000건이 강제 폭사해요?!: HTTP/2 GOAWAY 프레임과 gRPC Graceful Connection Drain]

## 1. 장애 시나리오: "쿠버네티스 롤링 배포가 시작되자마자 쏟아진 503 UNAVAILABLE과 결제 실패 참사"

MSA(마이크로서비스 아키텍처) 기반의 이커머스 플랫폼에서, 프론트엔드 API 게이트웨이와 백엔드 결제 서비스 간의 통신에 고성능 **gRPC(HTTP/2 기반)**를 도입했습니다.
HTTP/2의 강력한 단일 TCP 연결 다중화(Multiplexing) 덕분에 핸드셰이크 오버헤드가 사라지고 지연 시간이 획기적으로 줄었습니다.

하지만 새로운 버전을 쿠버네티스(k8s) 클러스터에 롤링 업데이트(`kubectl rollout restart`)로 무중단 배포하는 순간, 전사 모니터링 대시보드에 붉은 경고등이 켜졌습니다:
```text
io.grpc.StatusRuntimeException: UNAVAILABLE: io exception
Channel shutdown invoked, Connection reset by peer
StreamResetException: stream was reset: CANCEL / RST_STREAM
```

순식간에 1,000여 건의 결제 요청이 실패하고 유저들에게 `결제 처리 중 오류가 발생했습니다` 팝업이 노출되었습니다.

백엔드 개발자의 당황:
> "쿠버네티스가 파드를 1개씩 순차적으로 교체하는 롤링 배포(Rolling Update)를 썼는데 왜 무중단이 안 되고 진행 중이던 결제 스트림들이 모조리 터진 거죠?!"

원인은 **HTTP/2 장기 지속 TCP 연결과 비정상적인 강제 종료(Abrupt Close)**였습니다:
1. gRPC는 단 하나의 장기 지속 TCP 커넥션 위에서 수백~수천 개의 스트림(RPC 요청)을 동시에 주고받습니다.
2. 백엔드 파드가 `SIGTERM`을 받았을 때 단순하게 프로세스를 종료해 버리면, OS 커널이 해당 TCP 소켓을 즉시 닫거나 `RST`를 보냅니다.
3. 그 순간 **동일한 TCP 파이프 안에서 열심히 실행 중이던 수백 개의 인플라이트(In-flight) RPC 스트림이 일제히 증발**해 버립니다!
4. 클라이언트는 어떤 요청이 서버에서 처리되었고 어떤 요청이 버려졌는지 알 수 없어(멱등성 미보장) 함부로 재시도도 못 하고 503 에러를 뿜게 됩니다.

SRE 팀의 해결책:
> "파드가 종료될 때 소켓을 무턱대고 끊으면 안 됩니다! HTTP/2 표준 사양인 **2단계 GOAWAY 프레임 핸드셰이크**와 **Graceful Drain**을 구현하여, 새 스트림 진입을 차단하고 기존 처리 중인 스트림을 안전하게 완주시켜야 합니다!"

---

## 2. 시뮬레이션 사양 및 규칙

본 문제에서는 HTTP/2 표준(RFC 7540 Section 6.8) 및 gRPC의 **우아한 연결 드레인 (Graceful Connection Drain with 2-Step GOAWAY)** 메커니즘을 시뮬레이션합니다.

### (1) 네트워크 및 타이밍 모델
- 단방향 네트워크 지연: $OneWayLatency = RTT // 2$
- 클라이언트가 $t_{send}$에 스트림을 전송하면, 서버에는 $t_{arrive} = t_{send} + OneWayLatency$에 도착합니다.
- 서버가 스트림 처리를 시작하면 소요 시간 $duration$ 후 $t_{finish} = t_{arrive} + duration$에 완료됩니다.
- 서버의 셧다운 시작 시점(`shutdown_start_time_ms`)에 종료 시그널이 발동됩니다.

### (2) 종료 모드별 동작 규칙

#### 1) `ABRUPT_CLOSE` (단순 강제 종료)
- 서버는 `shutdown_start_time_ms` 시점에 즉시 소켓을 강제 차단합니다.
- $t_{finish} \le shutdown\_start\_time\_ms$로 이미 완전히 끝난 스트림만 정상 처리됩니다 (`COMPLETED += 1`).
- 그 시점에 서버에서 아직 처리 중이던 모든 스트림은 즉시 중단 및 파괴됩니다 (`DROPPED += 1`, `ABRUPT_RESETS += 1`).
- 차단 이후 서버에 도착한 패킷도 모두 유실됩니다 (`DROPPED += 1`).

#### 2) `GRACEFUL_GOAWAY` (gRPC 표준 우아한 드레인)
- **1단계 (초기 GOAWAY 전송)**:
  - $T_{sig} = shutdown\_start\_time\_ms$에 서버는 최대 스트림 ID($2^{31}-1$)를 담은 첫 번째 GOAWAY를 클라이언트로 보냅니다.
  - 클라이언트는 $T_{client\_goaway} = T_{sig} + OneWayLatency$ 시점에 이를 수신합니다.
  - 이 시점 이후($t_{send} \ge T_{client\_goaway}$) 클라이언트는 본 연결로 새 스트림을 보내지 않고 다른 건강한 파드로 안전하게 우회합니다 (`SAFELY_RETRIED += 1`).
- **2단계 (1 RTT 대기 및 최종 GOAWAY 확정)**:
  - 서버는 이미 네트워크 파이프라인에 실려 날아오고 있는 인플라이트 요청을 수신하기 위해 1 RTT 동안 대기합니다 ($T_{second\_goaway} = T_{sig} + RTT$).
  - $T_{second\_goaway}$ 시점까지 서버에 도착한 가장 큰 스트림 ID를 $LastStreamId$로 확정하여 최종 GOAWAY를 발행합니다.
- **3단계 (기존 스트림 완주 및 드레인 한도)**:
  - $LastStreamId$ 이하로 수신된 스트림들은 처리가 진행됩니다.
  - 서버는 최대 $T_{hard\_deadline} = T_{sig} + drain\_timeout\_ms$까지 기존 스트림들이 끝나길 기다립니다.
  - $t_{finish} \le T_{hard\_deadline}$ 내에 완료된 스트림은 정상 종료됩니다 (`COMPLETED += 1`).
  - 드레인 한도를 초과하여 미처 끝나지 못한 극단적 슬로우 쿼리는 폐기됩니다 (`DROPPED += 1`).
  - 클라이언트가 첫 GOAWAY 수신 전에 보냈으나 $T_{second\_goaway}$ 이후에 도착하여 $LastStreamId$를 초과한 요청은, 클라이언트가 "서버가 아예 손도 대지 않았다"는 사실을 100% 확신할 수 있으므로 다른 파드로 안전하게 투명 재시도합니다 (`SAFELY_RETRIED += 1`).

---

## 3. 입력 형식

- 첫째 줄에 4개의 파라미터가 공백으로 주어집니다:
  - `mode`: `"ABRUPT_CLOSE"` 또는 `"GRACEFUL_GOAWAY"`
  - `drain_timeout_ms`: 드레인 허용 시간 ($100 \le ms \le 60,000$)
  - `rtt_ms`: 네트워크 RTT ($2 \le ms \le 1,000$)
  - `shutdown_start_time_ms`: 서버 셧다운 시작 시점 ($0 \le ms \le 1,000,000$)
- 둘째 줄에 스트림 개수 $N$ ($0 \le N \le 1,000$)이 주어집니다.
- 셋째 줄부터 $N$개 줄에 걸쳐 각 스트림 정보가 공백으로 구분되어 주어집니다:
  - `stream_id client_send_time_ms duration_ms` (단, $stream\_id$는 홀수 양의 정수)

## 4. 출력 형식

- 모든 시뮬레이션이 종료된 후 다음 형식으로 한 줄에 출력합니다:
  - `COMPLETED: <수> SAFELY_RETRIED: <수> DROPPED: <수> ABRUPT_RESETS: <수>`

---

## 5. 입출력 예제

### 예제 1 (`ABRUPT_CLOSE`: 진행 중이던 스트림이 강제 폭사)
#### 입력
```text
ABRUPT_CLOSE 2000 20 1000
4
1 100 200
3 800 500
5 1005 300
7 1050 300
```
#### 출력
```text
COMPLETED: 1 SAFELY_RETRIED: 0 DROPPED: 3 ABRUPT_RESETS: 1
```

### 예제 2 (`GRACEFUL_GOAWAY`: 기존 스트림 완주 및 안전한 재시도)
#### 입력
```text
GRACEFUL_GOAWAY 2000 20 1000
4
1 100 200
3 800 500
5 1005 300
7 1050 300
```
#### 출력
```text
COMPLETED: 3 SAFELY_RETRIED: 1 DROPPED: 0 ABRUPT_RESETS: 0
```
**비교 설명**:
- `ABRUPT_CLOSE`에서는 1000ms 시점에 소켓이 강제 단절되어, 처리 중이던 Stream 3(800ms 발송, 서버 도착 810ms, 완료 예정 1310ms)이 중도에 파괴되고(`ABRUPT_RESETS: 1`), 이후 도착한 스트림도 다 유실되었습니다.
- 반면 `GRACEFUL_GOAWAY`에서는 1단계 GOAWAY 및 1 RTT(20ms) 대기를 거쳐 Stream 1, 3, 5가 드레인 한도(3000ms) 내에 무사히 완주(`COMPLETED: 3`)되었고, 클라이언트가 GOAWAY를 인지한 뒤 발송된 Stream 7은 다른 파드로 안전하게 투명 재시도(`SAFELY_RETRIED: 1`)되어 유실률 0%를 달성했습니다!
