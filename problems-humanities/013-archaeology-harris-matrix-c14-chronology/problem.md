# [고고학/유물연대측정] 해리스 매트릭스(Harris Matrix) 층서학적 위상 정렬과 방사성 탄소-14 옥스칼(OxCal) 보정 연대기 엔진

## 문제 설명

고고학 발굴 현장(경주 월성 왕궁터, 서울 풍납토성·몽촌토성, 공주 무령왕릉 등)에서 유적과 유물의 역사를 복원할 때 가장 핵심이 되는 학문적 원리는 **층서학(Stratigraphy)**과 **방사성 탄소 연대측정(Radiocarbon C-14 Dating)**입니다.

1973년 에드워드 해리스(Edward C. Harris) 박사가 창안한 **해리스 매트릭스(Harris Matrix)**는 복잡하게 얽힌 발굴 지층(Contexts, Strata, 구덩이 Cut, 퇴적 Fill, 성벽 기초 등) 간의 상대적 선후 관계를 **방향성 비순환 그래프(DAG, Directed Acyclic Graph)**로 추상화한 현대 과학 고고학의 국제 표준 도구입니다.
지층 누적의 법칙(Law of Superposition)에 따라 아래층은 위층보다 먼저 형성되었으며, 구덩이(Cut)는 자신이 파고든 기존 지층보다 나중에 파여진 것입니다.
그러나 발굴 현장에서는 수많은 물리적 접촉 관계 중 불필요한 중복 연결(Transitive Shortcuts)이 발생하여 계통도가 왜곡되기 쉬우며, 반대로 동물이 땅을 파헤치거나(Bioturbation) 도굴, 발굴 실수로 인해 위층이 아래층보다 오래되었다고 잘못 기록되는 **층서학적 순환 모순(Stratigraphic Cycle)**이 발생하기도 합니다.

또한 유기물(목탄, 곡물, 인골 등)에서 측정한 탄소-14 측정치(BP, Before Present: 1950년 기준 측정 연대)는 지구 대기의 탄소 농도 변동으로 인해 실제 달력 연대(Calibrated Calendar Years BC/AD)와 비선형적인 괴리를 보입니다. 이를 바로잡기 위해 나이테(Dendrochronology) 기반 보정 곡선(IntCal)을 거치고, 해리스 매트릭스의 지층 상하 위상 순서와 결합하여 **지층 역전(Stratigraphic Inversion)이나 잔존 유물(Residual) 및 후대 침입 유물(Intrusive Outlier)**을 탐지해야 합니다.

국립문화유산연구원 고고학 데이터 연구팀의 일원이 되어, 유적지의 지층 관계를 해석하여 순환 모순을 검출하고, **이행 축소(Transitive Reduction)**를 적용하여 군더더기 없는 **표준 해리스 매트릭스**를 구축하며, 방사성 탄소 연대 보정 곡선을 결합하여 지층 이상 여부를 판정하는 **고고학 연대기 추론 엔진**을 구현하십시오.

---

## 층서학 및 연대기 공리 규격

### 1. 지층 관계와 시간적 선후 인과율 (Temporal Precedence)
- 그래프의 방향 간선 $u \to v$는 **"지층 $u$가 지층 $v$보다 먼저 형성됨(u is OLDER than v)"**을 의미합니다:
  - `ABOVE`: 지층 $u$가 지층 $v$의 물리적 **위에 있음** $\implies$ $v$가 먼저 퇴적되었으므로 간선 **$v \to u$** 생성.
  - `BELOW`: 지층 $u$가 지층 $v$의 물리적 **아래에 있음** $\implies$ $u$가 먼저 퇴적되었으므로 간선 **$u \to v$** 생성.
  - `CUTS`: 지층 $u$가 지층 $v$를 **파고듦(Cut)** $\implies$ $v$가 이미 존재해야 팔 수 있으므로 간선 **$v \to u$** 생성.
  - `FILLED_BY`: 지층 $u$(구덩이 파인 흔적)가 지층 $v$(채움 흙)에 의해 **메워짐** $\implies$ 구덩이가 먼저 파여야 채워지므로 간선 **$u \to v$** 생성.

### 2. 순환 모순 검출 (Cycle Detection)
- 형성된 방향 그래프에 순환(Cycle)이 존재하면(예: $A \to B \to C \to A$), 물리적으로 불가능한 역층서학적 모순(Reverse Stratigraphy)이므로 즉시 `"STRATIGRAPHIC_CYCLE_DETECTED"` 에러를 반환합니다.
- 위상 정렬(Topological Sort) 시 진입 차수(In-degree)가 0인 노드가 여러 개일 경우, 사전순(Alphabetical order)으로 큐에서 꺼내어 결정론적 순서를 보장합니다.

### 3. 표준 해리스 매트릭스 이행 축소 (Transitive Reduction)
- $u \to v$ 직접 간선이 존재하더라도, $u \to w_1 \to \dots \to v$처럼 2단계 이상의 대체 경로가 존재하면 해당 직접 간선은 층서학적 **중복(Redundant Shortcut)**으로 판정하여 제거합니다.
- 중복 간선이 모두 제거된 간선 집합이 최종 **표준 해리스 매트릭스(Canonical Harris Matrix)**가 됩니다.

