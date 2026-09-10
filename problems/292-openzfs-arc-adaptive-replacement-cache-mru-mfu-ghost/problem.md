# Problem 292: 10GB 백업 한 번 돌렸더니 왜 DB 캐시 히트율이 99%에서 5%로 곤두박질쳐요?!: 고성능 스토리지 OpenZFS ARC(Adaptive Replacement Cache): MRU($T_1$) vs MFU($T_2$), 고스트 캐시($B_1, B_2$)와 동적 적응 파라미터 $p$를 이용한 순차 스캔 오염(Scan Pollution) 방어 시뮬레이터 (OpenZFS Adaptive Replacement Cache: MRU/MFU Dual-Lists, Ghost Caches & Scan Pollution Defense)

## 문제 설명

대규모 금융 트랜잭션 데이터베이스(PostgreSQL, MySQL)와 분산 스토리지 클러스터(OpenZFS, Ceph)를 운영하는 스토리지 인프라 SRE 팀은 매일 자정마다 반복되는 미스터리한 성능 붕괴 현상으로 인해 비상이 걸렸습니다.

평소 초당 수만 건의 쿼리를 처리하며 **캐시 히트율 98~99%**를 유지하던 핵심 데이터베이스가, 자정 정기 백업 스크립트(`pg_dump` 또는 테이블 전체 순차 스캔 쿼리)가 1회 실행되는 순간 **캐시 히트율이 5% 미만으로 폭락하고 NVMe 디스크 I/O 지연 시간이 50배 이상 폭증**하여 서비스 장애가 발생하는 것이었습니다.

원인은 전통적인 **LRU (Least Recently Used) 캐시 교체 알고리즘의 치명적 결함인 순차 스캔 오염(Scan Pollution / Cache Flushing)** 때문이었습니다:
* LRU는 가장 최근에 참조된 페이지를 무조건 캐시 최상단(MRU)에 적재합니다.
* 수 기가바이트의 콜드(Cold) 데이터나 1회성 백업 테이블을 순차 스캔(`Sequential Scan`)하면, 단 한 번 읽히고 영원히 다시 쓰이지 않을 쓰레기 페이지들이 캐시 전체를 가득 채웁니다.
* 그 결과, 수천 명의 사용자가 빈번하게 조회하던 핫(Hot) 워킹셋(인덱스, 사용자 세션, 계좌 잔액 등)이 물리 메모리에서 전부 축출(Evict)되어 버리는 대참사가 일어납니다.

반면, 참조 횟수만을 따지는 LFU(Least Frequently Used) 알고리즘은 과거에 수천 번 조회되었으나 지금은 유휴 상태인 오래된 페이지가 캐시에 영구 잔류하는 **빈도 정체(Frequency Starvation)** 문제를 유발합니다.

2003년 IBM 알마덴 연구소의 님로드 메기도(Nimrod Megiddo)와 다르멘드라 모다(Dharmendra S. Modha)는 USENIX FAST 학회에서 LRU와 LFU의 장점만을 취하고 스캔 오염을 원천 차단하는 혁명적인 알고리즘인 **ARC(Adaptive Replacement Cache)**를 발표했습니다. ARC는 오늘날 엔터프라이즈 스토리지 파일시스템의 제왕인 **OpenZFS**의 핵심 캐시 엔진으로 채택되어 사용되고 있습니다.

스토리지 코어 시스템 엔지니어로서, 4개의 이중 연결 리스트($T_1, T_2, B_1, B_2$)와 자가 조절 파라미터 $p$를 기반으로 스캔 오염을 완벽히 방어하는 OpenZFS ARC 엔진을 구현하십시오.

---

## 핵심 시스템 파라미터 및 원리

### 1. ARC 4대 리스트 아키텍처
캐시 전체 용량이 $c$일 때, ARC는 최대 $2c$개의 페이지 메타데이터를 관리합니다:
1. **$T_1$ (Top 1 - Recent Data Cache)**:
   - 최근에 '단 1회' 참조된 페이지의 실제 데이터를 보관하는 캐시 리스트 (용량 상한: $p$).
