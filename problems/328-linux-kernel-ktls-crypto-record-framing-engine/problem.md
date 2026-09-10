# 리눅스 커널 kTLS 대칭 암호화 오프로드 및 레코드 프레이밍 엔진 (Linux Kernel kTLS Crypto Record Framing Engine)

## 문제 설명

현대 고성능 웹 서버(NGINX, Envoy, Cloudflare 등) 및 클라우드 인프라에서는 초당 수십만 건의 HTTPS 연결을 처리하기 위해 CPU 연산 부하를 최소화하는 것이 핵심 과제입니다. 기존 유저스페이스 기반 TLS 라이브러리(OpenSSL 등)는 데이터 전송 시 커널 공간과 유저 공간 사이의 잦은 메모리 복사(`read()` / `write()`) 및 컨텍스트 스위칭으로 인해 대역폭 병목을 겪습니다.

리눅스 커널은 버전 4.13부터 **kTLS(Kernel TLS, `net/tls/tls_sw.c`, `net/tls/tls_device.c`)** 서브시스템을 도입하여, TLS 핸드셰이크는 유저스페이스에서 완료하고 실제 대칭키 데이터 암/복호화 및 레코드 프레이밍(Record Framing)을 커널 네트워크 스택 또는 하드웨어 스마트 NIC(SmartNIC Inline Offload)로 완전히 위임하는 아키텍처를 구현했습니다. 특히 kTLS는 `sendfile()` 및 `splice()` 시스템 콜과 결합하여 송신 버퍼의 제로 카피(Zero-Copy) 전송을 실현합니다.

당신은 리눅스 커널 네트워크 서브시스템 엔지니어로서, **TLS 1.2 / TLS 1.3 레코드 계층 프레이밍, AEAD 대칭 암호화/인증 태그 검증, `MSG_MORE` 레코드 병합(Coalescing), 제로 카피 계측 및 NIC 하드웨어 오프로드 성능 시뮬레이션 엔진**을 구현해야 합니다.

```
+-------------------------------------------------------------------------+
|                  Linux Kernel kTLS Subsystem Architecture               |
+-------------------------------------------------------------------------+
| [User Space]                                                            |
|  NGINX / Web App ---> sendmsg(MSG_MORE) / splice() (Zero-Copy)          |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
| [Kernel Space: net/tls/]                                                |
|                                                                         |
|  +-----------------------+     +-------------------------------------+  |
|  | TX Record Framing     |     | RX Stream Parser & Reassembly       |  |
|  | - MSG_MORE Coalescing |     | - 5-byte TLS Header Inspection      |  |
|  | - max_record_size     |     | - Frame Boundary & Incomplete Buffer|  |
|  +-----------+-----------+     +------------------+------------------+  |
|              |                                    ^                     |
|              v                                    |                     |
|  +------------------------------------------------+------------------+  |
|  | AEAD Crypto Engine (TLS 1.2 / TLS 1.3)                            |  |
|  | - Monotonic 64-bit Sequence Counter: seq_tx / seq_rx              |  |
|  | - Nonce Derivation: TLS 1.3 (IV ^ pad(seq)), TLS 1.2 (Salt+Nonce) |  |
|  | - Stream Keystream Encryption & 16-byte HMAC-SHA256 Auth Tag     |  |
|  +-------------------------------------------------------------------+  |
|                                    |                                    |
|              +---------------------+---------------------+              |
|              |                                           |              |
|              v (Offload Mode Selection)                  v              |
|  +-----------------------+                   +-----------------------+  |
|  | TLS_OFFLOAD_SW        |                   | TLS_OFFLOAD_DEVICE    |  |
|  | (Software CPU Crypto) |                   | (NIC Inline Offload)  |  |
|  +-----------+-----------+                   +-----------+-----------+  |
|              |                                           |              |
+--------------+-------------------------------------------+--------------+
               |                                           |
               v                                           v
+-------------------------------------------------------------------------+
| [TCP / IP Stack & Physical NIC Wire Transmission]                       |
+-------------------------------------------------------------------------+
```

---

## 엔진 규격 및 알고리즘

### 1. 세션 초기화 (`config`)
- `tls_version`: `"TLS_1_2"` 또는 `"TLS_1_3"`
- `cipher_suite`: `"AES_128_GCM"`, `"AES_256_GCM"`, 또는 `"CHACHA20_POLY1305"`
- `offload_mode`: `"SW"`, `"DEVICE"` (스마트 NIC 하드웨어 오프로드), 또는 `"ASYNC"` (비동기 가속기 QAT)
- `tx_key_hex`, `tx_iv_hex`, `rx_key_hex`, `rx_iv_hex`: 16진수 키 및 IV (TLS 1.3은 12바이트 Base IV, TLS 1.2는 4바이트 Implicit Salt)
- `max_record_size`: 레코드 최대 페이로드 크기 (기본값: 16384바이트)
- `coalesce_enabled`: `MSG_MORE` 병합 활성화 여부 (boolean)

### 2. 논스(Nonce) 유도 및 AEAD 암/복호화
1. **단조 증가 시퀀스 번호**:
   - $seq_{tx}$ 및 $seq_{rx}$는 $0$에서 시작하여 프레임이 송신/수신될 때마다 1씩 증가합니다.
2. **논스 유도 ($Nonce$)**:
   - **TLS 1.3**: Base IV (12바이트)와 4바이트 $0$ 패딩된 64비트 $seq$ (12바이트)를 XOR:
     $$Nonce = IV_{base} \oplus (	ext{0x00000000} \parallel seq_{64})$$
   - **TLS 1.2**: 4바이트 Implicit Salt와 8바이트 Explicit Nonce($seq_{64}$)를 결합:
     $$Nonce = Salt_{4} \parallel seq_{64}$$
