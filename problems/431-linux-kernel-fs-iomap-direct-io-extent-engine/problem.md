# Problem #431: 리눅스 커널 파일 시스템 & 스토리지: fs/iomap 모던 다이렉트 I/O(O_DIRECT) 및 익스텐트(Extent) 상태 머신과 바이오(bio) 경계 분할 엔진

## 🌟 개요 (Executive Summary)
리눅스 커널 4.8 이전의 전통적인 파일 I/O 서브시스템은 30년 역사의 `buffer_head`(`struct buffer_head`) 아키텍처에 의존했습니다. 이는 4KB 페이지마다 104바이트의 구조체를 할당하고 잠금을 수행하는 방식으로, 페타바이트급 파일 시스템이나 수백만 IOPS를 처리하는 초고속 NVMe SSD 환경에서 막대한 슬랩 메모리 오버헤드와 캐시라인 바운싱을 유발했습니다.

이를 근본적으로 대체하기 위해 크리스토프 헬비히(Christoph Hellwig)와 데이브 치너(Dave Chinner) 등 XFS 및 커널 스토리지 핵심 메인테이너들은 **모던 익스텐트 매핑 서브시스템인 `fs/iomap` (`fs/iomap/direct-io.c`, `fs/iomap/iter.c`)**을 도입했습니다. `iomap`은 XFS, ext4, Btrfs, ZoneFS, DAX 등 최신 파일 시스템의 공통 I/O 기반 계층으로 자리 잡았습니다.

`iomap` 다이렉트 I/O(`O_DIRECT`)의 핵심 설계 원리는 다음과 같습니다:
1. **반복자 기반 익스텐트 해석(`iomap_iter`)**: 단일 시스템 콜(예: 1MB 읽기/쓰기)이 여러 개의 서로 다른 익스텐트(Extent) 경계를 가로지를 때, 루프를 돌며 각 영역을 슬라이스 단위로 처리합니다.
2. **5대 익스텐트 상태 머신**:
   - `IOMAP_HOLE`: 파일 내 미할당 희소 구멍(Sparse Hole). 읽기 시 디스크 I/O를 전혀 발생시키지 않고 유저 버퍼를 즉각 0으로 제로-채움(`ZERO_FILL`) 처리합니다.
   - `IOMAP_UNWRITTEN`: `fallocate` 등으로 사전 할당되었으나 유효 데이터가 쓰이지 않은 블록. 읽기 시 0을 반환하며, 쓰기 발생 시 해당 구간만 `IOMAP_MAPPED`로 동적 분할 변환(`unwritten conversion`)합니다.
   - `IOMAP_MAPPED`: 실제 디스크 물리 섹터에 할당되고 초기화된 유효 블록. 다이렉트 DMA I/O를 수행합니다.
   - `IOMAP_INLINE`: 아이노드 본체에 직접 저장된 소형 데이터.
   - `IOMAP_DELALLOC`: 지연 할당된 페이지 캐시 데이터.
3. **하드웨어 제약 기반 바이오 분할(Bio Splitting)**: 단일 익스텐트가 하드웨어 최대 전송 크기(`max_bio_size`)를 초과할 경우, 여러 개의 하위 `bio`로 자동 분할되어 디바이스 드라이버에 전달됩니다.
4. **섹터 정렬 강제 검증**: 다이렉트 I/O는 하드웨어 DMA 요구사항에 따라 논리 오프셋 및 I/O 길이가 디바이스의 물리/논리 섹터 크기(512B 또는 4096B)의 배수여야 하며, 비정렬 요청은 `-EINVAL`(`EINVAL_UNALIGNED_DIRECT_IO`)로 거절합니다.

본 문제에서는 리눅스 커널 `fs/iomap`의 다이렉트 I/O 파이프라인, 익스텐트 상태 머신 전이, bio 분할 및 무복사 제로-필 동작을 완벽히 시뮬레이션하는 엔진을 구현합니다.

---

## 🏗️ 아키텍처 및 시스템 흐름도 (System Architecture)

```
              [ User Direct I/O Request: read(fd, buf, len) / O_DIRECT ]
                                       │
                                       ▼
                     [ Sector Alignment Verification ]
                         offset % sector_size == 0 &&
                         length % sector_size == 0
                                ┌──────┴──────┐
                              Valid         Invalid
                                │             │
                                │             ▼
                                │    [ EINVAL_UNALIGNED_DIRECT_IO ]
                                ▼
                       [ iomap_iter Loop ]
                  (pos = offset, remaining = length)
                                │
                 ┌──────────────┴──────────────┐
                 ▼                             ▼
       Find Extent at pos              No Extent (Hole)
                 │                             │
       ┌─────────┴─────────┐                   ▼
       ▼                   ▼            [ ZERO_FILL ]
   Type == MAPPED    Type in (HOLE,UNWRITTEN)  paddr = -1
       │                   │                   Advance pos
       │                   ▼
       │            [ ZERO_FILL ]
       │            (Zero memory directly)
       │            Advance pos
       ▼
   Check max_bio_size
       │
   Split into bios <= max_bio_size
   Issue BIO_READ / BIO_WRITE to paddr
   Advance pos
       │
       ▼
   If WRITE to UNWRITTEN:
   Split extent: [UNWRITTEN] -> [UNWRITTEN] + [MAPPED] + [UNWRITTEN]
   Increment unwritten_conversions
```

---

## 🔢 수학적 공식 및 판정 기준 (Mathematical Formulations)

