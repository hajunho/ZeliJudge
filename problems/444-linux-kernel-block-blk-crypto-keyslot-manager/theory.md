# Theory #444: 리눅스 커널 블록 레이어 & 스토리지 보안: block/blk-crypto.c 인라인 암호화 및 키슬롯 관리 이론

## 1. 소프트웨어 암호화의 I/O 절벽과 인라인 하드웨어 암호화

스토리지 보안에서 데이터 안정성을 보장하기 위해 저장 데이터 암호화(Data-at-Rest Encryption)는 필수적입니다.
전통적인 리눅스 암호화 계층인 `dm-crypt`(Device Mapper Crypt)는 커널 공간에서 CPU를 이용해 페이지 데이터를 암/복호화합니다.

그러나 초당 수백만 IOPS와 7GB/s 이상의 처리량을 내는 현대 PCIe 4.0/5.0 NVMe SSD 및 UFS 3.1 모바일 스토리지 환경에서:
1. **CPU 사이클 고갈**: 7GB/s 쓰기 스트림을 CPU가 AES-256-XTS로 처리하려면 고성능 코어 8~12개가 100% 소진됩니다.
2. **바운스 버퍼 메모리 복사**: 원본 메모리가 수정되는 레이스를 방지하기 위해 임시 바운스 페이지(Bounce Pages)를 할당하여 복사한 뒤 암호화해야 하므로 메모리 대역폭이 2배로 낭비됩니다.
3. **P99 레이턴시 스파이크**: 암호화 커널 워커 스레드의 컨텍스트 스위칭 지연으로 인해 스토리지 I/O 지연 시간이 50µs에서 수 밀리초로 악화됩니다.

---

## 2. blk-crypto 아키텍처와 인라인 엔진(Inline Encryption Engine)

리눅스 커널 5.8에서 도입된 **`blk-crypto` (`block/blk-crypto.c`)**는 물리 스토리지 컨트롤러 ASIC 내부의 하드웨어 암호화 엔진(IEE)을 직접 제어합니다:

```
[ Application / fscrypt write() ]
                │
                ▼
[ bio with struct bio_crypt_ctx attached ] (key_id, AES_256_XTS, DUN)
                │
                ▼
[ blk-crypto Keyslot Manager ] ──► Programs Key into HW Keyslot (SRAM)
                │
                ▼ (bio passed directly to NVMe DMA, Zero-Copy!)
[ PCIe Controller ASIC ]
  DMA reads plaintext from Host RAM ──► [ Hardware Crypto Core ] ──► Writes Ciphertext to NAND Flash!
```

### (1) 데이터 단위 번호 (DUN: Data Unit Number)의 중요성
XTS 모드와 같은 블록 암호화는 암호 블록의 위치마다 고유한 초기화 벡터(IV) 또는 트윅(Tweak)을 필요로 합니다.
`blk-crypto`는 각 블록의 논리 섹터 오프셋으로부터 64비트 정수 DUN을 유도합니다:
$$\text{DUN} = \frac{\text{sector} \times 512}{\text{data\_unit\_size}}$$
하드웨어 암호화 코어는 섹터 데이터를 회선으로 읽어 들이는 동안 이 DUN을 트윅으로 삼아 온더플라이(On-the-fly)로 암호화하므로, 별도의 소프트웨어 IV 계산 및 데이터 복사가 완전히 불필요합니다.

---

## 3. 한정된 하드웨어 키슬롯(Hardware Keyslots)과 LRU 동적 관리

하드웨어 암호화 엔진의 물리적 한계는 **고속 온칩 SRAM 키슬롯의 개수가 제한적(보통 16~64개)**이라는 점입니다.
엔터프라이즈 멀티테넌트 컨테이너 환경이나 안드로이드 FBE(File-Based Encryption)에서는 수천 개의 사용자 키가 동시에 공존합니다.

`blk-crypto`는 이를 해결하기 위해 가상 메모리 페이징과 유사한 **키슬롯 캐싱 및 LRU 축출(Eviction)** 알고리즘을 수행합니다:

### (1) 참조 카운트(`refcount`) 기반 동시성 안전 보장
- I/O 요청이 제출되어 특정 키슬롯을 점유하면 `slot->refcount`가 1 증가합니다.
- 물리 하드웨어 DMA가 완료되어 `bio_endio()`가 호출될 때 `slot->refcount`가 1 감소합니다.
- **불변식**: `slot->refcount > 0`인 키슬롯은 현재 물리 컨트롤러가 해당 슬롯의 키로 DMA 암호화를 진행 중이므로 **절대로 축출(Eviction)하거나 키를 덮어써서는 안 됩니다**.

### (2) LRU 축출 정책 (Least Recently Used Eviction)
모든 키슬롯이 사용 중이지만 일부 슬롯의 `refcount`가 0인 경우:
- `last_used_timestamp`가 가장 오래된 슬롯을 선별하여 기존 키를 무효화하고 새로운 키를 하드웨어에 프로그래밍합니다.

### (3) 소프트웨어 폴백 가드 (`blk-crypto-fallback`)
모든 키슬롯이 현재 활성 I/O에 의해 점유되어(`refcount > 0`) 가용 키슬롯이 단 하나도 없는 극단적인 부하 상황에서는:
- 커널은 I/O를 블록시키거나 실패 처리하는 대신, 해당 bio를 백그라운드 소프트웨어 암호화 워커 풀(`blk-crypto-fallback`)로 전달하여 소프트웨어로 암호화한 뒤 전송합니다.
- 이를 통해 시스템은 가용 하드웨어 자원을 100% 활용하면서도 결코 I/O 데드락이나 기아 상태에 빠지지 않는 무결성을 달성합니다.
