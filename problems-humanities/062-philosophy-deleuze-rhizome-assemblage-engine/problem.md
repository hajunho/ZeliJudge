# 질 들뢰즈 & 펠릭스 과타리: 리좀, 아상블라주 및 탈영토화 엔진 (Gilles Deleuze & Félix Guattari: Rhizome, Assemblage & Deterritorialization Engine)

## 문제 설명

20세기 프랑스 후기구조주의 철학의 거장 **질 들뢰즈(Gilles Deleuze, 1925~1995)**와 정신분석학자 **펠릭스 과타리(Félix Guattari, 1930~1992)**는 불후의 명저 『천 개의 고원: 자본주의와 분열증 2』(*Mille Plateaux: Capitalisme et schizophrénie 2*, 1980)에서 서구 전통 사유를 지배해 온 **수목형(Arborescent/Tree) 위계 구조**를 해체하고, 탈중앙화된 생성과 접속의 사유 모델인 **리좀(Rhizome)**과 **아상블라주(Assemblage, 배치)** 이론을 제시했습니다.

### 1. 수목형(Tree) vs 리좀형(Rhizome)
- **수목형 모델 (Arborescent Model)**:
  - 단일한 뿌리(Root)와 줄기, 2분법적 가지(Binary Branching)로 뻗어나가는 중앙 집중적·피라미드형 위계 질서입니다.
  - 서구 관료제, 전통 언어학의 수형도(Chomsky Tree), 가부장적 질서, 중앙집권형 데이터베이스가 이에 해당합니다.
- **리좀형 모델 (Rhizomatic Model)**:
  - 감자, 대나무, 잔디의 지하경(버섯의 균사체)처럼 중심이나 시작도 끝도 없이 오직 **'중간(Milieu)'**에서만 무한히 증식하는 수평적 그물망입니다.
  - 월드와이드웹(WWW), P2P 네트워크, 탈중앙화 블록체인, 생태학적 공생계가 이에 해당합니다.

### 2. 리좀의 6대 원리
1. **접속(Connection)과 이질성(Heterogeneity)**: 리좀의 어느 한 지점은 다른 어떤 지점과도 연결될 수 있으며, 언어·기계·생물·욕망 등 이질적인 요소들이 경계 없이 접속합니다.
2. **다양체(Multiplicity)**: 하나(1)가 분기하는 것이 아니라 언제나 $n-1$의 복수성으로 작동합니다.
3. **비의미적 단절(Asignifying Rupture)**: 어느 한 부분이 잘리거나 파괴되어도 죽지 않고, 그 절단면을 따라 새로운 **탈주선(Ligne de fuite)**을 그리며 다른 곳에서 부활합니다.
4. **지도제작법(Cartography)과 전사(Decalcomania)**: 이미 정해진 원본을 베끼는 모사(Tracing)가 아니라, 언제나 새로운 길을 열어젖히는 열린 지도(Map)를 그립니다.

### 3. 영토화(Territorialization)와 탈영토화(Deterritorialization)
모든 아상블라주는 두 개의 극 사이에서 진동합니다:
- **영토화도($T \in [0.0, 1.0]$)**:
  - $T$가 높으면 규칙과 법률, 위계로 구획된 **'홈패인 공간(Striated Space)'**이자 수목형 질서(`ARBORESCENT_TREE` / `OVERCODED_ARBORESCENT`)가 됩니다.
  - 외부 충격(Perturbation)의 강도가 파열 임계치(`rupture_threshold`)를 돌파하면 **탈주선(Line of Flight)**이 터져 나오며 탈영토화(`DETERRITORIALIZATION_RUPTURE`)가 일어나 위계적 경계가 무너지고 매끄러운 공간(`RHIZOMATIC_MULTIPLICITY`)으로 전이됩니다.
  - 반대로 제도나 자본에 의해 새로운 코드가 덧씌워지면 재영토화(`RETERRITORIALIZATION_CONSOLIDATED`)가 진행되어 질서가 재고착됩니다.

본 문제는 들뢰즈와 과타리의 리좀 네트워크 토폴로지, 탈주선 돌파, 탈영토화 및 재영토화 전이 동역학을 시뮬레이션하는 철학적 복합계 그래프 엔진을 구현하는 것입니다.

```
                  [ 수목형 위계 질서 (Arborescent Tree) ]
                           ROOT (영토화도 T = 0.85)
                          /    \
                     DEPT_A    DEPT_B
                        |
                        v
         [ 유목민적 외부 충격 (Perturbation / Desire Surge) ]
                        |
                        v
          강도(Intensity) >= 임계치(Threshold) ?
               /                              \
           (성공)                            (실패)
             |                                 |
    [ 탈주선 (Line of Flight) ]        [ 지층에 포획됨 (Captured) ]
    - 이질적 노드 간 신규 리좀 연결   - T 및 구조 유지
    - 영토화도 급감 (T_new = T - Δ)
    - 매끄러운 공간으로 전이:
      RHIZOMATIC_MULTIPLICITY
```

---

## 알고리즘 및 상태 전이 명세