2. **$T_2$ (Top 2 - Frequent Data Cache)**:
   - 최소 '2회 이상' 참조된 빈번한 핫 페이지의 실제 데이터를 보관하는 캐시 리스트 (용량 상한: $c - p$).
   - 실제 캐시에 상주하는 데이터 페이지 수: $|T_1| + |T_2| \le c$.
3. **$B_1$ (Bottom 1 - Recent Ghost Cache)**:
   - $T_1$에서 메모리 부족으로 축출된 페이지의 **메타데이터(키)만을 보관**하는 고스트 리스트 (데이터 없음).
4. **$B_2$ (Bottom 2 - Frequent Ghost Cache)**:
   - $T_2$에서 메모리 부족으로 축출된 페이지의 **메타데이터(키)만을 보관**하는 고스트 리스트 (데이터 없음).
   - 히스토리 메타데이터 총합 불변식: $|T_1| + |B_1| \le c$, $|T_1| + |T_2| + |B_1| + |B_2| \le 2c$.

---

### 2. 자가 적응 파라미터 $p$의 동적 조율 메커니즘
$p \in [0, c]$는 최근성 캐시 $T_1$의 목표 용량을 결정합니다:
1. **$B_1$ 고스트 히트 (최근성 부족 피드백)**:
   - 축출되었던 $T_1$ 페이지가 다시 요청되면, $T_1$의 용량이 너무 작았다는 의미입니다. $p$를 증가시킵니다:
     $$\Delta_1 = \max\left(1, \left\lfloor \frac{|B_2|}{|B_1|} \right\rfloor\right), \quad p = \min(c, p + \Delta_1)$$
2. **$B_2$ 고스트 히트 (빈도성 부족 피드백)**:
   - 축출되었던 $T_2$ 페이지가 다시 요청되면, $T_2$의 용량이 너무 작았다는 의미입니다. $p$를 감소시킵니다:
     $$\Delta_2 = \max\left(1, \left\lfloor \frac{|B_1|}{|B_2|} \right\rfloor\right), \quad p = \max(0, p - \Delta_2)$$

---

### 3. 교체 정책 (`REPLACE(in_b2)`)
신규 페이지 적재 시 메모리가 부족하면 어느 리스트에서 축출할지 결정합니다:
- 만약 $|T_1| > 0$ 이고 $(|T_1| > p \text{ 또는 } (in\_b2 \text{ 이고 } |T_1| == \lfloor p \rfloor))$:
  - $T_1$의 가장 오래된(LRU) 페이지를 축출하여 $B_1$으로 이동.
- 그렇지 않은 경우:
  - $T_2$의 가장 오래된(LRU) 페이지를 축출하여 $B_2$로 이동.

---

### 4. 스캔 오염 방어 원리 (Scan Resistance)
- 1회성 순차 스캔 데이터(백업 등)는 처음 접근 시 $T_1$에만 들어오며, 다시 참조되지 않으므로 $T_2$로 절대 승격되지 않습니다.
- $T_1$의 크기가 $p$를 넘어서는 순간 $T_1$ 내부에서만 $B_1$으로 밀려나 축출되므로, **$T_2$에 상주하는 핵심 워킹셋 데이터는 1바이트도 손상되지 않고 100% 보존**됩니다!

---

## 입력 형식 (`sys.stdin`)

JSON 객체로 주어지며 `mode`에 따라 동작합니다:

### 모드 1: `SIMULATE_CACHE_TRACE`
```json
{
  "mode": "SIMULATE_CACHE_TRACE",
  "cache_capacity": 50,
  "initial_p": 0.0,
  "compare_with_lru": true,
  "trace": [
    {"key": "PAGE_001"},
    {"key": "PAGE_002"}
  ]
}
```

### 모드 2: `SCAN_RESISTANCE_BENCHMARK`
```json
{
  "mode": "SCAN_RESISTANCE_BENCHMARK",
  "cache_capacity": 50,
  "working_set_size": 30,
  "scan_size": 200,
  "loops_before": 5
}
```

---

## 출력 형식 (`sys.stdout`)
단일 행의 압축된 JSON 문자열을 출력합니다.