3. **키스트림(Keystream) 생성 및 암호화**:
   - $counter$를 $0, 1, \dots$ 증가시키며 `HMAC-SHA256(Key, Nonce || counter_32)`의 32바이트 다이제스트를 연결하여 데이터 길이만큼의 키스트림을 생성하고 바이트별 XOR 수행.
4. **인증 태그(Auth Tag) 및 AAD 계산**:
   - 16바이트 인증 태그: `HMAC-SHA256(Key, AAD || Ciphertext)[:16]`
   - **TLS 1.3 AAD**: 5바이트 레코드 헤더 (`[0x17, 0x03, 0x03, Length_16]`)
     - TLS 1.3 레코드는 Inner Plaintext 끝에 1바이트 내부 콘텐츠 타입(`0x17` 등)을 추가한 후 암호화합니다.
   - **TLS 1.2 AAD**: $seq_{64} \parallel 	ext{Header}_{3} \parallel 	ext{Length}_{16}$ (13바이트)

### 3. 송신(TX) 프레이밍 및 병합(`MSG_MORE`)
- 플래그에 `"MSG_MORE"`가 포함되고 `coalesce_enabled`가 참인 경우:
  - 현재 보류 중인 데이터와 새 데이터의 합이 `max_record_size` 이하이면 레코드를 즉시 방출하지 않고 버퍼에 보류(`"status": "BUFFERED"`).
  - 초과 시 보류 중인 데이터를 레코드로 방출하고, 이후 데이터를 `max_record_size` 단위로 분할 방출.
- 플래그에 `"ZERO_COPY"`가 포함된 경우:
  - 송신 페이로드 바이트 수를 `zero_copy_bytes` 통계에 누적.

### 4. 수신(RX) 스트림 파싱 및 무결성 검증
- TCP 스트림은 단편화(Fragmentation)되거나 여러 레코드가 결합되어 도착할 수 있습니다.
- 5바이트 TLS 헤더를 분석하여 레코드 전체 길이($5 + L_{rec}$)가 버퍼에 수신될 때까지 대기.
- 완전한 레코드가 도착하면 태그를 검증:
  - **태그 일치 시**: 복호화하여 `rx_delivered_plaintext_hex`에 누적, 수신 통계 갱신.
  - **태그 불일치 또는 데이터 손상 시**: 소켓 상태를 `"TLS_ERROR_BAD_RECORD_MAC"`로 전환하고 에러 반환. 이후의 모든 연산은 거부됨.

### 5. CPU 사이클 및 하드웨어 오프로드 성능 모델
- 총 페이로드 바이트: $B_{total} = B_{tx} + B_{rx}$
- `DEVICE` 모드: $CPU\_Cycles = \lfloor B_{total} 	imes 0.5 floor$, 절감률 $88.5\%$
- `ASYNC` 모드: $CPU\_Cycles = \lfloor B_{total} 	imes 3.2 floor$, 절감률 $62.0\%$
- `SW` 모드: $CPU\_Cycles = \lfloor B_{total} 	imes 12 + (B_{tx} - B_{zc}) 	imes 2 floor$, 절감률 $0.0\%$

---

## 입력 형식

JSON 객체 형태로 표준 입력(`sys.stdin`)으로 주어집니다:
```json
{
  "config": {
    "tls_version": "TLS_1_3",
    "cipher_suite": "AES_128_GCM",
    "offload_mode": "DEVICE",
    "tx_key_hex": "0102030405060708090a0b0c0d0e0f10",
    "tx_iv_hex": "112233445566778899aabbcc",
    "rx_key_hex": "0102030405060708090a0b0c0d0e0f10",
    "rx_iv_hex": "112233445566778899aabbcc",
    "max_record_size": 16384,
    "coalesce_enabled": true
  },
  "operations": [
    {"op": "SEND", "data_hex": "48656c6c6f", "flags": ["MSG_MORE", "ZERO_COPY"]},
    {"op": "SEND", "data_hex": "20576f726c64", "flags": []},
    {"op": "INJECT_LOOPBACK"}
  ]
}
```

---

## 출력 형식

표준 출력(`sys.stdout`)으로 공백 없는 압축 JSON(`separators=(',', ':')`)을 출력합니다:
```json
{
  "execution_log": [
    {"op": "SEND", "result": {"status": "BUFFERED", "pending_bytes": 5}},
    {"op": "SEND", "result": {"status": "SENT", "records_emitted": 1}},
    {"op": "INJECT_LOOPBACK", "result": {"delivered_records": 1, "pending_rx_bytes": 0, "status": "PROCESSED"}}
  ],
  "final_status": {
    "cipher_suite": "AES_128_GCM",
    "offload_mode": "DEVICE",
    "performance": {
      "estimated_cpu_cycles": 5,
      "hardware_offload_savings_pct": 88.5
    },
    "rx_delivered_plaintext_hex": "48656c6c6f20576f726c64",
    "rx_stats": {
      "mac_errors": 0,
      "payload_bytes": 11,
      "pending_buffer_bytes": 0,
      "records_received": 1,
      "wire_bytes": 33
    },
    "socket_state": "ACTIVE",
    "tls_version": "TLS_1_3",
    "tx_records_summary": [
      {
        "content_type": "APPLICATION_DATA",
        "payload_len": 11,
        "seq": 0,
        "tag_hex": "...",
        "wire_len": 33,
        "zero_copy": true
      }
    ],
    "tx_stats": {
      "overhead_ratio": 3.0,
      "payload_bytes": 11,
      "records_sent": 1,
      "wire_bytes": 33,
      "zero_copy_bytes": 11
    }
  }
}
```
