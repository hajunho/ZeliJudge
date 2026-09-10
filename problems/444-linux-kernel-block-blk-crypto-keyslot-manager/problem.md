# Problem #444: 리눅스 커널 블록 레이어 & 스토리지 보안: block/blk-crypto.c 인라인 하드웨어 암호화(blk-crypto) 키슬롯(Keyslot) 동적 매핑 및 LRU 축출 엔진

## 🌟 개요 (Executive Summary)
현대 고속 NVMe PCIe 4.0/5.0 SSD 및 모바일 UFS 3.1+ 스토리지 환경에서, `dm-crypt`나 CPU 소프트웨어 암호화(AES-NI)는 기가바이트 단위의 I/O를 처리할 때 막대한 CPU 오버헤드와 메모리 바운싱, L3 캐시 오염을 유발하여 스토리지 대역폭을 50% 이상 잠식합니다.
이를 극복하기 위해 최신 엔터프라이즈 스토리지 컨트롤러와 리눅스 커널 5.8+은 **인라인 하드웨어 암호화 엔진 (Inline Encryption Engine / `block/blk-crypto.c`, `include/linux/blk-crypto.h`)**을 도입하였습니다.

인라인 암호화는 PCIe 버스 상에서 데이터가 DMA 전송되는 순간 컨트롤러 ASIC 내부에서 하드웨어 와이어-스피드로 즉시 암/복호화를 수행합니다.
그러나 스토리지 컨트롤러 하드웨어 내부의 고속 온칩 SRAM 키슬롯(Hardware Keyslots)은 물리적 비용으로 인해 보통 **16개~64개** 수준으로 극히 제한되어 있습니다.
반면 사용자 공간(fscrypt, ext4, f2fs, 암호화 컨테이너)은 수천 개의 독립된 파일 키(`key_id`)를 동시에 사용하므로, 한정된 하드웨어 키슬롯을 동적으로 관리하는 정교한 커널 매니저가 필수적입니다:
- **`bio_crypt_ctx` 컨텍스트 부착**: 파일시스템은 I/O 요청(`bio`)마다 암호화 키 식별자, 암호 알고리즘(`AES_256_XTS`), 그리고 섹터 주소 기반 64비트 데이터 단위 번호(DUN: Data Unit Number)를 부여합니다.
- **키슬롯 캐시 히트 (Keyslot Hit)**: 요청된 키가 이미 하드웨어 키슬롯에 프로그래밍되어 있다면 $O(1)$ 속도로 해당 슬롯의 참조 카운트(`refcount`)를 증가시키고 즉시 하드웨어 DMA로 전달합니다.
- **빈 슬롯 할당 (Keyslot Allocation)**: 빈 슬롯이 존재할 경우 새 키를 하드웨어 레지스터에 프로그래밍하고 바인딩합니다.
- **LRU 키슬롯 축출 (LRU Keyslot Eviction)**: 모든 슬롯이 가득 찼다면, 현재 진행 중인 I/O가 없는(`refcount == 0`) 슬롯 중 가장 오랫동안 사용되지 않은(LRU) 슬롯을 선별하여 기존 키를 내리고 새 키를 덮어씁니다.
- **소프트웨어 폴백 가드 (`blk-crypto-fallback`)**: 모든 하드웨어 키슬롯이 동시 I/O에 의해 점유되어(`refcount > 0`) 축출이 불가능한 극한의 경합 상황에서는 I/O 데드락을 방지하기 위해 커널 백그라운드 소프트웨어 암호화 워커(`FALLBACK_SW_CRYPT`)로 우회 처리합니다.
- **명시적 키 파기 (`EVICT_KEY_EXPLICIT`)**: 파일이 닫히거나 키링에서 키가 파기될 때, 참조 카운트가 0인 키슬롯의 메모리를 제로화(Zeroize)하여 부채널 공격 및 키 유출을 원천 방어합니다.

본 문제에서는 리눅스 커널 `block/blk-crypto.c`의 인라인 암호화 키슬롯 매핑, LRU 축출, DUN 산출, 소프트웨어 폴백 및 보안 키 파기 엔진을 시뮬레이션합니다.

---

## 🏗️ 아키텍처 및 시스템 흐름도 (System Architecture)

