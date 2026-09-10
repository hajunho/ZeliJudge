# [사회학/사회연결망분석] 마크 그라노베터의 '약한 유대의 힘'과 로널드 버트의 '구조적 공백' 네트워크 중심성 분석 엔진

## 문제 설명

사회학(Sociology)과 사회연결망분석(Social Network Analysis, SNA)에서 인간 관계망의 구조가 개인의 취업, 조직 내 승진, 정보 확산, 그리고 혁신 창출에 미치는 영향은 20세기 사회과학의 가장 위대한 발견 중 하나입니다.

### 1. 마크 그라노베터의 약한 유대의 힘 (Mark Granovetter, 1973)
스탠퍼드 대학교의 사회학자 마크 그라노베터(Mark Granovetter)는 명논문 《The Strength of Weak Ties》(사회학 역사상 최다 인용 논문)에서 다음과 같은 혁신적 통찰을 제시했습니다:
- **강한 유대(Strong Ties)**: 매일 연락하는 가족, 친한 친구, 같은 팀 동료. 삼항 폐쇄(Triadic Closure)로 인해 서로 모두 아는 닫힌 관계망을 형성하므로, 새로운 외부 정보가 유입되지 않고 동일한 정보만 내부에서 맴돕니다.
- **약한 유대(Weak Ties)**: 어쩌다 연락하는 동창, 지인, 타 부서 동료. 서로 다른 응집된 클러스터를 이어주는 **로컬 브릿지(Local Bridge)** 역할을 수행하여, 새로운 채용 기회, 혁신 아이디어, 외부 트렌드를 전달하는 결정적 정보 파이프라인이 됩니다.

### 2. 로널드 버트의 구조적 공백과 사회적 자본 (Ronald Burt, 1992)
시카고 대학교의 사회학자 로널드 버트(Ronald Burt)는 《Structural Holes: The Social Structure of Competition》에서 네트워크 내에 서로 연결되지 않은 집단들 사이의 단절을 **구조적 공백(Structural Holes)**이라 정의했습니다.
- 개인이 구조적 공백을 잇는 위치(Brokerage)를 점유할 때, 중복 없는 정보에 조기 접근(Early Access)하고 다른 집단 간의 이해관계를 조율(Tertius Gaudens)함으로써 압도적인 사회적 자본(Social Capital)과 성과를 얻게 됩니다.
- 이를 측정하기 위한 핵심 지표가 바로 **네트워크 제약도(Network Constraint, $C_i$)**와 **유효 규모(Effective Size, $ES_i$)**입니다.

HR 피플 분석(People Analytics), 링크드인(LinkedIn) 채용 네트워크, 조직 진단(Organizational Network Analysis, ONA) 플랫폼의 엔지니어가 되어, 소셜 그래프 데이터를 바탕으로 **약한 유대/강한 유대 판별**, **로컬 브릿지(Local Bridge) 탐지**, **이웃 중복도(Neighborhood Overlap)**, **버트의 네트워크 제약도 및 유효 규모**, **매개 중심성(Betweenness Centrality)**을 원스톱으로 계산하고 행위자의 **사회학적 역할(Sociological Role)**을 자동 분류하는 분석 엔진을 구현하십시오.

---

## 사회학적 수식 및 계산 규격

### 1. 관계(Tie) 유형 및 이웃 중복도 (Neighborhood Overlap)
- 두 행위자 $u, v$의 연결 가중치 $w_{uv}$가 주어질 때:
  - $w_{uv} \ge 	ext{strong\_tie\_threshold}$ 이면 `STRONG_TIE`
  - $w_{uv} < 	ext{strong\_tie\_threshold}$ 이면 `WEAK_TIE`
- **이웃 중복도 (Neighborhood Overlap)**:
  $$O(u, v) = rac{|N(u) \cap N(v)|}{|N(u) \cup N(v)| - 2} \quad (|N(u) \cup N(v)| > 2 	ext{ 일 때, 그 외 } 0.0)$$
- **로컬 브릿지 (Local Bridge)**:
  두 행위자 사이에 공통 이웃이 전혀 없는 경우 ($|N(u) \cap N(v)| = 0 \iff O(u, v) = 0.0$), 해당 에지는 서로 다른 커뮤니티를 유일하게 이어주는 `is_local_bridge = True`로 판정합니다.