### 1. 섹터 정렬 검증 (Sector Alignment Invariant)
스토리지 하드웨어의 섹터 크기를 $S_{\text{sector}}$라 할 때, 다이렉트 I/O 요청의 오프셋 $O$와 길이 $L$은 다음을 반드시 만족해야 합니다:
$$O \pmod{S_{\text{sector}}} = 0 \quad \land \quad L \pmod{S_{\text{sector}}} = 0$$
조건 불만족 시 `EINVAL_UNALIGNED_DIRECT_IO` 상태를 반환하고 모든 하위 I/O를 즉각 중단합니다.

### 2. 단일 반복 슬라이스 길이 결정 (Slice Length in iomap_iter)
익스텐트 $E$의 종료 오프셋을 $E_{\text{end}} = E_{\text{offset}} + E_{\text{length}}$라 할 때, 현재 커서 $P$에서의 처리 청크 크기 $C$는:
$$C = \min(\text{remaining}, E_{\text{end}} - P)$$

### 3. Bio 분할 개수 산출 (Bio Splitting Formulation)
단일 물리 MAPPED 익스텐트에서 처리할 바이트 수 $C$와 블록 레이어의 최대 bio 크기 $B_{\text{max}}$에 대해 생성되는 bio의 개수는:
$$N_{\text{bio}} = \lceil \frac{C}{B_{\text{max}}} \rceil$$
각 bio의 크기 $S_i$는:
$$S_i = \begin{cases} B_{\text{max}} & \text{if } i < N_{\text{bio}} - 1 \text{ or } C \pmod{B_{\text{max}}} = 0 \\ C \pmod{B_{\text{max}}} & \text{otherwise} \end{cases}$$

### 4. 미기록 익스텐트(UNWRITTEN) 분할 전이 (Extent Trisection)
범위 $[E_{\text{start}}, E_{\text{start}} + E_{\text{len}})$의 UNWRITTEN 익스텐트에 대해 부분 쓰기 $[P, P + C)$가 발생할 경우, 익스텐트 테이블은 최대 3개로 삼분할(Trisection)됩니다:
1. 선행 미기록 구간: $[E_{\text{start}}, P)$ (길이 $> 0$일 때, UNWRITTEN 유지)
2. 쓰기 완료 구간: $[P, P + C)$ (MAPPED로 상태 승격)
3. 후행 미기록 구간: $[P + C, E_{\text{start}} + E_{\text{len}})$ (길이 $> 0$일 때, UNWRITTEN 유지)

---

## 📥 입력 형식 (Input Specification)

표준 입력(stdin)으로 단일 JSON 객체가 전달됩니다:
```json
{
  "config": {
    "sector_size": 4096,
    "max_bio_size": 32768,
    "allow_unaligned": false,
    "initial_extents": [
      {"offset": 0, "length": 65536, "paddr": 1048576, "type": "MAPPED"},
      {"offset": 65536, "length": 65536, "paddr": 2097152, "type": "UNWRITTEN"}
    ]
  },
  "trace": [
    {"op": "IOMAP_READ", "offset": 32768, "length": 65536},
    {"op": "IOMAP_WRITE", "offset": 65536, "length": 32768},
    {"op": "DUMP_EXTENTS"}
  ]
}
```

### 지원 명령어 (Supported Operations):
1. `IOMAP_READ`:
   - 파라미터: `offset` (int), `length` (int)
   - 익스텐트를 순회하며 `ZERO_FILL` 또는 `BIO_READ`를 발행합니다.
2. `IOMAP_WRITE`:
   - 파라미터: `offset` (int), `length` (int), `alloc_paddr` (int, optional)
   - 익스텐트 순회 쓰기 및 UNWRITTEN -> MAPPED 동적 변환 수행.
3. `ALLOC_EXTENT`:
   - 파라미터: `offset` (int), `length` (int), `paddr` (int), `type` (str)
   - 신규 익스텐트를 테이블에 삽입 및 재정렬.
4. `DUMP_EXTENTS`:
   - 현재 파일의 모든 익스텐트 목록을 정렬된 순서로 덤프.

---

## 📤 출력 형식 (Output Specification)

표준 출력(stdout)으로 공백이 없는 콤팩트 JSON 문자열을 단일 행으로 출력합니다:
```json
{"events":[{"op":"IOMAP_READ","offset":32768,"length":65536,"status":"SUCCESS","bytes_read":65536,"zero_filled_bytes":32768,"disk_bytes_read":32768,"bios":[{"type":"BIO_READ","offset":32768,"length":32768,"paddr":1081344},{"type":"ZERO_FILL","offset":65536,"length":32768,"paddr":-1,"origin_type":"UNWRITTEN"}]}],"summary":{"total_bytes_read":65536,"total_bytes_written":0,"zero_filled_bytes":32768,"bio_count":1,"unwritten_conversions":0,"aligned_io_count":1,"unaligned_rejects":0,"final_extent_count":2}}
```

---

## 💡 제약 조건 (Constraints)
- 모든 시뮬레이션 상태는 단일 스레드 결정론적(Deterministic)으로 동작해야 합니다.
- `allow_unaligned`가 `false`일 때, 오프셋과 길이가 `sector_size`의 배수가 아니면 즉시 `EINVAL_UNALIGNED_DIRECT_IO`로 거절됩니다.
- 익스텐트 목록은 항상 `offset` 오름차순으로 정렬 상태를 유지해야 합니다.
- `max_bio_size`를 초과하는 I/O는 정확히 상한 단위로 분할되어 `bios` 목록에 순서대로 추가되어야 합니다.
