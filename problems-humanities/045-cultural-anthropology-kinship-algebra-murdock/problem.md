# Problem #045: 문화인류학 친족 대수학(Kinship Algebra)과 조지 머독(G. P. Murdock) 6대 친족 호칭 체계 분류기

## 1. 개요 및 인문학적 배경 (Overview & Humanistic Background)

인류학(Anthropology)과 구조주의(Structuralism)의 역사에서 가장 눈부신 수학적·체계적 성취 중 하나는 바로 **친족 체계(Kinship System)**의 형식화입니다. 20세기 중반, 프랑스의 인류학자 **클로드 레비-스트로스(Claude Lévi-Strauss, 1908~2009)**는 기념비적 저작 『친족의 기본 구조(*Les Structures élémentaires de la parenté*, 1949)』를 통해 인간 사회의 친족과 혼인 규칙이 자의적인 관습이 아니라 정밀한 **대수학적 군론(Group Theory)과 교환 대칭성**을 따른다는 사실을 입증했습니다.

동시에 미국의 문화인류학자 **조지 피터 머독(George Peter Murdock, 1897~1985)**은 전 세계 수백 개 부족 사회의 친족 용어를 비교 분석하여, 인류의 친족 호칭 체계가 단 **6대 기본 유형(Murdock's 6 Major Kinship Terminology Systems)**으로 수렴함을 밝혀냈습니다:

```
+---------------------------------------------------------------------------------------------------+
|                        Murdock's 6 Major Kinship Terminology Systems                              |
+---------------------------------------------------------------------------------------------------+
 1. 하와이식 (Hawaiian) : 세대주의(Generational). 부모 세대 남성은 모두 '아버지', 여성은 모두 '어머니'.
                         모든 사촌을 '형제/자매'로 부르며 전원 혼인 금기(Incest Taboo).
 2. 에스키모식 (Eskimo) : 직계/핵가족 중심(Bilateral). 아버지/어머니/형제/자매만 단독 호칭.
                         삼촌/외삼촌은 'Uncle', 모든 사촌(평행/교차)은 단일한 'Cousin'으로 통합.
 3. 이로쿼이식 (Iroquois): 이분합류(Bifurcate Merging). 부계/모계 성별 일치 시 합류(F=FB, M=MZ).
                         평행사촌(FBS, MZS)은 '형제/자매'로 금기, 교차사촌(MBD, FZD)은 호칭 분리 및 혼인 권장!
 4. 크로우식 (Crow)     : 모계제 세대 편향(Matrilineal Skewing). 고모 딸(FZD)은 '고모', 고모 아들(FZS)은 '아버지'로
                         한 세대 위로 승격! 외삼촌 자녀(MBS, MBD)는 '자식/조카'로 하강.
 5. 오마하식 (Omaha)    : 부계제 세대 편향(Patrilineal Skewing). 외삼촌 딸(MBD)은 '어머니', 아들(MBS)은 '외삼촌'으로
                         한 세대 위로 승격! 고모 자녀(FZS, FZD)는 '조카'로 하강.
 6. 수단식 (Sudanese)   : 완전 서술형(Descriptive). 8가지 사촌과 4가지 삼촌/고모/이모가 100% 독립된 고유 호칭 보유.
```

### 사촌의 이분법 (Parallel vs Cross Cousins)
- **평행사촌 (Parallel Cousins)**: 부모와 동성인 형제의 자녀 ($FBS$: 큰/작은아버지 아들, $MZD$: 이모 딸).
- **교차사촌 (Cross Cousins)**: 부모와 이성인 형제의 자녀 ($MBD$: 외삼촌 딸, $FZS$: 고모 아들).

레비-스트로스의 **동맹 이론(Alliance Theory)**에 따르면, 많은 원시 부족 사회에서 평행사촌은 자신의 형제자매로 분류되어 엄격한 근친상간 금기(Incest Taboo)의 대상이 되지만, 교차사촌은 다른 씨족(Clan/Moiety) 간의 지속적인 여성 교환을 유지하기 위한 **최우선 선호 혼인 대상(Preferred Marriage Partner)**이 됩니다.

이 문제에서는 가계도 그래프 및 친족 관계 코드를 바탕으로 친족 관계를 도출하고, 머독의 6대 친족 체계를 자동 분류하며, 레비-스트로스의 동맹 이론에 따른 혼인 적격성(Marriage Eligibility)을 판정하는 인류학 친족 대수 엔진을 구현합니다.

---

## 2. 입출력 규격 (Input & Output Specification)

### 입력 형식 (Standard Input)
표준 입력(stdin)으로 JSON 객체가 주어집니다.
```json
{
  "config": {
    "system_type": "AUTO_DETECT",
    "alliance_rule": "MATRILATERAL_ONLY"
  },
  "native_vocabulary": {
    "F": "tama", "FB": "tama", "MB": "tsita",
    "M": "na", "MZ": "na", "FZ": "kuri",
    "B": "tahka", "Z": "wehe",
    "FBS": "tahka", "FBD": "wehe", "MZS": "tahka", "MZD": "wehe",
    "MBS": "taha", "MBD": "weta", "FZS": "taha", "FZD": "weta"
  },
  "individuals": [
    {"id": "Ego", "gender": "M"},
    {"id": "Father", "gender": "M"},
    {"id": "Mother", "gender": "F"},
    {"id": "Uncle_Maternal", "gender": "M"},
    {"id": "Cousin_MBD", "gender": "F"},
    {"id": "GrandpaM", "gender": "M"},
    {"id": "GrandmaM", "gender": "F"}
  ],
  "parent_child": [
    ["GrandpaM", "Mother"], ["GrandmaM", "Mother"],
    ["GrandpaM", "Uncle_Maternal"], ["GrandmaM", "Uncle_Maternal"],
    ["Father", "Ego"], ["Mother", "Ego"],
    ["Uncle_Maternal", "Cousin_MBD"]
  ],
  "queries": [
    {"ego": "Ego", "target": "Cousin_MBD"}
  ]
}
```

- `config`:
  - `system_type`: 친족 체계 지정 (`"HAWAIIAN"`, `"ESKIMO"`, `"IROQUOIS"`, `"CROW"`, `"OMAHA"`, `"SUDANESE"`, 또는 자동 감지 `"AUTO_DETECT"`).
  - `alliance_rule`: 레비-스트로스 혼인 동맹 규칙 (`"BILATERAL_CROSS_COUSIN"`, `"MATRILATERAL_ONLY"`, `"PATRILATERAL_ONLY"`).
- `native_vocabulary`: 친족 관계 코드(`"F"`, `"FB"`, `"MB"`, `"FBS"`, `"MBD"` 등)를 현지 언어 단어로 매핑한 딕셔너리.
- `individuals` / `parent_child`: (선택 사항) 가계도 노드 및 엣지.
- `queries`: 평가 질의 목록.
  - `ego`: 기준인물 ID.
  - `target`: 대상인물 ID.
  - `relation_code`: (선택) 직접 관계 코드 지정 시 가계도 탐색 대신 우선 적용.

### 처리 규칙 (Processing Rules)

1. **머독 6대 체계 자동 식별 (`AUTO_DETECT`)**:
   - `native_vocabulary`가 주어졌을 때 핵심 칭호들의 동일성(Identity)을 비교하여 식별합니다:
     - **수단식 (`SUDANESE`)**: 부모 세대 6종과 사촌 8종이 모두 서로 다른 단어로 구별됨.
     - **하와이식 (`HAWAIIAN`)**: $F = FB = MB$, $M = MZ = FZ$, $B = FBS = MBS$.
     - **에스키모식 (`ESKIMO`)**: $F 
e FB$, $FB = MB$, $B 
e FBS$, $FBS = MBS$.
     - **이분합류 계열 ($F = FB 
e MB, B = FBS 
e MBS$)**:
       - 크로우식 (`CROW`): 모계 편향 $FZS = F$ 또는 $FZD = FZ$.
       - 오마하식 (`OMAHA`): 부계 편향 $MBS = MB$ 또는 $MBD = M$.
       - 이로쿼이식 (`IROQUOIS`): 세대 편향 없음.

2. **가계도 그래프 탐색 (Genealogy Traversal)**:
   - `relation_code`가 명시되지 않은 경우, `parent_child` 유향 그래프에서 Ego로부터 대상까지의 혈연 경로를 추적하여 표준 관계 코드(`F`, `M`, `FB`, `FZ`, `MB`, `MZ`, `FBS`, `FBD`, `FZS`, `FZD`, `MBS`, `MBD`, `MZS`, `MZD`, `B`, `Z`, `S`, `D`, `BS`, `BD`, `ZS`, `ZD`)를 결정론적으로 도출합니다.

3. **구조적 분류 (`structural_class`)**:
   - 직계: `PRIMARY_KIN` (`F, M, B, Z, S, D`)
   - 평행사촌: `PARALLEL_COUSIN` (`FBS, FBD, MZS, MZD`)
   - 교차사촌: `CROSS_COUSIN` (`MBS, MBD, FZS, FZD`)
   - 그 외: `COLLATERAL`

4. **혼인 적격성 평가 (`marriage_evaluation`)**:
   - 1차 친족 호칭(`FATHER, MOTHER, BROTHER, SISTER, SON, DAUGHTER`)으로 분류된 경우: 근친상간 금기 `INCEST_TABOO` (`eligible: false`).
   - 하와이식: 모든 사촌이 형제자매이므로 `INCEST_TABOO` (`eligible: false`).
   - 에스키모식: 서구 양측적 관습상 사촌 혼인 제한 `CULTURE_RESTRICTED` (`eligible: false`).
   - 이로쿼이/크로우/오마하:
     - 평행사촌: 형제자매 범주이므로 `INCEST_TABOO`.
     - 교차사촌:
       - `alliance_rule`이 `MATRILATERAL_ONLY`인데 대상이 $MBD$가 아닌 경우: `ALLIANCE_RESTRICTION` (`eligible: false`).
       - `alliance_rule`이 `PATRILATERAL_ONLY`인데 대상이 $FZD$가 아닌 경우: `ALLIANCE_RESTRICTION` (`eligible: false`).
       - 규칙 만족 시: `PREFERRED_CROSS_COUSIN` (`eligible: true`).

### 출력 형식 (Standard Output)
단일 행의 표준 JSON 형식으로 출력합니다.
```json
{
  "classified_system": "IROQUOIS",
  "alliance_rule": "MATRILATERAL_ONLY",
  "query_evaluations": [
    {
      "ego": "Ego",
      "target": "Cousin_MBD",
      "relation_code": "MBD",
      "structural_class": "CROSS_COUSIN",
      "canonical_term": "FEMALE_CROSS_COUSIN",
      "native_term": "weta",
      "marriage_evaluation": {
        "eligible": true,
        "status": "PREFERRED_CROSS_COUSIN",
        "reason": "Cross-cousin alliance eligible under IROQUOIS kinship"
      }
    }
  ]
}
```

---

## 3. 제약 사항 (Constraints)
- `individuals` 수: $1 \le N \le 50$
- `queries` 수: $1 \le Q \le 50$
- 친족 관계 코드는 표준 8대 기호(`F, M, B, Z, S, D, H, W`)의 조합을 따릅니다.
- Python 3 표준 라이브러리만 사용합니다 (`json`, `sys`).
