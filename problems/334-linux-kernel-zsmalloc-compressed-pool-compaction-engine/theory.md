# Linux Kernel zsmalloc Compressed Memory Pool Allocator & Compaction 심층 이론

## 1. 개요: 압축 메모리(ZRAM / ZSWAP)의 메모리 할당 도전 과제

현대 모바일 디바이스와 클라우드 호스트는 물리 메모리 부족 시 디스크 스왑(Disk Swap)으로 인한 I/O 병목을 피하기 위해 **ZRAM**과 **ZSWAP** 같은 압축 스왑 서브시스템을 광범위하게 활용합니다:
- 원본 4KB 페이지가 압축될 때, 출력 데이터의 크기는 정규분포를 따르지 않으며 데이터의 반복성에 따라 수십 바이트에서 3.9KB까지 연속적으로 분포합니다.
- **표준 커널 할당자들의 부적합성**:
  1. **Buddy Allocator**: 최소 할당 단위가 1개 페이지(4KB)이므로 1KB 크기의 압축 데이터에 3KB의 내부 단편화가 발생하여 압축 효과가 상쇄됩니다.
  2. **SLUB/SLAB**: 단일 객체가 물리 페이지 경계를 넘을 수 없으므로, 예를 들어 3000바이트 객체는 4KB 페이지에 단 1개만 들어가고 1096바이트가 버려집니다.

이를 극복하기 위해 세르게이 센케비치(Sergey Senkevich)와 민찬 김(Minchan Kim) 등이 리눅스 커널에 구현한 할당자가 바로 **zsmalloc (`mm/zsmalloc.c`)**입니다.

---

## 2. 핵심 아키텍처: `zspage`와 멀티페이지 체이닝

zsmalloc의 가장 독창적인 설계는 물리 페이지를 논리적으로 묶어 하나의 가상 슬랩을 형성하는 **`zspage`**입니다:

```c
struct size_class {
    spinlock_t lock;
    int size;
    int pages_per_zspage;
    int objs_per_zspage;
    struct list_head fullness_list[NR_ZS_FULLNESS];
};
```

### 12.5% 단편화 억제 법칙
- zsmalloc은 각 크기 클래스마다 1~4개의 물리 페이지(`ZS_MAX_PAGES_PER_ZSPAGE = 4`)를 조합하여, 버려지는 자투리 공간이 전체 `zspage` 크기의 12.5%(1/8) 이하가 되도록 사전 계산합니다.
- 예: 크기 3000바이트 객체
  - 1개 페이지(4096B) 사용 시: 1개 객체 수납, 1096B 낭비 (26.7% 낭비 -> 불합격)
  - 3개 페이지(12288B) 체이닝 시: 4개 객체 수납(12000B), 288B 낭비 (2.3% 낭비 -> 합격!)

---

## 3. 풀니스 그룹 (Fullness Groups) 및 할당 정책

zsmalloc은 사용률에 따라 `zspage`를 4개의 풀니스 리스트로 분류하여 관리합니다:

1. `ZS_EMPTY` (0%): 즉시 물리 페이지를 해제할 수 있는 상태.
2. `ZS_ALMOST_EMPTY` (1% ~ 49%): 컴팩션 시 소스(Source)가 될 우선 대상.
3. `ZS_ALMOST_FULL` (50% ~ 99%): 신규 할당 시 최우선 선택 대상.
4. `ZS_FULL` (100%): 여유 슬롯이 없어 탐색 대상에서 제외.

### 최적 슬롯 재사용 전략
- 새 객체 할당 시 `ZS_ALMOST_FULL`의 zspage를 먼저 소비함으로써, 높은 사용률을 가진 zspage를 최대한 `ZS_FULL`로 밀어 올립니다.
- 이를 통해 낮은 사용률의 zspage가 무분별하게 양산되는 것을 방지합니다.

---

## 4. 메모리 컴팩션 (zs_compact)과 간접 핸들 매핑

압축 스왑 데이터가 빈번히 해제되면 수많은 zspage에 빈 슬롯이 드문드문 남아 물리 페이지가 낭비되는 **외부 단편화(External Fragmentation)**가 발생합니다:

1. **간접 핸들 (Indirect Handle)**:
   - 객체가 메모리 내에서 자유롭게 이주(Relocate)될 수 있도록, 커널은 객체의 물리 주소 대신 포인터의 포인터 역할을 하는 64비트 간접 핸들을 반환합니다.
2. **투-포인터 컴팩션 알고리즘**:
   - `ZS_ALMOST_EMPTY` 리스트(소스)와 `ZS_ALMOST_FULL` 리스트(타깃)를 양방향 스캔합니다.
   - 소스의 객체를 타깃의 빈 슬롯으로 복사하고, 간접 핸들이 가리키는 내부 위치를 원자적으로 갱신합니다.
   - 객체가 모두 비워진 소스 `zspage`의 물리 페이지들을 OS 버디 할당자로 일괄 반환합니다.

---

## 5. 커널 소스 코드 매핑

- `mm/zsmalloc.c`:
  - `zs_malloc()`: 크기 클래스 선택 및 zspage 슬롯 할당.
  - `zs_free()`: 슬롯 반환 및 풀니스 전이, zspage 회수.
  - `zs_compact()`: 단편화된 zspage 간 객체 이주 및 페이지 언핀.
  - `get_pages_per_zspage()`: 12.5% 이하 최적 페이지 체이닝 산출.
- `include/linux/zsmalloc.h`:
  - `enum zs_mapmode`, `struct zs_pool` 정의.
