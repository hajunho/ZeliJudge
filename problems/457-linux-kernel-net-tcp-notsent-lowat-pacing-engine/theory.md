# 이론: Linux Kernel TCP TCP_NOTSENT_LOWAT 소켓 버퍼블로트 제거 및 JIT 페이싱 아키텍처

## 1. 대규모 대역폭-지연 곱(BDP)과 고전적 버퍼블로트

TCP 프로토콜이 물리 링크의 가용 대역폭을 100% 활용하기 위해서는 소켓 송신 버퍼의 크기가 대역폭-지연 곱(Bandwidth-Delay Product, $	ext{BDP} = 	ext{Bandwidth} 	imes 	ext{RTT}$) 이상이어야 합니다.
- 10Gbps 대역폭, 50ms RTT 네트워크:
  $$	ext{BDP} = 10 	imes 10^9 	ext{ bps} 	imes 0.05 	ext{ s} / 8 = 62.5 	ext{ MB}$$

이 때문에 현대 리눅스 커널의 TCP 오토튜닝(`tcp_wmem`)은 기본적으로 소켓 버퍼를 수 MB에서 수십 MB까지 동적으로 확장합니다.

그러나 이 거대한 버퍼는 **소켓 수준의 심각한 버퍼블로트(Bufferbloat)**를 야기합니다:
- 애플리케이션이 `epoll(POLLOUT)` 통지를 받으면 소켓 버퍼의 남은 공간이 소진될 때까지 수 MB의 데이터를 한 번에 밀어 넣습니다 (`write()`).
- 이렇게 커널 메모리(`sk_write_queue`)에 적재된 데이터 중 실제 네트워크 카드(NIC)로 나간 것은 극히 일부에 불과하며, 대부분은 커널 큐에서 멍하니 대기하게 됩니다.
- 이 대기 시간은 수십에서 수백 밀리초(ms)에 달하며, 이후 발생한 긴급 제어 메시지나 고우선순위 스트림의 전송을 가로막는 치명적인 헤드오브라인 블로킹(HOL Blocking)을 초래합니다.

---

## 2. HTTP/2·HTTP/3 멀티플렉싱과 스트림 우선순위 역전

단일 TCP 연결 위에서 수십~수백 개의 독립적인 논리 스트림을 다중화(Multiplexing)하는 HTTP/2 및 gRPC 환경에서 이 문제는 치명적입니다:
1. **대용량 파일 스트림 A**가 2MB를 한 번에 소켓에 씁니다.
2. 5ms 뒤 사용자가 웹 브라우저에서 버튼을 클릭하여 **초고우선순위 클릭 이벤트 스트림 B (200바이트)**를 전송하려 합니다.
3. 소켓 버퍼가 가득 차 있거나, 스트림 B의 패킷이 커널 송신 큐의 맨 뒤에 적재됩니다.
4. 스트림 B는 앞선 2MB가 모두 전송되고 ACK될 때까지 네트워크에 발을 들이지 못합니다.
- 결과적으로 애플리케이션 계층에서 아무리 복잡한 스트림 우선순위 트리(Priority Tree)를 구성했더라도, 커널 송신 큐의 맹목적인 FIFO 동작에 의해 무력화됩니다.

---

## 3. `TCP_NOTSENT_LOWAT` 메커니즘과 JIT (Just-In-Time) 페이싱

리눅스 커널 3.12에서 Eric Dumazet이 제안한 `TCP_NOTSENT_LOWAT` 소켓 옵션(`include/uapi/linux/tcp.h`)은 쓰기 가능(POLLOUT) 판단 기준의 패러다임을 바꿨습니다:

```
 [기존 전통적 커널 로직: tcp_poll()]
 if (sk_stream_wspace(sk) >= sk_stream_min_wspace(sk))
     mask |= POLLOUT;

 [현대 TCP_NOTSENT_LOWAT 커널 로직: tcp_stream_memory_free()]
 int notsent = sk->sk_wmem_queued - tcp_wmem_in_flight(sk);
 if (notsent < tp->notsent_lowat && sk_stream_memory_free(sk))
     mask |= POLLOUT;
```

- **`notsent` (미송신 큐 바이트 수)**:
  소켓 큐에 적재되었으나 아직 하드웨어 전송 큐(TSQ / qdisc / NIC ring)로 전달되지 않은 순수 잔여 바이트 수입니다.
- **동작 원리**:
  1. 애플리케이션이 데이터를 쓸 때, `notsent`가 `notsent_lowat`(예: 16KB 또는 1 MSS)을 초과하면 커널은 즉시 `POLLOUT` 마스크를 끄고 epoll 대기 큐로 들어갑니다.
  2. TCP 페이싱 타이머(FQ/Pacing) 또는 ACK 수신에 의해 데이터가 네트워크로 전송되어 `notsent`가 16KB 미만으로 떨어지는 순간, 커널은 `sk->sk_write_space()`를 호출하여 epoll 루프를 깨웁니다.
  3. 애플리케이션은 깨어난 그 시점에 가장 우선순위가 높은 프레임을 실시간으로 선택하여 16KB 단위로 주입(Just-In-Time)합니다.

---

## 4. 성능 및 지연 시간 벤치마크 효과

1. **소켓 내부 버퍼 지연 최소화**:
   - 기존 수 MB 큐잉으로 인한 수백 ms의 지연이 1~2 RTT 미만(수 ms)으로 95% 이상 격감합니다.
2. **TLS 레코드 분할 최적화**:
   - OpenSSL/BoringSSL 등의 TLS 라이브러리가 불필요하게 거대한 레코드를 미리 암호화하여 버퍼에 묶어둘 필요가 없어집니다.
3. **HTTP/2 우선순위 역전 해소**:
   - 구글 크로미엄(Chromium) 및 Envoy, NGINX의 실측 결과, 고우선순위 RPC의 테일 레이턴시(p99 지연)가 3~10배 개선되었습니다.
