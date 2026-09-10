# 문제 463: Linux Kernel AF_ALG 암호화 소켓 인터페이스 및 하드웨어 가속 오프로드 엔진

## 문제 설명

리눅스 커널의 **`AF_ALG` (Algorithm Sockets)**(`crypto/af_alg.c`, `crypto/algif_aead.c`, `crypto/algif_hash.c`, `include/uapi/linux/if_alg.h`)는 사용자 공간 애플리케이션(OpenSSL afalg 엔진, QEMU, LUKS/dm-crypt, WireGuard)이 커널 내부의 암호화 프레임워크(Crypto API) 및 하드웨어 가속기(Intel QAT, ARMv8 Crypto Extensions, AMD CCP, AES-NI)를 표준 BSD 소켓 인터페이스(`socket`, `bind`, `setsockopt`, `accept`, `sendmsg`, `recvmsg`)를 통해 직접 활용할 수 있도록 지원하는 커널 서브시스템입니다.

전통적인 `/dev/crypto` 디바이스 노드 방식과 달리, `AF_ALG`는 커널의 파일 디스크립터 및 제어 메시지(Control Messages, `cmsg`) 파이프라인을 활용하여 고성능 암호화 세션을 비동기적으로 다중화할 수 있습니다:

```
+-----------------------------------------------------------------------------------------+
|                  Linux AF_ALG Cryptographic Socket Lifecycle                            |
+-----------------------------------------------------------------------------------------+

 [User Space Application]                                    [Kernel Crypto Architecture]
      |                                                                 |
      | 1. socket(AF_ALG, SOCK_SEQPACKET, 0)                            |
      |    bind(fd=3, {salg_type: "aead", salg_name: "gcm(aes)"})      |
      +---------------------------------------------------------------->| crypto_alloc_aead("gcm(aes)")
      | <--- SOCKET_BOUND                                               |
      |                                                                 |
      | 2. setsockopt(fd=3, SOL_ALG, ALG_SET_KEY, 256-bit key)          |
      +---------------------------------------------------------------->| crypto_aead_setkey()
      | <--- KEY_CONFIGURED                                             |
      |                                                                 |
      | 3. accept(fd=3) ---> returns operational conn_fd=4              |
      +---------------------------------------------------------------->| Allocates alg_ctx for session
      | <--- SESSION_ACCEPTED                                           |
      |                                                                 |
      | 4. sendmsg(conn_fd=4, [IV, AAD_len, AAD + Plaintext], ENCRYPT)  |
      +---------------------------------------------------------------->| Queues AEAD request
      |                                                                 |
      | 5. recvmsg(conn_fd=4)                                           |
      +---------------------------------------------------------------->| Executes hardware cipher:
      | <--- Returns Ciphertext + 16-byte Authentication Tag            |   Emits AEAD_ENCRYPTED
      |                                                                 |
      | 6. Tampered tag decryption attempt                              |
      +---------------------------------------------------------------->| Tag mismatch!
      | <--- EBADMSG_AUTH_FAILED (Integrity Violation!)                 |   auth_failures += 1
      v                                                                 v
```

### 지원 암호군 사양 (`SUPPORTED_ALGS`)
1. **`hash`**:
   - `"sha256"`: 32바이트 다이제스트 (키 불필요)
   - `"sha512"`: 64바이트 다이제스트 (키 불필요)
   - `"hmac(sha256)"`: 32바이트 다이제스트 (`key_required = True`)
2. **`skcipher`**:
   - `"cbc(aes)"`: 허용 키 길이 `[16, 24, 32]`바이트, IV 16바이트
   - `"ctr(aes)"`: 허용 키 길이 `[16, 24, 32]`바이트, IV 16바이트
3. **`aead`**:
   - `"gcm(aes)"`: 허용 키 길이 `[16, 24, 32]`바이트, IV 12바이트, 인증 태그 길이 16바이트

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:
- `operations`: 일련의 소켓 연산 배열.

지원되는 연산:
1. `{"op": "BIND_SOCKET", "fd": int, "salg_type": str, "salg_name": str}`
   - 소켓에 암호화 알고리즘을 바인딩합니다. 미지원 시 `ENOENT_NO_CIPHER`, 중복 fd 시 `EBADF_DUPLICATE_FD`.
2. `{"op": "SET_KEY", "fd": int, "key_hex": str}`
   - 리스너 소켓에 암호화 키를 설정합니다. 허용되지 않은 키 길이 시 `EINVAL_KEY_LEN`.
3. `{"op": "ACCEPT_SESSION", "listen_fd": int, "conn_fd": int}`
   - 암호화 실행 세션을 인스턴스화합니다. 키가 필수인데 설정되지 않은 경우 `ENOKEY_KEY_NOT_SET`.
4. `{"op": "SEND_MSG", "conn_fd": int, "data_hex": str, "cipher_op": "ENCRYPT"|"DECRYPT"|null, "iv_hex": str|null, "assoclen": int|null}`
   - 데이터 및 제어 파라미터(IV, AAD 길이, 연산 모드)를 소켓 버퍼에 기록합니다.
5. `{"op": "RECV_MSG", "conn_fd": int}`
   - 암호 연산을 수행하고 결과를 수신합니다.
   - `hash`: 다이제스트 출력 (`DIGEST_GENERATED`).
   - `skcipher`: 암호화/복호화 결과 출력 (`CIPHER_PROCESSED`).
   - `aead`:
     - 암호화: `Ciphertext + 16-byte Tag` 반환 (`AEAD_ENCRYPTED`).
     - 복호화: 태그 검증 실패 시 `EBADMSG_AUTH_FAILED` 및 `auth_failures` 카운트. 검증 성공 시 `AEAD_DECRYPTED`.
6. `{"op": "QUERY_STATE"}`
   - 활성 리스너/세션 수, 통계(`stats`)를 반환합니다.

---

## 출력 형식

표준 출력(stdout)으로 각 연산의 결과를 담은 JSON을 한 줄(compact)로 출력합니다:
```json
{"results": [...]}
```
