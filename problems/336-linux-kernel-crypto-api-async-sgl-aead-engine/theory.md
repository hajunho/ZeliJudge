# 리눅스 커널 Crypto API (crypto/): 내부 서브시스템 및 고성능 비동기 아키텍처

## 1. 리눅스 커널 Crypto API의 발전과 설계 철학

초기 유닉스 및 리눅스 커널에서는 암호화 알고리즘이 필요할 때마다 각 서브시스템(예: PPP 압축, 루프백 파일시스템) 내부에서 독자적인 C 코드로 구현되어 있었습니다. 이는 중복 구현, 보안 패치 관리의 난맥상, 그리고 새로운 하드웨어 가속기를 유연하게 채택할 수 없는 심각한 한계를 유발했습니다.

이를 해결하기 위해 리눅스 커널 2.6에 제임스 모리스(James Morris) 등에 의해 **통합 Crypto API(`crypto/`)**가 설계되었습니다. Crypto API는 객체 지향적 변환 인스턴스(`crypto_tfm`) 모델을 도입하여:
1. **알고리즘 추상화**: 호출자(IPsec, dm-crypt 등)는 구체적인 하드웨어나 구현체를 몰라도 알고리즘 이름(예: `"aes"`, `"gcm(aes)"`)만으로 변환기를 할당받습니다.
2. **복합 템플릿(Templates)**: 블록 암호(Cipher)와 동작 모드(Mode of Operation)를 독립적으로 합성(Compose)할 수 있습니다 (예: `cbc(aes)`, `gcm(aes)`, `authenc(hmac(sha256),cbc(aes))`).
3. **이 기종 가속기 투명 오프로드**: CPU의 SIMD 인스트럭션 세트부터 PCIe 부착형 FPGA/ASIC(Intel QAT)까지 단일 인터페이스로 수용합니다.

---

## 2. 핵심 데이터 구조 및 서브시스템

### (1) `struct crypto_alg` 와 `cra_priority`
모든 암호화 드라이버는 모듈 로딩 시 `crypto_register_alg()`를 통해 커널에 등록됩니다:
```c
struct crypto_alg {
    char cra_name[CRYPTO_MAX_ALG_NAME];
    char cra_driver_name[CRYPTO_MAX_ALG_NAME];
    u32 cra_priority;
    u32 cra_flags;
    u32 cra_blocksize;
    u32 cra_ctxsize;
    ...
};
```
- `cra_priority`: 드라이버의 성능 및 선호도 수치입니다. 커널은 알고리즘 이름으로 검색할 때 등록된 드라이버 중 **가장 높은 `cra_priority`를 가진 드라이버**를 바인딩합니다.
- 일반적으로:
  - C Generic: 100
  - ASM/SIMD: 300 ~ 400
  - Dedicated Crypto Engine: 1000 이상

---

### (2) Scatterlist (SGL) 기반 제로 카피 I/O
커널 공간에서 대용량 데이터는 단일 가상 연속 주소에 존재하지 않습니다. 특히 고성능 네트워크 패킷의 경우 소켓 버퍼 헤더(`sk_buff->data`)와 페이지 단편(`skb_shinfo(skb)->frags`)에 물리적으로 분산되어 있습니다.

```c
struct scatterlist {
    unsigned long page_link;
    unsigned int  offset;
    unsigned int  length;
    dma_addr_t    dma_address;
};
```
- Crypto API는 요청 시 소스 SGL(`src`)과 목적지 SGL(`dst`) 포인터를 수신합니다.
- 드라이버는 scatterwalk 라이브러리를 통해 비연속적인 청크들을 순회하며 DMA 전송 또는 SIMD 레지스터 로드를 수행하여 커널 공간에서의 불필요한 `kmalloc` 및 메모리 복제(`memcpy`) 오버헤드를 완전 제거합니다.

---

### (3) AEAD 요청과 결합 데이터(AAD)
**AEAD(Authenticated Encryption with Associated Data)**는 기밀성(Confidentiality)과 무결성(Integrity)을 하나의 프리미티브로 통합한 표준입니다:
```c
struct aead_request {
    struct scatterlist *src;
    struct scatterlist *dst;
    unsigned int cryptlen;
    unsigned int assoclen;
    u8 *iv;
    crypto_completion_t complete;
    void *data;
};
```
- **AAD(Assoc Data)**: IPsec의 SPI(Security Parameter Index)나 시퀀스 번호, TLS 레코드 헤더처럼 평문으로 전송되어야 라우터가 패킷을 라우팅할 수 있으나, 위조되어서는 안 되는 메타데이터입니다.
- AEAD 엔진은 AAD 구간을 암호화하지 않고 보존하면서도, 무결성 검증 태그(ICV/Tag) 계산에는 암호문과 함께 투입합니다.
- 복호화 시 인증 태그가 1비트라도 틀리면 전체 복호화 데이터 폐기와 함께 `-EBADMSG`를 즉시 반환합니다.

---

### (4) 비동기 링 버퍼 및 백로그 큐 관리
하드웨어 가속기는 I/O 제출과 완료가 비동기적으로 일어납니다:
```c
int crypto_aead_encrypt(struct aead_request *req)
```
- **`-EINPROGRESS`**: 요청이 가속기의 하드웨어 링 버퍼(DMA Descriptor Ring)에 성공적으로 큐잉되었으며, 완료 시 비동기 콜백(`req->complete()`)이 호출될 것임을 호출자에게 통지합니다.
- **`-EBUSY`**: 하드웨어 링이 가득 찼으나 `CRYPTO_TFM_REQ_MAY_BACKLOG` 플래그가 설정되어 소프트웨어 백로그 큐에 안전하게 대기되었음을 알립니다.
- **`-ENOSPC`**: 백로그 큐마저 가득 차 요청이 거부(Drop)되었음을 의미합니다.

하드웨어 인터럽트 핸들러나 NAPI 폴링 루틴에서 작업이 완료되면, 백로그에 대기하던 요청이 하드웨어 링으로 승격되며 파이프라인의 처리량이 극대화됩니다.
