# 문제 251 이론: Linux dm-crypt XTS 비가역성 한계, dm-integrity AEAD 인증 태그 및 온디스크 저널링 아키텍처

---

## 1. 전체 디스크 암호화(FDE)와 인증 암호화(AEAD)의 괴리

현대 리눅스 블록 디바이스 암호화 표준(LUKS, dm-crypt)은 섹터 단위 대칭키 암호화 모드로 **AES-XTS (`aes-xts-plain64`)**를 사용합니다.

```
+--------------------------------------------------------------------+
| AES-XTS Encryption Mode                                            |
|                                                                    |
| C = AES_K1(P ^ T) ^ T,  where T = AES_K2(Sector_Number) * alpha^j  |
+--------------------------------------------------------------------+
```

### AES-XTS의 근본적인 한계:
AES-XTS는 뛰어난 랜덤 읽기/쓰기 성능과 섹터 위치(IV) 격리를 제공하지만, **메시지 인증 코드(MAC)가 전혀 포함되어 있지 않은 비인증 암호화(Unauthenticated Encryption)** 방식입니다.
- **가변성(Malleability)**: 디스크 물리 매체의 비트가 손상되거나 공격자가 암호문 $C$를 $C'$로 조작하더라도, AES-XTS 복호화기는 아무런 에러 없이 복호화를 마칩니다.
- 단지 해당 16바이트 블록의 평문이 의사 난수(Pseudorandom garbage)로 복호화될 뿐입니다.
- 운영체제나 파일시스템 입장에서는 `/etc/shadow`, 커널 바이너리, 데이터베이스 레코드의 비트가 뒤틀렸다는 사실을 전혀 인지하지 못한 채 무결성이 파괴된 상태로 실행을 계속하게 됩니다.

---

## 2. dm-integrity 아키텍처와 섹터별 태그 관리

리눅스 커널 4.12부터 도입된 **`dm-integrity`**는 블록 계층에서 진정한 데이터 무결성과 진위성을 보장하기 위해 섹터별 암호학적 인증 태그를 저장하는 계층입니다.

```
+-------------------------------------------------------------+
| Physical Sector Layout with dm-integrity                    |
|                                                             |
| [ Sector 0: 4096B Data ] ---> [ Tag 0: 32B HMAC-SHA256 ]    |
| [ Sector 1: 4096B Data ] ---> [ Tag 1: 32B HMAC-SHA256 ]    |
|                                                             |
| [ Dedicated On-Disk Journal Area: WAL for Data + Tags ]     |
+-------------------------------------------------------------+
```

### 무결성 검증 프로세스:
1. `WRITE_BIO`: 데이터 섹터가 암호화된 후, $Tag = 	ext{HMAC}(Sector, Ciphertext)$를 계산하여 온디스크 저널에 기록한 뒤 물리 미디어에 영구 기록합니다.
2. `READ_BIO`: 디스크에서 암호문과 태그를 동시에 읽어와 커널 내부에서 HMAC을 재계산합니다. 만약 1비트라도 불일치하면 커널은 해당 bio에 즉시 **`-EIO` (I/O Error)**를 반환하여 손상된 데이터의 유입을 물리적으로 차단합니다.

---

## 3. 리플레이 공격(Replay Attack)과 단조 카운터

순수한 섹터 기반 MAC(HMAC-SHA256)만 사용할 경우, 공격자는 과거 시점에 기록된 정당한 암호문 섹터와 정당한 태그를 통째로 캡처한 뒤 나중에 덮어쓸 수 있습니다.
- 암호문과 태그가 쌍으로 일치하므로 `dm-integrity`는 변조를 감지하지 못합니다.
- **해결책**:
  - 각 섹터 태그 계산에 단조 증가 시퀀스 번호(Monotonic Counter / Journal Epoch)를 바인딩하여, 과거 시퀀스의 데이터가 재주입되는 리플레이 공격을 완벽하게 탐지하고 차단합니다.

---

## 4. 온디스크 저널링 모드와 쓰기 스톨(Write Stall) 튜닝

`dm-integrity`는 크래시 일관성(Crash Consistency)을 위해 데이터와 태그를 원자적으로 기록해야 합니다.

### (1) Journal 모드 (기본값)
- 모든 쓰기 요청이 먼저 온디스크 저널(Journal Ring)에 커밋된 후 실제 데이터 영역으로 복사됩니다(이중 쓰기).
- **성능 병목**: 대량의 순차 쓰기가 발생할 때 저널 링 버퍼가 워터마크(기본 80%)에 도달하면, 커널은 신규 쓰기 bio를 일시 중단(`journal write stall`)시키고 저널을 디스크에 비우는 동기식 플러시 작업을 수행합니다.
- 이로 인해 I/O 지연 시간이 10ms에서 2000ms 이상으로 급증합니다.

### (2) Bitmap 모드 (고성능 대안)
- 동기식 저널 대신 더티 섹터를 추적하는 인메모리/온디스크 비트맵을 사용합니다.
- 데이터와 태그를 디스크에 직접 쓰므로 이중 쓰기 오버헤드와 저널 고갈 스톨이 발생하지 않습니다.
- 비정상 크래시 후 재부팅 시 비트맵의 더티 영역만 재계산하므로 고성능 워크로드에 최적입니다.

---

## 5. 엔터프라이즈 프로덕션 셋업 가이드 (LUKS2 + dm-integrity)

```bash
# 1. dm-integrity와 dm-crypt가 통합된 LUKS2 디바이스 포맷
cryptsetup luksFormat /dev/nvme0n1p2     --type luks2     --cipher aes-xts-plain64     --integrity hmac-sha256     --sector-size 4096

# 2. 고성능 비트맵 모드로 오픈
cryptsetup open /dev/nvme0n1p2 secure_storage     --integrity-no-journal
```
