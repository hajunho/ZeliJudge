# 이론: Linux Kernel AF_ALG 소켓 아키텍처 및 하드웨어 암호화 가속 엔진

## 1. 유저 공간 암호화의 한계와 `AF_ALG`의 설계 배경

전통적으로 사용자 공간 프로그램(OpenSSL, NGINX, IPSec 데몬)이 AES나 SHA 연산을 수행할 때는 OpenSSL의 자체 소프트웨어 라이브러리를 사용하거나 특수 ioctl 기반의 `/dev/crypto` 디바이스를 열어야 했습니다.

그러나 엔터프라이즈 서버 환경에서:
1. **하드웨어 가속기 드라이버 접근**: Intel QAT(QuickAssist Technology), ARMv8 Cryptographic Engine, AMD CCP(Cryptographic Coprocessor) 등 전용 가속기 드라이버는 호스트 커널 공간에 적재되어 있습니다.
2. **권한 분리**: 비특권 컨테이너나 일반 사용자가 디바이스 노드(`/dev/crypto`)에 직접 접근하는 것은 보안 정책상 차단됩니다.

리눅스 커널 2.6.38에 도입된 **`AF_ALG` (Algorithm Sockets)**는 유닉스 철학("모든 것은 파일이자 소켓이다")을 계승하여, 친숙한 표준 BSD 소켓 시스템 콜(`socket`, `bind`, `setsockopt`, `accept`)을 통해 커널 내부의 강력한 하드웨어 가속기에 투명하게 접근할 수 있도록 설계되었습니다 (`crypto/af_alg.c`).

---

## 2. 2단계 소켓 생명주기 (Listener vs Connection Sockets)

`AF_ALG`의 동작 모델은 네트워크 TCP 서버의 `listen()`과 `accept()` 구조를 그대로 차용합니다:

```
 [1단계: Listener Socket (socket + bind + setsockopt)]
 socket(AF_ALG, SOCK_SEQPACKET, 0)
   --> bind(sockaddr_alg { salg_type = "aead", salg_name = "gcm(aes)" })
   --> setsockopt(ALG_SET_KEY, key)
 
 [2단계: Session Connection Socket (accept)]
 conn_fd = accept(listen_fd)
   --> 커널 내부에 해당 알고리즘의 세션 컨텍스트(struct af_alg_ctx) 할당
   --> sendmsg()로 평문 및 IV/AAD 전달
   --> recvmsg()로 암호문 및 인증 태그 수신
```

- **리스너 소켓**: 알고리즘 할당(`crypto_alloc_tfm`) 및 마스터 키 저장을 담당합니다.
- **연결 소켓**: 실제 I/O 버퍼와 암호화 상태(IV 카운터, AAD 길이)를 유지하며 암호화 연산을 병렬로 처리합니다. 이를 통해 단 하나의 마스터 키 설정으로 수천 개의 독립적인 동시 암호화 세션을 생성할 수 있습니다.

---

## 3. AEAD (Authenticated Encryption with Associated Data)와 `cmsg` 제어

현대 암호화 표준(TLS 1.3, WireGuard, IPSec)의 핵심인 **AEAD (예: AES-GCM, ChaCha20-Poly1305)**는 기밀성(암호화)뿐만 아니라 무결성(인증)을 동시에 보장합니다.

`AF_ALG`는 부가적인 메타데이터를 소켓의 보조 데이터(Control Message: `cmsg`)를 통해 커널로 전달합니다:
- `ALG_SET_OP`: `ALG_OP_ENCRYPT (1)` 또는 `ALG_OP_DECRYPT (0)`.
- `ALG_SET_IV`: 12바이트 또는 16바이트 초기화 벡터(IV).
- `ALG_SET_AEAD_ASSOCLEN`: 패킷 헤더 등 암호화되지는 않지만 변조 여부를 반드시 검증해야 하는 부가 인증 데이터(AAD)의 바이트 길이.

```
 [sendmsg Payload Structure]
 +-------------------+------------------------------------+
 | AAD (Associated)  | Plaintext (Data to Encrypt)        |
 +-------------------+------------------------------------+
 
 [recvmsg Encrypted Output]
 +------------------------------------+-------------------+
 | Ciphertext                         | Tag (16 Bytes)    |
 +------------------------------------+-------------------+
```

---

## 4. 무결성 위조 감지와 `EBADMSG`

복호화(`ALG_OP_DECRYPT`) 시 커널은 하드웨어 가속기를 통해 수신된 AAD와 암호문으로부터 계산된 태그와 패킷 끝에 첨부된 16바이트 인증 태그를 비교합니다:
- 일치하는 경우: 평문을 복원하여 사용자 공간 버퍼로 복사.
- 단 1비트라도 불일치하는 경우: 공격자의 변조 시도(Tampering)로 간주하여 평문을 일체 노출하지 않고 즉시 **`EBADMSG` (Bad Message)** 오류 코드를 반환합니다.

이와 같은 정교한 커널 소켓 추상화 덕분에 엔터프라이즈 애플리케이션은 복잡한 하드웨어 드라이버를 직접 작성하지 않고도 최고의 보안성과 처리량을 달성할 수 있습니다.
