# 깊이 있는 컴퓨터 과학: 리눅스 커널 TCP 3-Way Handshake와 SYN Flood 방어 아키텍처

## 1. 리눅스 TCP 연결 수립의 2단계 큐 모델

리눅스 커널은 TCP 연결 수립 과정을 2단계 큐로 분리하여 관리합니다:

```
[클라이언트]                           [리눅스 커널]                          [사용자 앱]
    |                                      |                                      |
    |---- SYN ---------------------------->|                                      |
    |                                      | [1. SYN Queue 할당 (SYN_RECV)]       |
    |<--- SYN-ACK (ISN 쿠키) --------------|                                      |
    |                                      |                                      |
    |---- ACK ---------------------------->|                                      |
    |                                      | [2. Accept Queue 이동 (ESTABLISHED)] |
    |                                      |                                      |
    |                                      |<--- accept() ------------------------|
    |                                      |----> 소켓 FD 반환 ------------------->|
```

### 1.1 `request_sock` 구조체와 메모리 비용
- 전통적인 방식에서 `SYN`을 수신하면 커널은 `struct request_sock` 구조체(약 256~512 바이트)를 슬랩 할당자(`kmem_cache`)에서 할당받아 반연결 해시 테이블에 보관합니다.
- 초당 수백만 개의 SYN이 쏟아지면 커널 메모리가 고갈되거나 `tcp_max_syn_backlog` 제한에 걸려 신규 패킷을 드롭합니다.

---

## 2. SYN Cookies 메커니즘 (D. J. Bernstein 1996)

SYN Cookies는 메모리를 소비하지 않고 3-Way Handshake를 완결하는 독창적인 암호학적 기법입니다.

### 2.1 32비트 ISN(Initial Sequence Number) 인코딩
커널은 32비트 시퀀스 번호를 다음과 같이 분할하여 생성합니다:
1. **상위 5비트 ($t \pmod{32}$)**: 64초 단위로 증가하는 느린 시계(Slow Counter). 유효 시간(보통 1~2분) 만료 검증용.
2. **중간 3비트**: MSS(Maximum Segment Size) 인덱스. SYN 패킷의 MSS 옵션을 8가지 표준 값(예: 536, 1460 등) 중 하나로 양자화하여 인코딩.
3. **하위 24비트**: 암호화 해시 값.
   $$\text{Hash} = \text{SHA256}(\text{Client IP}, \text{Client Port}, \text{Server IP}, \text{Server Port}, t, \text{Secret}) \pmod{2^{24}}$$

### 2.2 장단점 및 트레이드오프
- **장점**: SYN Flood 공격 시 서버 메모리 소비가 완벽히 0이 되며, DoS 공격에 면역을 가짐.
- **단점 (RFC 1323 옵션 제약)**:
  - 서버가 SYN 패킷을 저장하지 않으므로 TCP 타임스탬프(`TCP Timestamps`), 윈도우 스케일링(`Window Scale`), SACK(Selective ACK) 등 클라이언트가 제안한 확장 옵션을 기억하지 못함.
  - **현대 커널의 해결책**: 리눅스 2.6.26부터 `tcp_timestamps = 1`인 경우 타임스탬프 필드의 하위 비트에 TCP 옵션들을 추가 인코딩하여 옵션 손실 문제를 해결함.

---

## 3. 리슨 백로그(Listen Backlog)와 Accept 큐 병목

### 3.1 `net.core.somaxconn` vs `listen(fd, backlog)`
- `int listen(int sockfd, int backlog);`
- 리눅스 커널은 실제 Accept 큐의 크기를 `min(backlog, sysctl_somaxconn)`으로 결정합니다.
- `somaxconn`의 기본값(128)이 너무 낮으면, 아무리 애플리케이션이 `listen(fd, 1024)`를 호출해도 실제 큐는 128개로 잘립니다(Truncated).

### 3.2 `tcp_abort_on_overflow`의 동작
- Accept 큐가 꽉 찼을 때 최종 `ACK`를 수신하면:
  - `tcp_abort_on_overflow = 0` (기본값): 커널은 이 ACK를 조용히 무시(Ignore)합니다. 클라이언트는 연결이 수립되었다고 생각하지만, 첫 데이터를 보낼 때 서버가 처리하지 못해 재전송을 반복하게 됩니다.
  - `tcp_abort_on_overflow = 1`: 커널이 즉각 `RST` 패킷을 전송하여 클라이언트의 연결을 즉시 리셋시킵니다.
