# 리눅스 커널 KASAN 섀도 메모리(Shadow Memory) 및 레드존 포이즈닝 엔진

## 1. 개요 및 배경

리눅스 커널에서 발생하는 치명적인 보안 취약점(Local Privilege Escalation, LPE 및 Remote Code Execution, RCE)의 60% 이상은 C 언어 메모리 관리 오류인 **버퍼 오버플로우(Out-of-Bounds, OOB)**, **해제 후 재사용(Use-After-Free, UAF)**, **이중 해제(Double Free)**에서 기인합니다.
전통적인 디버깅 기법은 페이지 경계(Page Boundary)에서만 폴트를 감지할 수 있어, SLUB 캐시 슬랩 객체 내부의 단 몇 바이트 오프바이원(Off-by-One) 침범을 감지하지 못합니다.

리눅스 커널 4.0부터 도입된 **KASAN(Kernel Address Sanitizer, `mm/kasan/generic.c`)**은 컴파일러 인스트루멘테이션과 **1:8 직접 매핑 섀도 메모리(Shadow Memory)** 아키텍처를 결합하여 바이트 단위의 정밀한 메모리 오염 탐지를 수행합니다:
1. **1:8 섀도 메모리 스케일링**:
   - 커널 가상 주소 공간의 **8바이트마다 1바이트의 섀도 메모리**가 대응됩니다.
   - 섀도 주소 변환 공식:
     $$\text{shadow\_addr} = (\text{kernel\_addr} \gg 3) + \text{KASAN\_SHADOW\_OFFSET}$$
2. **섀도 바이트 값의 시맨틱**:
   - `0x00`: 8바이트 전체가 유효(Accessible)함.
   - `0x01` ~ `0x07` ($k$): 해당 8바이트 청크 중 앞부분 $k$ 바이트만 유효하고, 나머지 $8 - k$ 바이트는 레드존으로 포이즌됨.
   - `0xFB` (`KASAN_SLAB_REDZONE`): 슬랩 객체 경계 방어용 레드존 패딩.
   - `0xFC` (`KASAN_SLAB_FREE`): 이미 해제된 슬랩 객체(UAF 탐지용).
   - `0xFA` (`KASAN_PAGE_REDZONE`): 버디 페이지 할당 경계 레드존.
   - `0xFE` (`KASAN_SHADOW_GAP`): 접근 불가능한 섀도 갭 / 미할당 커널 공간.
3. **컴파일러 인터셉트 및 검증**:
   - 컴파일러는 메모리 역참조(`loadN`, `storeN`) 직전에 섀도 메모리를 검사하는 인라인 코드를 삽입합니다.
   - 만약 접근하려는 바이트가 유효 범위를 벗어나면 즉시 **KASAN 버그 리포트**를 생성하여 커널 패닉 또는 스택 트레이스를 출력합니다.

본 과제에서는 Generic KASAN의 1:8 섀도 메모리 변환, 슬랩 객체 할당 시의 페이로드 언포이즈닝 및 레드존 포이즈닝, 해제 시의 `KASAN_SLAB_FREE` 마킹, 그리고 메모리 접근 시의 부분 청크(Partial Granule) 및 레드존 침범 검출 엔진을 구현합니다.

---

## 2. 아키텍처 다이어그램

```
Kernel Address Space (8-Byte Granules)
  0xffff888001000000: [ B0 | B1 | B2 | B3 | B4 | B5 | B6 | B7 ]  --> Shadow: 0x00 (All 8 Valid)
  0xffff888001000008: [ B8 | B9 | B10| B11| B12| B13| B14| B15]  --> Shadow: 0x00 (All 8 Valid)
  0xffff888001000010: [ B16| B17| B18| Rz | Rz | Rz | Rz | Rz ]  --> Shadow: 0x03 (First 3 Valid, 5 Redzone!)
  0xffff888001000018: [ Rz | Rz | Rz | Rz | Rz | Rz | Rz | Rz ]  --> Shadow: 0xFB (KASAN_SLAB_REDZONE)
                                         |
                                         v (Right Shift by 3 + KASAN_SHADOW_OFFSET)
Shadow Memory Region (1 Byte per 8 Bytes)
  [ 0x00 ] [ 0x00 ] [ 0x03 ] [ 0xFB ] [ 0xFB ] ...
```

