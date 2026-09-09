# 132. gRPC로 바꿨는데 왜 로드밸런서가 트래픽을 서버 1대에만 몰아줘요?!: HTTP/2 단일 TCP 스트림 다중화와 L4 vs L7 로드밸런서의 비극 & gRPC 클라이언트 사이드 부하 분산

## 문제 설명

이커머스 MSA 플랫폼의 주니어 백엔드 엔지니어 젤리(Zeli)는 마이크로서비스 간 통신 지연시간(Latency)을 획기적으로 줄이기 위해 기존의 HTTP/1.1 REST API를 Google의 초고속 바이너리 RPC 프레임워크인 **gRPC (HTTP/2 기반)**로 전면 전환했습니다.

쿠버네티스 클러스터에 결제 처리 백엔드 파드(`srv_1`, `srv_2`, `srv_3`) 3대를 띄우고, 그 앞단에 쿠버네티스 기본 L4 로드밸런서인 `ClusterIP Service`를 연결했습니다:

```
[주문 서비스 (Client App)]
           │
           │ (HTTP/2 단일 TCP 연결!)
           ▼
[쿠버네티스 L4 Service (ClusterIP)]
     │
     ├─── (모든 RPC 요청 100% 몰빵!) ────► [srv_1] (CPU 100%, 큐 포화 사망! 💥)
     │
     ├─────────────────────────────────► [srv_2] (CPU 0%, 노는 중... 💤)
     │
     └─────────────────────────────────► [srv_3] (CPU 0%, 노는 중... 💤)
```

*"기존 HTTP/1.1 REST 통신 때는 3대의 파드에 요청이 33%씩 칼같이 예쁘게 분산되었으니, gRPC로 바꿔도 똑같이 라운드로빈으로 분산되겠지?!"* 😎

하지만 부하 테스트를 시작하자마자 충격적인 일이 벌어졌습니다!  
**`srv_1` 혼자서 모든 RPC 요청을 뒤집어쓰고 CPU 100%를 찍으며 요청 거절(`REJECTED_OVERLOADED`) 에러를 뿜어냈고, 나머지 `srv_2`, `srv_3`은 CPU 0%로 완벽하게 놀고 있었던 것입니다!** 😱

---

### 원인: HTTP/2 단일 TCP 다중화와 L4의 "커넥션 핀닝(Connection Pinning)"

이 참사의 원인은 **HTTP/1.1과 HTTP/2의 연결 아키텍처 차이**와 **L4 로드밸런서의 동작 한계**가 결합되어 발생했습니다.

1. **HTTP/1.1의 동작 (L4에서 분산이 잘 되었던 이유)**:
   - 요청마다 새로운 TCP 연결을 맺거나 여러 개의 독립적인 TCP 소켓을 병렬로 운용했습니다.
   - L4 로드밸런서는 클라이언트가 새로운 TCP 3-Way Handshake(`SYN` 패킷)를 보낼 때마다 백엔드 서버를 라운드로빈으로 바꾸어 연결해 주므로 자연스럽게 부하가 분산되었습니다.

2. **HTTP/2 (gRPC)의 동작 (단일 TCP 다중화)**:
   - gRPC는 연결 맺기 비용(TCP 핸드셰이크 + TLS 핸드셰이크)을 줄이기 위해 **단 1개의 장기 지속 TCP 연결(Single Long-Lived TCP Connection)**을 맺습니다.
   - 그 후 수천, 수만 개의 RPC 호출은 이 단일 TCP 파이프라인 위에서 **독립적인 가상 스트림(Stream)**으로 다중화되어 전송됩니다.

3. **L4 로드밸런서의 비극**:
   - L4 로드밸런서(AWS NLB, K8s iptables/IPVS Service 등)는 오직 TCP 연결이 맺어지는 최초의 `SYN` 시점에만 대상을 결정합니다.
   - 클라이언트가 `srv_1`과 단 1개의 TCP 연결을 맺고 나면, 그 연결 내부에서 수만 건의 RPC 스트림이 쏟아져 들어와도 L4는 패킷의 L7 페이로드를 알지 못하므로 **무조건 처음에 맺어진 `srv_1`로만 패킷을 쏘아 보냅니다!**
   - 이로 인해 특정 파드 하나만 독박을 쓰고 과부하로 사망하는 **커넥션 핀닝(Connection Pinning)** 현상이 발생합니다.

---

### 세 가지 실무 구원 아키텍처

젤리는 gRPC 트래픽을 스트림 단위로 우아하게 분산하는 3가지 부하 분산 아키텍처를 시뮬레이션 엔진으로 검증하기로 했습니다:

1. **`L4_PROXY` (L4 프록시 방식)**:
   - 클라이언트별로 최초 TCP 연결 시 라운드로빈으로 백엔드를 1개 지정하고, 이후 모든 스트림을 해당 서버에 핀닝합니다.
   - 단, 서버 설정에 **`max_connection_age_ms`**가 지정되어 있는 경우, 해당 시간이 지나면 `GOAWAY` 프레임에 의해 기존 연결을 Graceful하게 닫고 새 TCP 연결을 맺으면서 다음 백엔드 서버로 순환 재연결(`L4_CONNECTION_AGE_RECONNECT`)합니다.
2. **`L7_PROXY` (Envoy, ALB 등 L7 프록시 방식)**:
   - 프록시가 클라이언트와의 HTTP/2 연결을 종단하고, 들어오는 개별 gRPC 스트림마다 백엔드 풀로 분산합니다.
   - 정책:
     - `"ROUND_ROBIN"`: 건강한 백엔드 풀을 대상으로 스트림마다 순환 분산 (`L7_STREAM_LEVEL_ROUND_ROBIN`).
     - `"LEAST_CONCURRENT"`: 현재 활성 처리 중인 요청 수(`active_concurrency`)가 가장 적은 백엔드로 분산 (`L7_LEAST_CONCURRENT_ROUTING`).
3. **`CLIENT_SIDE` (gRPC 클라이언트 사이드 로드밸런싱)**:
   - 클라이언트가 서비스 디스커버리를 통해 백엔드 파드들의 IP 목록을 직접 획득하고, 모든 파드와 1:1 독립 서브채널(Subchannel)을 맺습니다.
   - 클라이언트 내부 로드밸런서가 자체적으로 스트림 단위 분산을 수행합니다 (`CLIENT_SUBCHANNEL_ROUND_ROBIN` / `CLIENT_SUBCHANNEL_LEAST_CONCURRENT`).

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "load_balancer_type": "L4_PROXY",  // "L4_PROXY", "L7_PROXY", "CLIENT_SIDE"
  "lb_policy": "ROUND_ROBIN",        // "ROUND_ROBIN" 또는 "LEAST_CONCURRENT" (L7/Client-side)
  "max_connection_age_ms": 100,      // (선택) L4 커넥션 만료 및 재연결 주기
  "backend_servers": [
    {
      "id": "srv_1",
      "max_capacity": 3,             // 최대 동시 처리 가능 스트림 수
      "is_healthy": true             // 헬스 체크 통과 여부 (기본 true)
    },
    {
      "id": "srv_2",
      "max_capacity": 3,
      "is_healthy": true
    }
  ],
  "clients": [
    { "id": "client_app" }
  ],
  "requests": [
    {
      "request_id": "req_01",
      "client_id": "client_app",
      "timestamp_ms": 0,
      "duration_ms": 50
    }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 JSON 객체를 출력합니다:

```json
{
  "summary": {
    "load_balancer_type": "L4_PROXY",
    "lb_policy": "ROUND_ROBIN",
    "total_requests": 15,
    "total_processed": 10,
    "total_rejected": 5,
    "imbalance_ratio": 3.0,
    "overall_verdict": "SERVER_OVERLOAD_HOTSPOT_FAILURE"
  },
  "server_stats": {
    "srv_1": {
      "processed": 10,
      "rejected": 5,
      "total_received": 15
    },
    "srv_2": {
      "processed": 0,
      "rejected": 0,
      "total_received": 0
    }
  },
  "request_results": [
    {
      "request_id": "req_01",
      "client_id": "client_app",
      "assigned_server": "srv_1",
      "status": "PROCESSED",
      "routing_decision": "L4_NEW_TCP_CONNECTION_PINNED"
    }
  ]
}
```

---

## 제약 사항 및 상태 판정 기준

- **동시성 처리**: 요청의 유효 시간은 $[timestamp\_ms, timestamp\_ms + duration\_ms]$이며, 새 요청 시점에 종료 시각이 된 이전 요청들은 즉시 동시성 카운트에서 해제됩니다.
- **수용 한도 초과**: 할당된 서버의 현재 `active_concurrency >= max_capacity`인 경우 해당 요청은 즉시 거절되며 `status`는 `"REJECTED_OVERLOADED"`가 됩니다.
- **불균형 지수 (Imbalance Ratio)**:
  $$	ext{imbalance\_ratio} = rac{\max(	ext{Total Received}) - \min(	ext{Total Received})}{\max(	ext{Avg}(	ext{Total Received}), 1.0)}$$
  (소수점 둘째 자리까지 반올림)
- **최종 판정 (`overall_verdict`)**:
  - `total_rejected > 0`: `"SERVER_OVERLOAD_HOTSPOT_FAILURE"`
  - `total_rejected == 0`이고 `imbalance_ratio >= 1.0`: `"SEVERE_LOAD_IMBALANCE"`
  - `total_rejected == 0`이고 `0.5 <= imbalance_ratio < 1.0`: `"MODERATE_LOAD_IMBALANCE"`
  - `total_rejected == 0`이고 `imbalance_ratio < 0.5`: `"BALANCED"`
