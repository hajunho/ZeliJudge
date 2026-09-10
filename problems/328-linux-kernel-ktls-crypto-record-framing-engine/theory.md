# 리눅스 커널 kTLS (Kernel TLS) 및 암호화 오프로드 이론 (Linux Kernel kTLS Theory)

## 1. 개요 및 설계 철학

전통적인 소켓 암호화 통신에서는 유저 공간의 SSL/TLS 라이브러리가 다음과 같은 방식으로 작동했습니다:
1. 애플리케이션 버퍼의 데이터를 유저 공간 TLS 라이브러리로 복사
2. CPU가 유저 공간에서 대칭키 암호화(AES-GCM 등) 및 MAC 계산 수행
3. 암호화된 레코드를 `write()` 또는 `send()` 시스템 콜을 통해 커널 소켓 송신 버퍼(`sk_buff`)로 복사
4. 커널 TCP/IP 스택이 패킷을 캡슐화하여 NIC로 전달

이 전통적 모델은 최소 2회의 유저-커널 메모리 복사(`Ecopy`)와 수많은 컨텍스트 스위칭을 발생시켜, 40Gbps/100Gbps 고속 네트워크에서 심각한 CPU 병목을 유발했습니다.

**kTLS (`net/tls/`)**는 이 문제를 해결하기 위해 도입되었습니다:
- **핸드셰이크와 제어 평면 분리**: 복잡한 비대칭키 암호화, 인증서 교환, 협상은 기존처럼 유저 공간(OpenSSL)에서 안전하게 수행합니다.
- **데이터 평면 커널 통합**: 세션 키 협상이 완료되면 `setsockopt(fd, SOL_TLS, TLS_TX, ...)`를 통해 대칭키와 IV를 커널로 넘겨 소켓 레벨에서 인라인 암호화를 수행합니다.
- **제로 카피(Zero-Copy) 및 `sendfile()` 결합**: 파일 시스템 페이지 캐시나 유저 메모리 페이지를 커널 버퍼로 복사하지 않고 가상 메모리 포인터(Scatter-Gather List, `sg_list`)만으로 직접 암호화 엔진으로 파이프라인 처리합니다.

---

## 2. TLS 레코드 계층 프레이밍 구조

### TLS 1.2 Record Framing (RFC 5246)
```
+---------------+----------------+----------------+--------------------------+-------------------+
| Content Type  | Legacy Version | Length (16-bit)| Explicit Nonce (64-bit)  | Encrypted Payload | Auth Tag (16B)    |
| (1 Byte)      | (0x0303, 2B)   | (2 Bytes)      | (8 Bytes, sequence num)  | (Plaintext len)   | (HMAC/GHASH)      |
+---------------+----------------+----------------+--------------------------+-------------------+
```
- TLS 1.2에서는 헤더 뒤에 8바이트의 명시적 논스(Explicit Nonce)가 노출됩니다.

### TLS 1.3 Record Framing (RFC 8446)
```
+---------------+----------------+----------------+--------------------------+-------------------+-------------------+
| Legacy Type   | Legacy Version | Length (16-bit)| Encrypted Payload        | Inner Content Type| Auth Tag (16B)    |
| (0x17, 1B)    | (0x0303, 2B)   | (2 Bytes)      | (Plaintext len)          | (0x17 / 0x15, 1B) | (HMAC/GHASH)      |
+---------------+----------------+----------------+--------------------------+-------------------+-------------------+
```
- TLS 1.3에서는 트래픽 분석(Traffic Analysis)을 방지하기 위해 외부 헤더의 콘텐츠 타입을 항상 `0x17 (Application Data)`로 고정하고, 실제 콘텐츠 타입(Handshake, Alert 등)을 암호화 페이로드 내부의 가장 마지막 바이트(Inner Content Type)로 숨깁니다.
- 또한 8바이트 명시적 논스를 패킷에서 제거하고, 송수신 측이 공유하는 단조 증가 시퀀스 번호 $seq$와 Base IV를 비트 XOR하여 논스를 유도함으로써 대역폭 낭비를 줄입니다.

---

## 3. 스마트 NIC 인라인 하드웨어 오프로드 (`TLS_OFFLOAD_DEVICE`)

kTLS는 3가지 실행 모드를 지원합니다:
1. **`TLS_OFFLOAD_SW` (Software)**:
   - 커널 내부의 암호화 API 서브시스템(`crypto/`)을 활용하여 CPU 벡터 명령어(AES-NI, AVX-512)로 암호화를 수행합니다. 메모리 복사는 줄어들지만 여전히 CPU 사이클이 소모됩니다.
2. **`TLS_OFFLOAD_ASYNC` (Asynchronous Engine)**:
   - Intel QAT(QuickAssist Technology)와 같은 전용 PCIe 가속기로 암호화 작업을 오프로드하여 CPU를 해방하지만, DMA 인터럽트 및 링 버퍼 오버헤드가 수반됩니다.
3. **`TLS_OFFLOAD_DEVICE` (Hardware SmartNIC Inline Offload)**:
   - Mellanox ConnectX-6 Dx, Broadcom Thor 등 현대 스마트 NIC에 세션 키와 TCP 시퀀스를 직접 프로그래밍합니다.
   - 호스트 커널은 암호화되지 않은 플레인텍스트를 NIC로 전달하기만 하면, NIC의 내장 암호화 하드웨어가 패킷 송출 직전에 실시간으로 암호화 및 태그를 부착합니다.
   - 호스트 CPU 사용률이 거의 0%에 수렴하며 100Gbps+ 라인 레이트(Line-rate) 전송이 가능합니다.

---

## 4. 무결성 장애 검출과 `EBADMSG` (Bad Record MAC)

TLS 보안 모델의 핵심은 기밀성(Confidentiality)뿐만 아니라 무결성(Integrity)과 재생 방지(Replay Prevention)입니다:
- 매 레코드마다 64비트 시퀀스 번호가 묵시적으로 증가하므로, 중간 공격자가 패킷 순서를 바꾸거나 오래된 레코드를 재전송하면 $seq$ 불일치로 인해 AAD 검증이 실패합니다.
- 네트워크 전송 중 단 1비트의 손상이라도 발생하면 `HMAC-SHA256` 또는 `GHASH` 인증 태그가 불일치하게 됩니다.
- 리눅스 커널 kTLS는 인증 태그 검증 실패 시 즉시 소켓 상태를 에러로 전환하고 `EBADMSG (-74)`를 반환하여 연결을 강제 종료함으로써 침해 사고를 원천 차단합니다.