---

## 3. 핵심 규칙 및 상태 전이 모델

### 3.1 섀도 주소 매핑
커널 주소 $A$에 대응되는 섀도 메모리 인덱스 $G$ 및 섀도 주소:
$$G = A \gg 3$$
$$\text{shadow\_addr} = G + \text{KASAN\_SHADOW\_OFFSET}$$

### 3.2 슬랩 할당 (`KMALLOC`)
- 객체 페이로드 크기: `size`
- 완전한 8바이트 청크 수: $F = \lfloor \text{size} / 8 \rfloor$
- 나머지 바이트: $R = \text{size} \bmod 8$
- 앞선 $F$개의 섀도 바이트는 `0x00`으로 설정.
- $R > 0$인 경우, 다음 섀도 바이트는 $R$ (`0x01` ~ `0x07`)로 설정 (부분 청크 포이즈닝).
- 객체 바로 뒤에 위치하는 `redzone_size` 바이트 영역은 `0xFB` (`KASAN_SLAB_REDZONE`)로 포이즌.

### 3.3 슬랩 해제 (`KFREE`)
- 이미 해제된 객체(`freed == True`)에 다시 `KFREE`가 호출되면 `DOUBLE_FREE` 버그 리포트 생성.
- 정상 해제 시, 페이로드 및 레드존을 포함한 전체 슬랩 슬롯의 섀도 바이트를 `0xFC` (`KASAN_SLAB_FREE`)로 포이즌.

### 3.4 메모리 접근 검증 (`READ_ACCESS`, `WRITE_ACCESS`)
주소 $A$부터 크기 $S$바이트 범위 $[A, A + S - 1]$의 각 바이트 $p$에 대해:
- 섀도 인덱스: $g = p \gg 3$, 청크 내 오프셋: $o = p \& 7$
- 섀도 값: $V = \text{shadow}[g]$
- 유효성 판정:
  - $V = 0$: 유효
  - $1 \le V \le 7$: $o < V$이면 유효, $o \ge V$이면 **위반**!
  - $V$가 포이즌 코드($V \ge 0x80$): **위반**!
- 위반 발생 시 버그 분류:
  - $V = 0xFC$: `USE_AFTER_FREE`
  - $V = 0xFB$ 또는 $1 \le V \le 7$: `SLAB_OUT_OF_BOUNDS`
  - $V = 0xFA$: `PAGE_ALLOC_OUT_OF_BOUNDS`
  - 기타: `WILD_MEMORY_ACCESS`

---

## 4. 입출력 규격

### 입력 JSON 구조
```json
{
  "config": {
    "shadow_offset": "0xdffffc0000000000",
    "default_redzone_size": 16
  },
  "operations": [
    {"type": "KMALLOC", "obj_id": "buf1", "addr": 18446603337227632640, "size": 27, "redzone_size": 16},
    {"type": "READ_ACCESS", "addr": 18446603337227632640, "size": 27},
    {"type": "WRITE_ACCESS", "addr": 18446603337227632667, "size": 1},
    {"type": "KFREE", "obj_id": "buf1"}
  ]
}
```

### 출력 JSON 구조
```json
{
  "operation_results": [
    {
      "op_index": 0,
      "type": "KMALLOC",
      "status": "SUCCESS",
      "obj_id": "buf1",
      "addr": "0xffff888001000000",
      "size": 27,
      "redzone_size": 16
    },
    {
      "op_index": 1,
      "type": "READ_ACCESS",
      "status": "ACCESS_OK",
      "access_type": "READ",
      "addr": "0xffff888001000000",
      "size": 27
    },
    {
      "op_index": 2,
      "type": "WRITE_ACCESS",
      "status": "BUG_REPORT",
      "bug_type": "SLAB_OUT_OF_BOUNDS",
      "fault_addr": "0xffff88800100001b",
      "access_type": "WRITE",
      "access_size": 1,
      "shadow_val": "0x03",
      "obj_id": "buf1",
      "offset_from_obj": 27
    }
  ],
  "summary": {
    "total_operations": 4,
    "allocated_objects": 1,
    "freed_objects": 1,
    "clean_accesses": 1,
    "bug_reports_count": 1,
    "bug_types_summary": {
      "SLAB_OUT_OF_BOUNDS": 1
    }
  }
}
```
