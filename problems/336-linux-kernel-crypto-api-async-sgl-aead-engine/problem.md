# 리눅스 커널 Crypto API (crypto/): 비동기 대칭/AEAD 암호 엔진, Scatterlist (SGL) 체이닝 및 하드웨어 가속기 오프로드

## 문제 설명

리눅스 커널의 **Crypto API (`crypto/`, `include/crypto/`)**는 네트워크 스택(IPsec, WireGuard, kTLS, MACsec), 스토리지 암호화(dm-crypt, fscrypt, ecryptfs), 무선 랜 보안(cfg80211, mac80211) 및 커널 보안 모듈(IMA/EVM, dm-verity)을 아우르는 핵심 암호화 하위 시스템입니다.

커널 환경은 유저스페이스와 달리 메모리가 연속적인 거대 버퍼로 존재하지 않고 비연속적인 페이지 단편(Page Fragments)이나 소켓 버퍼(`sk_buff` frags)로 나뉘어 전달되므로, Crypto API는 **Scatterlist (`struct scatterlist`, SGL)** 체이닝 구조를 통해 제로 카피(Zero-Copy) 암복호화를 수행합니다.

또한 CPU 부하를 경감하기 위해 소프트웨어 C 제네릭 구현, x86 AVX-512 / ARM Neon SIMD 가속, 그리고 전용 하드웨어 가속기(Intel QAT, NXP CAAM, ARM CryptoCell)를 **우선순위 계층(`cra_priority`)**과 **비동기 링 버퍼 큐잉(`-EINPROGRESS`, `-EBUSY`)** 메커니즘을 통해 유기적으로 결합합니다:

```
                  [ 사용자 공간 / 커널 서브시스템 (IPsec, dm-crypt, kTLS) ]
                                            │
                                            ▼
                  ┌──────────────────────────────────────────────────┐
                  │    Crypto API 변환 인스턴스 (crypto_aead / tfm)    │
                  │  - 알고리즘 매칭 & 드라이버 우선순위 선별 (cra_priority)│
                  └─────────────────────────┬────────────────────────┘
                                            │
                    ┌───────────────────────┴───────────────────────┐
                    │                                               │
           [ 동기 소프트웨어/SIMD ]                         [ 비동기 하드웨어 오프로드 ]
           - cra_priority: 100 ~ 400                      - cra_priority: 1000
           - 即時 연산 완료 (SUCCESS)                     - QAT / CAAM 링 버퍼 큐잉
                                                          - 여유 시: -EINPROGRESS
                                                          - 포화 시: -EBUSY (Backlog)
                                                          - 초과 시: -ENOSPC (Drop)
                                                                    │
                                                                    ▼
                                                          [ poll_completions / 인터럽트 ]
                                                          - 완료 콜백 호출 & 백로그 승격
```

리눅스 커널 Crypto API의 핵심 동작 규칙은 다음과 같습니다:

1. **드라이버 등록 및 우선순위 바인딩 (`cra_priority`)**:
   - 동일한 암호 알고리즘(예: `"gcm(aes)"`, `"chacha20-poly1305"`)에 대해 여러 드라이버가 등록될 수 있습니다:
     - 제네릭 C 구현 (`driver_type: "generic"`): `cra_priority = 100`
     - SIMD 벡터 가속 (`driver_type: "simd"`): `cra_priority = 300 ~ 400`
     - 하드웨어 가속기 (`driver_type: "hardware"`): `cra_priority = 1000`
   - 변환 인스턴스 할당 시 가장 높은 `cra_priority`를 가진 활성 드라이버가 자동 선택됩니다.

2. **비연속적 메모리 Scatterlist (SGL) 개더-스캐터 (Gather-Scatter)**:
   - 입력 데이터는 복수의 비연속 청크로 구성된 `src_sgl`로 주어지며, 각각 `offset`과 `length`를 가집니다.
   - 출력 또한 연속 버퍼가 아닌 목적지 SGL 템플릿(`dst_template`)의 각 슬롯 용량(`capacity`)에 맞추어 순차적으로 쪼개어 채워 넣는 스캐터링(Scatter) 방식으로 전개됩니다.

3. **AEAD (Authenticated Encryption with Associated Data) 패킷 구조**:
   - `assoclen`: 결합 데이터(Associated Authenticated Data, AAD)의 바이트 길이입니다 (예: IPsec SPI/시퀀스 번호, TLS 레코드 헤더). AAD는 암호화되지 않고 평문 그대로 유지되지만, 무결성 인증 태그 계산에는 반드시 포함됩니다.
   - `encrypt`: 입력에서 AAD를 보존하고, 본문(Payload)을 암호화하여 암호문(Ciphertext)을 생성한 뒤, AAD와 암호문을 대상으로 HMAC 인증 태그(`auth_tag`, 기본 16바이트)를 산출하여 출력 SGL로 스캐터링합니다.
   - `decrypt`: 입력에서 AAD와 암호문, 끝부분의 인증 태그를 분리합니다. AAD와 암호문으로부터 인증 태그를 재계산하여 전달받은 태그와 상수 시간(`hmac.compare_digest`)으로 대조합니다.
     - 태그가 일치하지 않으면 패킷 위변조로 간주하여 **`-EBADMSG` (ICV 불일치 오류)**를 반환하고 `auth_failures` 메트릭을 증가시킵니다.
     - 일치하면 복호화된 평문과 AAD를 결합하여 출력 SGL에 기록합니다.