```
        [ Filesystem submits bio with bio_crypt_ctx ]
                             │
            Compute DUN = (sector * 512) // data_unit_size
                             │
                             ▼
         [ blk-crypto Hardware Keyslot Manager ]
                             │
                Is key_id already in a Keyslot?
               ┌─────────────┴─────────────┐
              Yes                          No
               │                           │
               ▼                           ▼
        [ KEYSLOT_HIT ]            Is there an empty slot?
        slot.refcount++            ┌───────┴───────┐
        Update timestamp          Yes              No
        Mode = HW_KEYSLOT          │               │
                                   ▼               ▼
                       [ KEYSLOT_ALLOCATED ]  Any slot with refcount == 0?
                       Program key to slot            ┌───────┴───────┐
                       slot.refcount = 1             Yes              No
                       Mode = HW_KEYSLOT              │               │
                                                      ▼               ▼
                                            [ KEYSLOT_EVICTED_LRU ] [ All Slots Busy ]
                                            Evict oldest unused slot      │
                                            Program new key to slot       ├─ Fallback Enabled?
                                            slot.refcount = 1             │  Mode = SW_FALLBACK
                                            Mode = HW_KEYSLOT             │
                                                                          └─ Fallback Disabled?
                                                                             Return EBUSY!
 ─────────────────────────────────────────────────────────────────────────────
        [ COMPLETE_BIO_CRYPT ] -> slot.refcount--
        [ EVICT_KEY_EXPLICIT ] -> Zeroize slot if refcount == 0
```

---

## ⚙️ I/O 데이터 규격 (Input/Output Specifications)

### 1. 입력 JSON 구조
```json
{
  "config": {
    "num_keyslots": 4,
    "supported_modes": ["AES_256_XTS"],
    "data_unit_size": 4096,
    "software_fallback_enabled": true
  },
  "trace": [
    {"op": "SUBMIT_BIO_CRYPT", "bio_id": "B1", "key_id": "KEY_1", "sector": 0, "num_sectors": 8, "timestamp": 10},
    {"op": "SUBMIT_BIO_CRYPT", "bio_id": "B2", "key_id": "KEY_1", "sector": 8, "num_sectors": 8, "timestamp": 15},
    {"op": "COMPLETE_BIO_CRYPT", "bio_id": "B1"},
    {"op": "EVICT_KEY_EXPLICIT", "key_id": "KEY_1"},
    {"op": "GET_STATS"}
  ]
}
```

### 2. 필드 정의
- `config`:
  - `num_keyslots` (int, default=4): 하드웨어 지원 키슬롯 총 개수.
  - `supported_modes` (list of str): 하드웨어 지원 암호화 모드 목록.
  - `data_unit_size` (int, default=4096): DUN 산출 단위 (바이트).
  - `software_fallback_enabled` (bool, default=true): 키슬롯 포화 시 소프트웨어 암호화 폴백 허용 여부.
- `trace` 명령어:
  1. `SUBMIT_BIO_CRYPT`:
     - `bio_id` (str): I/O 요청 식별자.
     - `key_id` (str): 암호화 키 식별자.
     - `crypto_mode` (str, default="AES_256_XTS"): 암호 알고리즘.
     - `sector` (int): 시작 섹터 번호.
     - `num_sectors` (int): 섹터 개수 (512B/섹터).
     - `timestamp` (int): 요청 타임스탬프 (LRU 추적용).
  2. `COMPLETE_BIO_CRYPT`:
     - `bio_id` (str): 완료된 I/O 식별자. 해당 키슬롯의 `refcount` 1 감소.
  3. `EVICT_KEY_EXPLICIT`:
     - `key_id` (str): 키링에서 명시적 파기된 키 식별자. 미사용 중일 경우 제로화.
  4. `GET_STATS`:
     - 키슬롯 히트, 할당, LRU 축출, 폴백 횟수 및 슬롯 상세 상태 조회.

### 3. 출력 JSON 구조
```json
{
  "events": [
    {
      "op": "SUBMIT_BIO_CRYPT",
      "bio_id": "B1",
      "mode": "HW_KEYSLOT",
      "slot_id": 0,
      "dun": 0,
      "status": "KEYSLOT_ALLOCATED"
    },
    ...
  ],
  "summary": {
    "keyslot_hits": 1,
    "keyslot_allocs": 1,
    "keyslot_evictions": 0,
    "fallback_sw_crypt": 0,
    "total_bios_processed": 2,
    "total_bytes_encrypted": 8192,
    "active_bios_in_flight": 1
  }
}
```
