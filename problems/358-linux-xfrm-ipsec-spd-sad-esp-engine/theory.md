# Linux Kernel XFRM 프레임워크와 IPsec ESP/안티 리플레이 프로토콜 이론

## 1. 리눅스 네트워크 스택에서 XFRM 서브시스템의 위치

Linux 커널 2.6부터 도입된 **XFRM(Transform)** 프레임워크는 IPsec(RFC 4301~4309)을 포함하여 패킷의 페이로드를 암호화, 인증, 압축(IPComp)하는 통합 커널 변환 아키텍처입니다.

XFRM은 L3 라우팅 서브시스템(`fib_lookup`, `dst_entry`)과 깊게 결합되어 있습니다:
- **Outbound Path**:
  소켓 계층에서 생성된 패킷이 라우팅을 거친 후 `xfrm_lookup()`을 호출합니다.
  SPD(Security Policy Database)에 매칭되는 규칙이 있으면, 일반 라우팅 대상체(`rtable`)를 XFRM 전용 대상체(`xfrm_dst`)로 감싸 `dst->output` 함수 포인터를 `xfrm_output()`으로 교체합니다.
- **Inbound Path**:
  IP 프로토콜 번호 50(ESP) 또는 51(AH)을 수신하면 `inet_protos` 해시 테이블을 통해 `xfrm4_rcv()` / `xfrm6_rcv()`로 직결되어 `xfrm_input()`에서 복호화 및 인증을 수행합니다.

---

## 2. SPD와 SAD의 분리 설계 철학

XFRM 아키텍처는 제어 플레인(Control Plane)과 데이터 플레인(Data Plane)을 분리하기 위해 두 개의 핵심 데이터베이스를 엄격히 분리합니다:

| 구분 | 보안 정책 데이터베이스 (SPD) | 보안 연관 데이터베이스 (SAD) |
| :--- | :--- | :--- |
| **커널 소스** | `net/xfrm/xfrm_policy.c` | `net/xfrm/xfrm_state.c` |
| **관리 주체** | 네트워크 관리자 / 오케스트레이터 정책 | IKE 키 교환 데몬(StrongSwan, Libreswan) |
| **키 식별자** | 5-튜플 (방향, 소스/목적지 서브넷, 포트, 프로토콜) | 3-튜플 (목적지 IP, SPI, 프로토콜: ESP/AH) |
| **역할** | "어떤 트래픽에 보안을 적용할 것인가?" | "암호화 키와 알고리즘은 무엇인가?" |
| **수명** | 영구적 또는 장기적 정책 | 세션 단위 일시적 수명 (Rekey 교체) |

---

## 3. ESP (Encapsulating Security Payload, RFC 4303) 구조와 오버헤드

ESP 패킷은 원본 L3/L4 페이로드를 완벽히 은닉하고 암호화합니다:

```
0                   1                   2                   3
0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|               Security Parameters Index (SPI)                 |  <- ESP Header (8B)
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                      Sequence Number                          |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                    Initialization Vector (IV)                 |  <- 8B (AES-GCM)
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                    Payload Data (Encrypted)                   |
|                              ...                              |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|     Padding (0-3 bytes)       | Pad Length    | Next Header   |  <- ESP Trailer
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|             Integrity Check Value (ICV / Auth Tag)           |  <- 16B (GMAC)
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

- **ESP 터널 모드 vs 트랜스포트 모드**:
  - **Transport Mode**: 원본 IP 헤더를 보존하고 L4 페이로드만 ESP로 감쌈 (Host-to-Host).
  - **Tunnel Mode**: 원본 IP 패킷 전체를 암호화하고 새로운 외부 IP 헤더(20B/40B)를 추가 (Site-to-Site VPN, Gateway).

---

## 4. RFC 4303 안티 리플레이(Anti-Replay) 슬라이딩 윈도우 알고리즘

공격자가 유효하게 암호화된 정상 ESP 패킷을 네트워크 상에서 가로채어 수천 번 재전송(Replay Attack)하여 서버 자원을 고갈시키거나 중복 트랜잭션을 유발하는 것을 방어합니다.

### 4.1 슬라이딩 윈도우 원리
- 윈도우 크기 $W$ (기본 64, 최신 커널은 128~1024비트 비트맵 지원).
- 현재까지 수신된 패킷 중 가장 높은 시퀀스 번호를 $H$라고 할 때:
  1. $	ext{Seq} > H$: 새로운 미래 패킷. 윈도우를 $	ext{Seq} - H$만큼 우측으로 슬라이딩하고 비트맵 갱신 ($H \leftarrow 	ext{Seq}$).
  2. $H - W < 	ext{Seq} \le H$: 윈도우 내부 패킷. 비트맵에서 $	ext{Seq}$에 해당하는 비트를 검사:
     - 이미 `1`이면 중복 패킷으로 즉시 폐기.
     - `0`이면 비트를 `1`로 세팅하고 패킷 수락.
  3. $	ext{Seq} \le H - W$: 윈도우 좌측 경계를 벗어난 너무 오래된 패킷 $ightarrow$ 즉시 폐기.

이 알고리즘은 비트 연산(Shift 및 Bitwise OR)을 통해 **$O(1)$ 시간 복잡도**로 패킷당 수 나노초 내에 재전송 공격을 원천 차단합니다.

---

## 5. SA 수명(Lifetime)과 IKE 키 갱신 (Rekeying)

단일 대칭키(AES 키)로 과도한 양의 데이터를 암호화하면 암호학적 공격(생일 공격, 바이어스 분석)에 취약해집니다.
- **Soft Lifetime**:
  누적 바이트나 시간이 소프트 제한에 도달하면, 커널 XFRM은 Netlink 소켓(`NETLINK_XFRM`)을 통해 IKE 데몬에게 `XFRM_MSG_EXPIRE(soft)` 이벤트를 발행합니다. 데몬은 트래픽 중단 없이 백그라운드에서 새로운 SA를 협상합니다.
- **Hard Lifetime**:
  소프트 제한 이후에도 키 교환이 완료되지 못하고 하드 제한을 초과하면, 보안 누설을 방지하기 위해 커널은 즉시 해당 SA를 통한 모든 트래픽을 폐기(`SA_HARD_EXPIRED`)합니다.

---

## 6. 클라우드 및 쿠버네티스(Calico/Cilium) 환경의 모범 사례

1. **하드웨어 암호 오프로드 (IPsec Crypto Offload)**:
   - Mellanox ConnectX-6 Dx / Intel E810과 같은 최신 스마트 NIC은 `xfrm_dev_offload`를 통해 AES-GCM 연산을 NIC ASIC으로 오프로드하여 호스트 CPU 사용률을 90% 이상 절감합니다.
2. **WireGuard와의 비교**:
   - WireGuard는 단일 알고리즘(ChaCha20-Poly1305)과 단순한 설정으로 각광받지만, 엔터프라이즈 환경에서 FIPS-140-2 인증(AES-GCM 필수), 하드웨어 오프로드 지원, 다양한 서브넷 기반 정책 라우팅을 만족하는 데는 Linux XFRM IPsec이 필수적입니다.