### 2. 국소 결집 계수 (Local Clustering Coefficient) 및 유효 규모 (Effective Size)
행위자 $u$의 이웃 수 $k_u = |N(u)|$에 대해:
- **국소 결집 계수 ($C_u$)**:
  $$C_u = rac{2 \cdot |\{ (v, w) \in E \mid v, w \in N(u) \}|}{k_u (k_u - 1)} \quad (k_u \ge 2 	ext{ 일 때, } k_u < 2 	ext{ 이면 } 0.0)$$
- **로널드 버트의 유효 규모 ($ES_u$)**:
  $u$가 맺고 있는 관계 중 중복(Redundancy)을 제외한 실질적 비중복 접점 수:
  $$ES_u = k_u - rac{2 \cdot |\{ (v, w) \in E \mid v, w \in N(u) \}|}{k_u} \quad (k_u \ge 2 	ext{ 일 때, } k_u < 2 	ext{ 이면 } k_u)$$

### 3. 로널드 버트의 네트워크 제약도 (Network Constraint, $C_u$)
행위자 $u$의 관계망에서 상대방 $v$에 대한 투자 비율 $p_{uv} = rac{w_{uv}}{\sum_{k \in N(u)} w_{uk}}$:
- $u$가 $v$에게 받는 개별 제약도:
  $$c_{uv} = \left( p_{uv} + \sum_{q \in N(u) \setminus \{v\}} p_{uq} p_{qv} ight)^2$$
- $u$의 전체 **네트워크 제약도 ($C_u$)**:
  $$C_u = \sum_{v \in N(u)} c_{uv}$$
  (제약도가 낮을수록 구조적 공백을 많이 장악한 자유로운 브로커이며, 높을수록 이웃들의 닫힌 연결망에 종속됨).

### 4. 매개 중심성 (Betweenness Centrality, 정규화)
- 브랜디스(Brandes) 알고리즘으로 계산된 비방향 최단 경로 중개 수 $BC(u)$:
  $$BC_{	ext{norm}}(u) = rac{2 \cdot BC(u)}{(n - 1)(n - 2)} \quad (n > 2 	ext{ 일 때, 그 외 } 0.0)$$

### 5. 사회학적 역할 분류 (`sociological_role`)
- $k_u \le 1$: `"PERIPHERAL_ISOLATE"` (고립자)
- $C_u \le 0.35$ AND $BC_{	ext{norm}}(u) \ge 0.15$: `"KEY_BROKER"` (구조적 공백을 지배하는 핵심 브로커)
- $C_u(	ext{clustering}) \ge 0.60$ AND $C_u(	ext{constraint}) \ge 0.55$: `"COHESIVE_INSIDER"` (응집된 내부자)
- 그 외: `"GENERAL_ACTOR"` (일반 구성원)

---

## 입력 형식

표준 입력(`sys.stdin`)으로 단일 JSON 객체가 주어집니다:
```json
{
  "network_id": "ORG_NETWORK_01",
  "strong_tie_threshold": 5.0,
  "nodes": ["A1", "A2", "BRIDGE_A", "BRIDGE_B", "B1"],
  "edges": [
    {"source": "A1", "target": "A2", "weight": 8.0},
    {"source": "A1", "target": "BRIDGE_A", "weight": 7.0},
    {"source": "BRIDGE_A", "target": "BRIDGE_B", "weight": 2.0},
    {"source": "BRIDGE_B", "target": "B1", "weight": 8.0}
  ]
}
```

---

## 출력 형식

표준 출력(`sys.stdout`)으로 계산된 결과를 JSON 문자열(단일 라인)로 출력합니다:
```json
{
  "network_id": "ORG_NETWORK_01",
  "total_actors": 5,
  "total_ties": 4,
  "summary": {
    "strong_ties_count": 3,
    "weak_ties_count": 1,
    "local_bridges_count": 3,
    "key_brokers_count": 0,
    "cohesive_insiders_count": 0
  },
  "actors": {
    "BRIDGE_A": {
      "degree": 2,
      "clustering_coefficient": 0.0,
      "effective_size": 2.0,
      "burt_constraint": 0.6521,
      "betweenness_centrality": 0.5,
      "sociological_role": "GENERAL_ACTOR"
    }
  },
  "ties": [
    {
      "source": "BRIDGE_A",
      "target": "BRIDGE_B",
      "weight": 2.0,
      "tie_type": "WEAK_TIE",
      "common_neighbors_count": 0,
      "neighborhood_overlap": 0.0,
      "is_local_bridge": true
    }
  ]
}
```
