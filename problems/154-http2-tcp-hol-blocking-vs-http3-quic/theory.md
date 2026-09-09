# [CS Deep Dive] HTTP/2 TCP HoL 블로킹의 태생적 한계와 HTTP/3 QUIC 혁신

## 1. 전송 계층과 애플리케이션 계층의 불일치 (Layering Mismatch)

HTTP의 진화 과정은 언제나 **Head-of-Line (HoL) 블로킹**과의 전쟁이었습니다:

```
+-----------------------------------------------------------------------+
| HTTP/1.0  | 커넥션당 1개 요청/응답 (Short-lived TCP)                    |
|           | -> 매 요청마다 3-Way Handshake 반복으로 극심한 오버헤드      |
+-----------------------------------------------------------------------+
| HTTP/1.1  | Persistent Connection (Keep-Alive) & 파이프라이닝           |
|           | -> FIFO 순서 보장 의무로 앞선 HTTP 요청 지연 시 뒤 요청 블로킹 |
|           |    (HTTP 계층 HoL Blocking)                               |
+-----------------------------------------------------------------------+
| HTTP/2    | 단일 TCP 상에서 프레임 단위 다중화 (Multiplexing)           |
|           | -> HTTP 계층 HoL은 해결했으나, TCP 계층의 엄격한 바이트 스트림 |
|           |    순서 보장으로 인해 전 스트림 동시 블로킹 (TCP HoL Blocking) |
+-----------------------------------------------------------------------+
| HTTP/3    | UDP 기반 QUIC 프로토콜 (RFC 9000 / RFC 9114)              |
|           | -> 독립된 QUIC 스트림으로 TCP HoL 완전 소멸, Connection ID    |
|           |    기반 0-RTT 핸드오버 (Connection Migration) 달성             |
+-----------------------------------------------------------------------+
```

---

## 2. HTTP/2의 아킬레스건: TCP 계층 HoL 블로킹 메커니즘

HTTP/2는 L7(애플리케이션 계층)에서 각 요청과 응답을 작은 **바이너리 프레임(Frame)** 으로 잘게 쪼개어 단 하나의 TCP 연결 위로 인터리빙(Interleaving)하여 전송합니다.

### 왜 패킷 하나 유실이 전 스트림을 멈추는가?
1. **TCP는 바이트 스트림(Byte Stream) 프로토콜**:
   OS 커널의 TCP 계층(`tcp_input.c`)은 전송되는 데이터가 HTTP/2 프레임인지 전혀 알지 못합니다. TCP의 유일한 사명은 **"송신된 시퀀스 번호 순서 그대로 빈틈없이 상위 계층에 바이트를 전달하는 것(In-Order Delivery)"** 입니다.
2. **패킷 드롭 시 커널 수신 버퍼 정체**:
   - 패킷 1 (Stream 1의 일부)이 무선망에서 유실됨.
   - 패킷 2 (Stream 2의 데이터), 패킷 3 (Stream 3의 데이터)이 정상 수신됨.
   - TCP 수신 윈도우는 패킷 1이 도착하지 않았으므로, 패킷 2와 패킷 3을 OS 소켓 수신 큐(Out-of-Order Queue)에 보관하고 사용자 애플리케이션(`read()`)으로 전달하지 않습니다!
   - 송신 측이 패킷 유실을 감지하고 재전송(Retransmission)하여 수신될 때까지 최소 $1\text{ RTT}$ 동안, **전혀 무관한 Stream 2, 3의 데이터까지 커널에 감금되어 처리되지 못합니다.**
3. **네트워크 손실률과 성능 역전**:
   - 유실률 $0\%$의 유선망: HTTP/2가 압도적 우위.
   - 유실률 $2\% \sim 5\%$의 무선 모바일망: 6개의 TCP 커넥션을 분산 사용하던 HTTP/1.1보다 HTTP/2의 체감 지연 시간이 오히려 급격히 나빠집니다.

---

## 3. QUIC (HTTP/3)의 해결 원리: UDP 기반 독립 스트림

Google이 개발하고 IETF가 표준화한 **QUIC(Quick UDP Internet Connections)** 은 TCP의 근본적 결함을 전면 재설계했습니다:

### 1. 전송 계층 수준의 독립 스트림 (Independent Streams)
* QUIC 패킷 헤더에는 스트림 ID(`Stream ID`)와 스트림 내 오프셋(`Offset`)이 명시됩니다.
* 스트림 1의 패킷이 유실되어도, 스트림 2의 패킷이 도착하면 커널/QUIC 라이브러리는 스트림 1의 재전송을 기다리지 않고 **스트림 2의 데이터를 즉시 상위 HTTP/3 계층으로 디스패치**합니다.
* 결과적으로 스트림 간 HoL 블로킹이 완전히 $0$이 됩니다.

### 2. Connection ID 기반 Connection Migration
* **기존 TCP의 한계 (4-Tuple 바인딩)**:
  `{Source IP, Source Port, Destination IP, Destination Port}`
  스마트폰이 Wi-Fi(IP: `192.168.1.50`)에서 이동하여 LTE/5G(IP: `211.58.12.3`)로 전환되면 4-Tuple이 변경되어 기존 TCP 연결이 즉시 파괴(RST)됩니다.
* **QUIC의 Connection ID (CID)**:
  QUIC은 패킷 헤더에 무작위 64비트 Connection ID를 포함합니다.
  클라이언트의 IP나 포트가 변경되어도 서버는 CID를 통해 동일한 논리 세션임을 즉시 식별하므로, **재연결 핸드셰이크 지연 없이 0ms 즉시 전송(Seamless Migration)** 이 유지됩니다.

---

## 4. 실무 아키텍처 가이드라인

1. **클라우드 CDN 및 인프라의 HTTP/3 활성화**:
   - Cloudflare, CloudFront, Fastly 등 글로벌 CDN 엣지에서 HTTP/3(QUIC)을 활성화하십시오 (`Alt-Svc` 헤더 제공).
   - 모바일 앱 클라이언트(OkHttp, Cronet)에서 HTTP/3를 기본 지원하도록 설정하면 패킷 손실률이 높은 환경에서 P99 응답 지연을 최대 40% 이상 단축할 수 있습니다.
2. **UDP 443 포트 방화벽 개방**:
   - 일부 엔터프라이즈 사내망이나 레거시 방화벽이 UDP 443 트래픽을 차단하는 경우가 있으므로, 클라이언트 라이브러리는 QUIC 연결 실패 시 자동으로 HTTP/2로 폴백(Fallback / Happy Eyeballs)하는 메커니즘을 구비해야 합니다.