4. **비동기 하드웨어 링 버퍼 큐잉 및 백로그 관리**:
   - 하드웨어 가속기 드라이버의 경우 요청이 즉시 완료되지 않고 링 버퍼에 비동기로 큐잉됩니다.
   - `active_queue` 공간이 남아있으면 큐에 진입하고 커널 표준 비동기 상태 코드인 **`-EINPROGRESS`**를 반환합니다.
   - `active_queue`가 꽉 찼지만 요청에 `may_backlog == true`가 설정되어 있고 `backlog_queue`에 공간이 있다면 백로그로 진입하고 **`-EBUSY`**를 반환합니다.
   - 두 큐가 모두 포화되었거나 `may_backlog == false`인 상태에서 큐가 차면 **`-ENOSPC`**를 반환하고 요청을 폐기합니다 (`queue_overflows += 1`).
   - `poll_completions` 연산이 호출되면 최대 `max_drain`개만큼의 활성 요청이 완료 처리되며, 백로그 큐에 대기 중이던 요청이 선입선출(FIFO) 순서로 활성 큐로 자동 승격(Promotion)됩니다.

본 문제에서는 이와 같은 리눅스 커널 Crypto API의 **SGL 기반 AEAD 암복호화, 드라이버 우선순위 선별, 인증 태그 검증 및 비동기 링 버퍼/백로그 오프로드 엔진**을 구현합니다.

---

## 입력 형식

표준 입력(stdin)으로 하나의 JSON 객체가 주어집니다.

```json
{
  "config": {
    "debug": false
  },
  "registered_algorithms": [
    {
      "alg_name": "gcm(aes)",
      "driver_name": "aes-gcm-generic",
      "cra_priority": 100,
      "driver_type": "generic",
      "authsize": 16
    },
    {
      "alg_name": "gcm(aes)",
      "driver_name": "qat-hardware-engine",
      "cra_priority": 1000,
      "driver_type": "hardware",
      "authsize": 16
    }
  ],
  "hardware_accelerator": {
    "enabled": true,
    "queue_capacity": 2,
    "backlog_capacity": 2
  },
  "crypto_requests": [
    {
      "req_id": "REQ_01",
      "op_type": "encrypt",
      "alg_name": "gcm(aes)",
      "assoclen": 8,
      "key_hex": "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff",
      "iv_hex": "1234567890abcdef12345678",
      "may_backlog": true,
      "src_sgl": [
        {"offset": 0, "length": 8, "data": "IPSEC_HD"},
        {"offset": 0, "length": 16, "data": "TOP_SECRET_DATA_"}
      ],
      "dst_template": [
        {"sg_id": "frag0", "capacity": 32},
        {"sg_id": "frag1", "capacity": 64}
      ]
    },
    {
      "req_id": "POLL_01",
      "op_type": "poll_completions",
      "max_drain": 1
    }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 다음 스키마를 갖는 단일 JSON 객체를 압축 공백 없이 출력합니다 (`json.dumps(..., separators=(',', ':'))`).

```json
{
  "request_results": [
    {
      "req_id": "REQ_01",
      "op": "encrypt",
      "status": "EINPROGRESS",
      "driver_name": "qat-hardware-engine",
      "driver_type": "hardware",
      "cra_priority": 1000,
      "is_async_queued": true,
      "aad_length": 8,
      "ciphertext_length": 32,
      "auth_tag": "3a7b...",
      "dst_sgl": [
        {"sg_id": "frag0", "capacity": 32, "length": 32, "data": "..."},
        {"sg_id": "frag1", "capacity": 64, "length": 24, "data": "..."}
      ]
    },
    {
      "req_id": "POLL_01",
      "op": "poll_completions",
      "status": "SUCCESS",
      "drained_count": 1,
      "completed_requests": ["REQ_01"],
      "remaining_active": 0,
      "remaining_backlog": 0
    }
  ],
  "crypto_subsystem_metrics": {
    "sync_completed": 0,
    "async_queued": 1,
    "backlog_queued": 0,
    "queue_overflows": 0,
    "auth_failures": 0,
    "total_bytes_processed": 16
  },
  "hardware_engine_status": {
    "active_queue_depth": 0,
    "backlog_queue_depth": 0,
    "is_throttled": false
  }
}
```

---

## 제약 사항

- $1 \le |\text{registered\_algorithms}| \le 20$
- $1 \le |\text{crypto\_requests}| \le 50$
- 키 크기: 16, 24, 32바이트 (hex 32, 48, 64자)
- IV 크기: 12바이트 (hex 24자)
- 인증 태그 크기: 기본 16바이트 (hex 32자)
- 암복호화 연산: SHA-256 및 HMAC 기반 결정론적 의사 난수 키스트림 생성
- 시간 복잡도: 요청당 $O(L + S)$ 이내 (여기서 $L$은 바이트 길이, $S$는 SGL 엔트리 수)
- 공간 복잡도: $O(L + S)$ 이내