### 4. 층위 단계(Stratigraphic Phases / Horizons) 계산
- 가장 기저층(부모가 없는 기반암/자연 토양, 진입 차수 0)의 위상을 Phase 1로 지정합니다.
- 각 지층 $v$의 위상 단계는 자신으로 들어오는 모든 선행 지층 $u$에 대해:
  $$\text{phase}(v) = 1 + \max_{(u, v) \in E} \text{phase}(u)$$

### 5. 탄소-14 보정 곡선(IntCal) 및 역전 이상 탐지
- 연대 보정 앵커 포인트(서기 -1000년 ~ 1600년) 구간에서 선형 보간(Piecewise Linear Interpolation)을 통해 보정 탄소 연대 $\mu_{\text{cal}}(y)$와 표준편차 $\sigma_{\text{cal}}(y)$를 계산합니다.
- 탄소 측정치 $(T_{\text{BP}} \pm \sigma_{\text{BP}})$에 대해 서기 연도 $y \in [-1000, 1600]$ (5년 간격)의 사후 확률 밀도 $P(y) \propto \frac{1}{\sqrt{\sigma_{\text{BP}}^2 + \sigma_{\text{cal}}(y)^2}} \exp\left(-\frac{(T_{\text{BP}} - \mu_{\text{cal}}(y))^2}{2(\sigma_{\text{BP}}^2 + \sigma_{\text{cal}}(y)^2)}\right)$를 계산하여 정규화합니다.
- 기대 달력 연대($\text{mean\_cal\_ad}$)와 95.4% 신용 구간($\text{range\_95\_ad}$)을 도출합니다.
- **층서학적 연대 역전(Stratigraphic Age Inversion)**:
  - 표준 해리스 매트릭스의 직접 간선 $u \to v$에 대해, $u$가 더 오래된 층이므로 달력 연대 또한 $\text{mean\_cal\_ad}(u) \le \text{mean\_cal\_ad}(v)$이어야 합니다.
  - 만약 아래층 $u$의 연대가 위층 $v$보다 $2 \times \sqrt{\sigma_u^2 + \sigma_v^2}$를 초과하여 젊다면, 후대 동물의 굴파기나 도굴로 인한 현대 유물 침입(`STRATIGRAPHIC_AGE_INVERSION`)으로 판정합니다.

---

## 입력 형식

표준 입력(`sys.stdin`)으로 유적지 지층 목록, 층서 관계 목록, 탄소 연대 측정 데이터가 포함된 JSON이 주어집니다:
```json
{
  "site_name": "Gyeongju_Wolseong_Palace_Site",
  "contexts": [
    {"id": "L1_Topsoil", "type": "DEPOSIT"},
    {"id": "L2_Floor", "type": "STRUCTURE"},
    {"id": "L3_Bedrock", "type": "NATURAL"}
  ],
  "relationships": [
    {"source": "L1_Topsoil", "target": "L2_Floor", "type": "ABOVE"},
    {"source": "L2_Floor", "target": "L3_Bedrock", "type": "ABOVE"},
    {"source": "L1_Topsoil", "target": "L3_Bedrock", "type": "ABOVE"}
  ],
  "c14_samples": [
    {"context_id": "L2_Floor", "c14_age_bp": 500, "c14_error_bp": 25, "material": "WOOD_CHARCOAL"}
  ]
}
```

---

## 출력 형식

표준 출력(`sys.stdout`)으로 이행 축소된 표준 해리스 매트릭스, 층위 단계, 보정 연대, 이상치 분석 결과가 포함된 단일 라인 JSON을 출력합니다:
```json
{
  "site_name": "Gyeongju_Wolseong_Palace_Site",
  "is_valid_dag": true,
  "error": null,
  "topological_sequence": ["L3_Bedrock", "L2_Floor", "L1_Topsoil"],
  "canonical_harris_matrix": [
    {"source": "L2_Floor", "target": "L1_Topsoil"},
    {"source": "L3_Bedrock", "target": "L2_Floor"}
  ],
  "stratigraphic_phases": {
    "L1_Topsoil": 3,
    "L2_Floor": 2,
    "L3_Bedrock": 1
  },
  "c14_chronology": {
    "L2_Floor": {
      "mean_cal_ad": 1435.2,
      "std_ad": 22.4,
      "range_95_ad": [1395, 1475],
      "material": "WOOD_CHARCOAL",
      "stratigraphic_phase": 2
    }
  },
  "stratigraphic_anomalies": [],
  "summary": {
    "total_contexts": 3,
    "total_relationships": 3,
    "canonical_edges_count": 2,
    "redundant_edges_removed": 1,
    "max_phase": 3,
    "anomalies_count": 0,
    "archaeological_interpretation": "CHRONOLOGY_CONSISTENT_WITH_STRATIGRAPHY"
  }
}
```
