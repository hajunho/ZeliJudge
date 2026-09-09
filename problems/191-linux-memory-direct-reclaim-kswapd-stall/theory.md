# 깊이 있는 컴퓨터 과학: 리눅스 커널 Zone Watermarks와 메모리 회수(Page Reclaim) 서브시스템

## 1. 리눅스 물리 메모리 존(Zone)과 페이지 할당 경로

리눅스 커널의 물리 메모리는 하드웨어 특성과 주소 지정 범위에 따라 존(Zone)으로 나뉩니다:
- **`ZONE_DMA`**: x86 기준 하위 16MB (레거시 ISA 디바이스용).
- **`ZONE_DMA32`**: 32비트 주소 공간(하위 4GB).
- **`ZONE_NORMAL`**: 64비트 시스템에서 주소 제한 없이 커널과 유저 공간이 직접 매핑하여 사용하는 일반 물리 메모리.

### 1.1 Fast Path vs Slow Path 할당 메커니즘
애플리케이션이 `malloc()`이나 메모리 매핑을 통해 페이지를 요청(`alloc_pages()`)할 때:
1. **패스트 패스 (Fast Path, `get_page_from_freelist()`)**:
   - 현재 존의 `free_pages - alloc_pages > WMARK_LOW`인지 검사합니다.
   - 여유 공간이 충분하면 락 경합 없이 버디 시스템의 per-CPU 페이지 세트(PCP, Per-CPU Page Sets)에서 $1\,\mu\text{s}$ 미만의 극저지연으로 페이지를 즉시 반환합니다.
2. **슬로우 패스 (Slow Path, `__alloc_pages_slowpath()`)**:
   - `WMARK_LOW` 이하로 떨어지면 슬로우 패스로 진입합니다.
   - 비동기 백그라운드 스레드인 `kswapd`를 깨우고(`wake_all_kswapds()`), 재차 할당을 시도합니다.
   - 만약 여유 메모리가 `WMARK_MIN`마저 붕괴되면, 커널은 유저 스레드를 슬립시키고 **다이렉트 리클레임(`__perform_reclaim()`)**을 강제 수행합니다.

---

## 2. 수위선(Zone Watermarks) 계산 공식

커널 내부 소스코드(`mm/page_alloc.c`의 `__setup_per_zone_wmarks()`)에서 각 존의 워터마크는 다음과 같이 계산됩니다:

$$\text{wmark\_min} = \frac{\text{vm.min\_free\_kbytes}}{\text{PAGE\_SIZE}}$$

$$\text{scale\_buffer} = \text{managed\_pages} \times \frac{\text{vm.watermark\_scale\_factor}}{10000}$$

$$\Delta_{\text{wmark}} = \max\left(\left\lfloor \frac{\text{wmark\_min}}{4} \right\rfloor, \text{scale\_buffer}\right)$$

$$\text{wmark\_low} = \text{wmark\_min} + \Delta_{\text{wmark}}$$

$$\text{wmark\_high} = \text{wmark\_min} + 2 \times \Delta_{\text{wmark}}$$

- `vm.min_free_kbytes`는 `WMARK_MIN`의 절대 크기를 결정합니다.
- `vm.watermark_scale_factor`는 `WMARK_LOW`와 `WMARK_MIN` 사이의 **완충 지대(Buffer Gap)** 폭을 결정합니다.

---

## 3. kswapd 비동기 회수 vs 유저 다이렉트 리클레임

| 비교 항목 | `kswapd` (비동기 회수) | `Direct Reclaim` (동기 회수) |
|---|---|---|
| **실행 주체** | 독립된 커널 백그라운드 스레드 | 메모리를 요청한 **유저 애플리케이션 스레드** |
| **기상 트리거** | 여유 메모리가 `WMARK_LOW` 아래로 떨어질 때 | 여유 메모리가 `WMARK_MIN` 아래로 떨어질 때 |
| **애플리케이션 영향** | **지연 시간 스톨 0ms** (무중단) | **수십~수백 ms 블로킹** (D-State 정지) |
| **종료 조건** | 여유 메모리가 `WMARK_HIGH`에 도달할 때 | 현재 할당 요구량이 충족될 때까지 |
| **CPU 비용** | 독립 코어에서 비동기 처리 | 요청 스레드의 응답 시간(p99)에 직접 타격 |

---

## 4. 실무 장애 사례와 튜닝 가이드

### 4.1 Apache Kafka / Elasticsearch 대규모 인제스천 참사
- **현상**: 초당 수만 건의 메시지가 유입되는 카프카 브로커에서 프로듀서 ACK 응답 지연이 갑자기 500ms 이상 치솟으며 타임아웃 발생.
- **원인 분석**: 브로커 OS의 기본 `min_free_kbytes`가 64MB로 너무 낮아, 100MB 단위의 OS 페이지 캐시 더티 쓰기 버스트 발생 시 수위선이 즉시 `WMARK_MIN`을 하회하여 카프카 I/O 스레드가 커널 `try_to_free_pages()`에 갇힘.
- **해결책**:
  ```bash
  # 1. min_free_kbytes를 시스템 RAM의 약 3~5%로 상향 (예: 1GB)
  sysctl -w vm.min_free_kbytes=1048576

  # 2. watermark_scale_factor를 기본값 10(0.1%)에서 200(2%)으로 확대
  sysctl -w vm.watermark_scale_factor=200
  ```

이 설정을 적용하면, 여유 메모리가 위험 수위선에 도달하기 훨씬 전에 `kswapd`가 조기에 깨어나 거대한 완충 버퍼를 유지하므로, 유저 스레드의 다이렉트 리클레임 스톨을 완벽하게 예방할 수 있습니다.
