# Linux Kernel XFRM (Transform / IPsec) 프레임워크: SPD/SAD 상태 머신, ESP 캡슐화 및 RFC 4303 안티 리플레이 슬라이딩 윈도우 엔진

## 문제 설명

기업 엔터프라이즈 하이브리드 클라우드, 금융망, Kubernetes 컨테이너 네트워크(Calico, Cilium IPsec 모드)에서 데이터 플레인의 기밀성과 무결성을 보장하기 위해 리눅스 커널의 **XFRM(Transform / IPsec)** 서브시스템(`net/xfrm/`)이 사용됩니다.

XFRM 프레임워크는 라우팅 계층(`dst_entry`)과 통합되어 동작하며, 다음 두 가지 핵심 데이터베이스로 트래픽을 제어합니다:
- **보안 정책 데이터베이스 (SPD - Security Policy Database, `xfrm_policy.c`)**:
  - 어떤 패킷을 암호화(`ALLOW + tmpl_spi`), 통과(`ALLOW`), 또는 즉시 폐기(`BLOCK`)할 것인지를 패킷 방향(`OUT`/`IN`), 소스/목적지 서브넷(CIDR), 프로토콜로 규정합니다.
- **보안 연관 데이터베이스 (SAD - Security Association Database, `xfrm_state.c`)**:
  - 특정 IPsec 터널의 암호화 알고리즘, 보안 파라미터 색인(SPI - Security Parameters Index), 시퀀스 번호(Seq), 안티 리플레이 슬라이딩 윈도우(Replay Window), 수명(Lifetime) 등 런타임 암호 문맥을 유지합니다.

```
       [ Outbound Path: Plaintext Packet ]
                        │
                        ▼
       [ 1. SPD Lookup: Direction OUT, CIDR Match ]
         ├── Action: BLOCK ─────────────> DROP (POLICY_DISCARD)
         ├── Action: ALLOW (No SPI) ────> Forward Plaintext
         └── Action: ALLOW (tmpl_spi) ──> [ 2. SAD Lookup (xfrm_state) ]
                                                │
                                                ▼
                                   [ 3. ESP Encapsulation ]
                                     - Sequence Number 증가 (+1)
                                     - ESP Overhead: SPI + Seq + IV + Pad + ICV
                                     - Lifetime 갱신 (Soft Rekey / Hard Drop)
                                                │
                                                ▼
                                   [ IPsec ESP Ciphertext Packet ]

       [ Inbound Path: IPsec ESP Packet ]
                        │
                        ▼
       [ 1. SAD Lookup: SPI, Destination IP ]
                        │
                        ▼
       [ 2. Anti-Replay Sliding Window (RFC 4303) ]
         ├── Seq <= 0 ──────────────────> DROP (REPLAY_ERROR_SEQ_ZERO)
         ├── Seq < (Highest - Window) ──> DROP (REPLAY_ERROR_OUTSIDE_WINDOW)
         ├── Duplicate Bit Set ─────────> DROP (REPLAY_ERROR_DUPLICATE_PACKET)
         └── Normal Seq ────────────────> Advance Window & Set Bit
                        │
                        ▼
       [ 3. Cryptographic ICV / HMAC Verification ]
         ├── Tampered / Bit Corruption ─> DROP (ICV_VERIFICATION_FAILED)
         └── Authenticated ─────────────> Decapsulate & Forward Plaintext
```

본 문제는 리눅스 커널 XFRM 서브시스템의 **SPD 정책 평가, SAD 상태 머신, RFC 4303 ESP 패킷 캡슐화, 안티 리플레이 슬라이딩 윈도우 및 암호 무결성 검증 파이프라인**을 정밀하게 에뮬레이션하는 엔진을 구현하는 것입니다.

---

## 핵심 엔진 아키텍처 및 요구사항

### 1. 보안 정책 데이터베이스 (SPD) 평가
- 패킷의 방향(`OUT`/`IN`), 소스 IP(`src_ip`), 목적지 IP(`dst_ip`), 프로토콜(`proto`)을 정책 CIDR 범위(`src_cidr`, `dst_cidr`)와 대조합니다.
- 일치하는 정책이 없으면 평문 통과(`FORWARD_PLAINTEXT`, `reason = "NO_MATCHING_SPD_POLICY"`).
- `action == "BLOCK"`인 경우 즉시 패킷을 폐기(`DROP`, `reason = "POLICY_DISCARD"`).
- `action == "ALLOW"`이면서 `tmpl_spi`가 없으면 평문 통과(`FORWARD_PLAINTEXT`, `reason = "POLICY_ALLOW_PASSTHROUGH"`).

### 2. 보안 연관 (SAD) 런타임 및 수명(Lifetime) 관리
- `tmpl_spi`에 해당하는 SA가 SAD에 존재하지 않으면 `DROP`, `reason = "SAD_STATE_NOT_FOUND"`.
- **수명 검사 (Bytes Lifetime)**:
  - $	ext{current\_bytes} + 	ext{payload} > 	ext{lifetime.hard}$인 경우 강제 만료로 폐기(`DROP`, `reason = "SA_HARD_EXPIRED"`).
  - 누적 바이트가 `lifetime.soft` 이상이 되면 키 갱신 경고 플래그(`soft_rekey_alert = true`)를 발동합니다.