### 1. 기본 설정 및 네트워크 초기화
- **파열 임계치 ($	au$)**: `config.rupture_threshold` (기본값: $0.60$)
- **초기 노드 및 엣지**: 고원(Plateau) 노드 집합 $V$와 초기 엣지 목록 $E$.
- **아상블라주 상태**: 초기 영토화도 $T \in [0.0, 1.0]$ 및 지층 유형 (`stratum_type`).

### 2. 동적 사건(Perturbation) 시계열 전이

각 사건에 대해:

#### 1) 탈주선 사건 (`LINE_OF_FLIGHT`)
- 입력: 충격 강도 $I \in [0.0, 1.0]$, 원천 노드 $source$, 대상 노드 $target$.
- 판정:
  - **$I \ge 	au - 10^{-7}$인 경우 (탈영토화 파열 성공)**:
    - $source$와 $target$ 사이에 새로운 무방향 리좀 연결을 생성합니다.
    - 영토화도 감쇄:
      $$T_{new} = \max(0.0, 	ext{round}(T - I 	imes 0.30, 4))$$
    - 지층 상태 갱신:
      - $T_{new} < 0.40 \implies$ `"RHIZOMATIC_MULTIPLICITY"` (리좀적 다양체 / 매끄러운 공간)
      - $T_{new} < 0.70 \implies$ `"STABILIZED_ASSEMBLAGE"` (안정화된 아상블라주)
      - 그 외 $\implies$ 기존 유지
    - 판정: `"DETERRITORIALIZATION_RUPTURE"`, 연결 생성 기록: `[source, target]`.
  - **$I < 	au - 10^{-7}$인 경우 (지층에 포획)**:
    - 연결 생성 없음, $T$ 변동 없음.
    - 판정: `"CAPTURED_BY_STRATUM"`, 연결 생성 기록: `null`.

#### 2) 재영토화 사건 (`RETERRITORIALIZATION`)
- 입력: 강도 $I \in [0.0, 1.0]$.
- 영토화도 가산:
  $$T_{new} = \min(1.0, 	ext{round}(T + I 	imes 0.25, 4))$$
- 지층 상태 갱신:
  - $T_{new} \ge 0.70 \implies$ `"OVERCODED_ARBORESCENT"` (초과코드화된 수목형 지층)
  - $T_{new} \ge 0.40 \implies$ `"STABILIZED_ASSEMBLAGE"` (안정화된 아상블라주)
  - 그 외 $\implies$ `"RHIZOMATIC_MULTIPLICITY"`
- 판정: `"RETERRITORIALIZATION_CONSOLIDATED"`.

### 3. 최종 요약 통계 (Summary)
모든 사건 처리 후:
- `assemblage_name`: 아상블라주 명칭
- `final_territorialization`: 최종 영토화도 $T$ (소수점 넷째 자리)
- `final_stratum_type`: 최종 지층 상태 문자열
- `total_plateau_nodes`: 총 고원 노드 수
- `total_rhizome_connections`: 총 리좀 무방향 엣지 수
- `average_rhizomatic_degree`: 평균 연결 차수 $	ext{round}\left(rac{2 	imes E}{V}, 4ight)$

---

## 입력 형식 (Input JSON Schema)

```json
{
  "config": {
    "rupture_threshold": 0.55
  },
  "assemblage": {
    "name": "bureaucratic_monarchy",
    "territorialization": 0.85,
    "stratum_type": "ARBORESCENT_TREE"
  },
  "nodes": [
    {"id": "KING"},
    {"id": "MINISTER_WAR"},
    {"id": "MINISTER_FINANCE"},
    {"id": "NOMADIC_TRIBE"}
  ],
  "edges": [
    {"source": "KING", "target": "MINISTER_WAR"},
    {"source": "KING", "target": "MINISTER_FINANCE"}
  ],
  "perturbations": [
    {
      "type": "LINE_OF_FLIGHT",
      "intensity": 0.80,
      "source": "NOMADIC_TRIBE",
      "target": "MINISTER_WAR"
    }
  ]
}
```

---

## 출력 형식 (Output JSON Schema)

```json
{
  "summary": {
    "assemblage_name": "bureaucratic_monarchy",
    "final_territorialization": 0.61,
    "final_stratum_type": "STABILIZED_ASSEMBLAGE",
    "total_plateau_nodes": 4,
    "total_rhizome_connections": 3,
    "average_rhizomatic_degree": 1.5
  },
  "event_history": [
    {
      "event_index": 1,
      "type": "LINE_OF_FLIGHT",
      "intensity": 0.8,
      "details": {
        "outcome": "DETERRITORIALIZATION_RUPTURE",
        "territorialization_level": 0.61,
        "stratum_type": "STABILIZED_ASSEMBLAGE",
        "connection_created": [
          "NOMADIC_TRIBE",
          "MINISTER_WAR"
        ]
      }
    }
  ]
}
```

---

## 제약 조건

- $1 \le 	ext{nodes} \le 100$
- $0 \le 	ext{edges} \le 500$
- $1 \le 	ext{perturbations} \le 100$
- 모든 부동 소수점 수치는 소수점 넷째 자리까지 반올림(`round(v, 4)`)하여 기록합니다.
- 표준 입력(`sys.stdin`)으로부터 UTF-8 JSON 문자열을 수신하고, 결과를 `json.dumps(..., ensure_ascii=False)`로 표준 출력에 인쇄합니다.