### 3. 아웃바운드 ESP 캡슐화 (Outbound Path)
- SA의 시퀀스 번호를 1 증가시킵니다: $	ext{seq} = 	ext{current\_seq} + 1$.
- **RFC 4303 ESP 오버헤드 계산**:
  - $	ext{SPI}(4	ext{B}) + 	ext{Seq}(4	ext{B}) + 	ext{IV}(8	ext{B}) + 	ext{Payload} + 	ext{Pad}(0..3	ext{B}) + 	ext{PadLen}(1	ext{B}) + 	ext{NextHdr}(1	ext{B}) + 	ext{ICV}(16	ext{B})$
  - 패딩 바이트: $	ext{pad\_len} = (4 - ((	ext{payload} + 2) mod 4)) mod 4$
  - 최종 ESP 패킷 크기(`esp_packet_size`)를 산출하고 `ESP_ENCAPSULATED` 상태로 반환합니다.

### 4. 인바운드 역캡슐화 및 RFC 4303 안티 리플레이 슬라이딩 윈도우 (Inbound Path)
- 인바운드 패킷의 `seq`를 SA의 리플레이 윈도우(`replay_window_size`) 및 수신 최고 시퀀스(`highest_seq_seen`)와 대조합니다:
  - $	ext{seq} \le 0$: `DROP`, `reason = "REPLAY_ERROR_SEQ_ZERO"`.
  - $	ext{seq} > 	ext{highest}$: 최고 시퀀스를 갱신하고 비트맵에 추가한 뒤, 윈도우 좌측 경계($	ext{highest} - 	ext{window}$)보다 오래된 항목을 제거.
  - $	ext{seq} \le 	ext{highest}$:
    - $	ext{highest} - 	ext{seq} \ge 	ext{window}$: 윈도우 범위를 벗어난 오래된 패킷 $ightarrow$ `DROP`, `reason = "REPLAY_ERROR_OUTSIDE_WINDOW"`.
    - 이미 비트맵에 존재하는 `seq`: 중복 재생 패킷 $ightarrow$ `DROP`, `reason = "REPLAY_ERROR_DUPLICATE_PACKET"`.
    - 윈도우 내부 미수신 패킷: 비트맵에 등록.
- **ICV 무결성 검증**:
  - `is_tampered == true`인 경우 암호 무결성 위조로 판정하여 폐기(`DROP`, `reason = "ICV_VERIFICATION_FAILED"`).
  - 정상 패킷은 역캡슐화되어 원본 페이로드 바이트(`recovered_payload_bytes`)를 반환(`ESP_DECAPSULATED`).

---

## 입력 형식

JSON 문자열이 표준 입력(`stdin`)으로 주어집니다:

```json
{
  "spd_policies": [
    {
      "policy_id": "SPD_OUT",
      "dir": "OUT",
      "src_cidr": "10.0.1.0/24",
      "dst_cidr": "10.0.2.0/24",
      "proto": "TCP",
      "action": "ALLOW",
      "tmpl_spi": 1001
    }
  ],
  "sad_states": [
    {
      "spi": 1001,
      "mode": "TUNNEL",
      "current_seq": 0,
      "replay_window_size": 64,
      "lifetime_bytes": {"soft": 500, "hard": 1000, "current": 0}
    }
  ],
  "packets": [
    {
      "pkt_id": "P_OUT_01",
      "dir": "OUT",
      "src_ip": "10.0.1.10",
      "dst_ip": "10.0.2.20",
      "proto": "TCP",
      "payload_bytes": 100
    }
  ]
}
```

---

## 출력 형식

처리된 패킷별 결과와 XFRM 집계 메트릭을 JSON 형태로 표준 출력(`stdout`)에 공백 없이 출력합니다:

```json
{
  "engine": "linux_kernel_xfrm_ipsec",
  "metrics": {
    "total_packets_processed": 1,
    "esp_encapsulated": 1,
    "esp_decapsulated": 0,
    "replay_drops": 0,
    "crypto_integrity_drops": 0,
    "policy_blocks": 0,
    "active_sads": 1
  },
  "verdict": "XFRM_IPSEC_TUNNEL_SECURE",
  "results": [
    {
      "pkt_id": "P_OUT_01",
      "status": "ESP_ENCAPSULATED",
      "spi": 1001,
      "seq": 1,
      "esp_packet_size": 136,
      "soft_rekey_alert": false
    }
  ]
}
```

---

## 판정 규칙 (`verdict`)

1. 리플레이 드롭(`replay_drops > 0`) 또는 암호학적 위조 드롭(`crypto_integrity_drops > 0`)이 1건 이상 발생한 경우:
   `"REPLAY_OR_CRYPTO_ATTACK_MITIGATED"`
2. 정책 차단(`policy_blocks > 0`)이 발생한 경우:
   `"XFRM_POLICY_VIOLATION_BLOCKED"`
3. 정상적으로 캡슐화/역캡슐화가 수행된 경우:
   `"XFRM_IPSEC_TUNNEL_SECURE"`
4. 그 외:
   `"XFRM_ROUTING_PASSIVE"`
