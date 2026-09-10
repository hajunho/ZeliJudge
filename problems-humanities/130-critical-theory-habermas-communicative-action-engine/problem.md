# 위르겐 하버마스의 의사소통행위이론: 공론장, 생활세계의 식민지화 및 담론 윤리학 엔진

## 문제 설명

20세기 비판이론(Critical Theory)을 대표하는 독일의 철학자이자 사회학자 **위르겐 하버마스(Jürgen Habermas, 1929~)**는 그의 불후의 주저 『의사소통행위이론(Theorie des kommunikativen Handelns, 1981)』을 통해 아도르노와 호르크하이머의 도구적 이성 비판이 봉착한 비관주의적 아포리아를 돌파하고, **의식 철학(주체 중심)에서 언어·의사소통 철학(상호주관성 중심)으로의 거대한 패러다임 전환**을 이룩했습니다.

하버마스는 근대 사회를 두 개의 대립적 층위로 모델링합니다:
1. **생활세계 (Lifeworld / Lebenswelt)**:
   - 문화적 재생산(Cultural Meaning), 사회적 통합(Social Integration), 그리고 사회화(Socialization)를 담당하는 상호주관적 배경입니다.
   - 구성원 간의 합의는 오직 언어적 상호작용과 상호이해를 지향하는 **의사소통행위(Communicative Action)**를 통해서만 형성됩니다.
2. **체계 (System / System)**:
   - 경제와 관료국가로 대표되는 영역으로, 효율성과 전략적 성공만을 추구하는 도구적·전략적 행위(Strategic Action)로 작동합니다.
   - 체계는 언어적 합의 과정을 생략하기 위해 **화폐(Money)**와 **권력(Power)**이라는 비언어적 조종 매체(Steering Media)를 사용합니다.
3. **생활세계의 식민지화 (Colonization of the Lifeworld)**:
   - 체계의 조종 매체(화폐의 논리와 관료주의적 권력)가 본래 의사소통적 합의에 의해 운영되어야 할 생활세계(가족, 교육, 법, 공론장, 문화)의 핵심 영역으로 침투하여, 연대성과 도덕적 합의를 파괴하고 구성원들을 원자화·도구화하여 아노미와 정당성의 위기(Legitimation Crisis)를 유발하는 현대 사회의 병리 현상입니다.

### 이상적 담화 상황 (Ideal Speech Situation)과 4대 타당성 요구 (Validity Claims)
하버마스에 따르면 모든 발화 행위(Speech Act)는 상대방과의 상호 이해를 위해 다음 **4대 보편적 타당성 요구**를 제기합니다:
1. **이해가능성 (Comprehensibility / Verständlichkeit)**: 언어적으로 문법에 맞고 의미가 전달되어야 함. 화자의 의사소통 역량(`competence`)에 좌우됨.
2. **진리성 (Truth / Wahrheit)**: 객관적 세계에 속한 사실과 증거(`evidence_score`)에 부합해야 함.
3. **정당성 (Rightness / Richtigkeit)**: 사회적 상호작용 규범과 도덕적 의무(`normative_justification` & `lifeworld_anchoring`)에 부합해야 함.
4. **진실성 (Truthfulness / Sincerity / Wahrhaftigkeit)**: 주관적 내면의 기만이나 허위의식이 없어야 함(`sincerity_score`).

또한 담론 윤리학(Discourse Ethics)의 핵심인 **이상적 담화 상황**은 다음 조건을 만족해야 합니다:
- **강제로부터의 자유 (Freedom from Coercion)**: 어떠한 뇌물(화폐)이나 위협/행정명령(권력)도 개입하지 않아야 함.
- **참여의 대칭성 (Symmetry of Participation)**: 모든 이해당사자가 배제 없이 동등하게 발언할 수 있어야 함 (`symmetry_ratio >= 0.50`).
- **더 나은 논증의 강제 없는 힘 (Unforced Force of the Better Argument)**: 반론(`objection`)에 의해 논박되지 않고 4대 타당성 요구가 모두 검증($\ge 0.65$)될 때에만 진정한 민주적 규범 합의(`CONSENSUS_REACHED`)에 도달합니다.

주어진 공론장 참여자, 생활세계 초기 지표, 그리고 일련의 담론 세션(의사소통적 토론 및 체계 조종 매체 침투)을 시뮬레이션하여 세션별 합의 결과(`history`)와 생활세계의 최종 상태 및 식민지화 병리(`summary`)를 평가하는 비판이론 엔진을 구현하십시오.

```
+-----------------------------------------------------------------------------------------+
|                  Habermas Communicative Action & Lifeworld Engine                       |
+-----------------------------------------------------------------------------------------+
                     [ Session Input: Proposed Norm / Interaction Type ]
                                                |
                       +------------------------+------------------------+
                       | Interaction Type == COMMUNICATIVE?              |
                       +------------------------+------------------------+
                               /                                                              YES                               NO (STRATEGIC)
                               |                                  |
                +--------------+--------------+         +---------+---------+
                | Check 4 Validity Claims:     |         | System Intrusion? |
                |  - Comprehensibility >= 0.65 |         | (Bribe / Power)   |
                |  - Truth >= 0.65             |         +---------+---------+
                |  - Rightness >= 0.65         |            /                             |  - Truthfulness >= 0.65      |        YES               NO
                | Check Symmetry (>= 0.50)     |         |                 |
                | Check Coercion-Free (0/0)    |   [ COLONIZED ]     [ DEADLOCK ]
                | Unresolved Objections == 0   |   [ COMPROMISE ]
                +--------------+---------------+         |
                               |                   Erode Lifeworld
                   +-----------+-----------+       Increase Colonization Index
                  /                                          YES                         NO
                  |                           |
         [ CONSENSUS_REACHED ]           [ DISSENSUS ]
         * Unforced Force of Better      * Legitimacy Drops
           Argument Prevails             * Explains Failed Claims
         * Lifeworld Enrichment          * Pathology Evaluation
           (+Integration, -Colonization)
```

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다.
```json
{
  "config": {
    "participants": [
      {"id": "citizen_A", "competence": 0.95, "lifeworld_anchoring": 0.90},
      {"id": "citizen_B", "competence": 0.92, "lifeworld_anchoring": 0.88},
      {"id": "teacher_C", "competence": 0.96, "lifeworld_anchoring": 0.95}
    ],
    "lifeworld": {
      "cultural_meaning": 800.0,
      "social_integration": 800.0,
      "socialization": 800.0,
      "colonization_index": 0.12
    }
  },
  "sessions": [
    {
      "session_id": 1,
      "target_norm": "Universal Free Public Education Policy",
      "interaction_type": "COMMUNICATIVE",
      "claims": [
        {"speaker_id": "citizen_A", "claim_type": "COMPREHENSIBILITY", "comprehensibility": 0.98},
        {"speaker_id": "teacher_C", "claim_type": "TRUTH", "evidence_score": 0.92},
        {"speaker_id": "citizen_B", "claim_type": "RIGHTNESS", "normative_justification": 0.95},
        {"speaker_id": "citizen_A", "claim_type": "TRUTHFULNESS", "sincerity_score": 0.90}
      ],
      "objections": []
    }
  ]
}
```

### 필드 상세 설명:
- `config`:
  - `participants`: 공론장 참여자 목록:
    - `id`: 고유 식별자 문자열.
    - `competence` ($0.0 \le \text{competence} \le 1.0$): 언어적·논증적 의사소통 역량.
    - `lifeworld_anchoring` ($0.0 \le \text{lifeworld\_anchoring} \le 1.0$): 생활세계 가치 지향성 (낮을수록 도구적·이기적 성향).
  - `lifeworld`: 생활세계 자원 지표:
    - `cultural_meaning`: 문화적 재생산 점수 ($0 \sim 1000$).
    - `social_integration`: 사회적 통합 및 연대 점수 ($0 \sim 1000$).
    - `socialization`: 사회화 및 자아 정체성 점수 ($0 \sim 1000$).
    - `colonization_index`: 체계 식민지화 지수 ($0.0 \sim 1.0$).
- `sessions`: 순차적으로 열리는 토론 및 규범 제정 세션:
  - `session_id`: 세션 일련번호.
  - `target_norm`: 제안된 규범 또는 정책 안건 명칭.
  - `interaction_type`: `"COMMUNICATIVE"` (상호 이해 지향) 또는 `"STRATEGIC"` (자기 잇속·체계 지향).
  - `claims`: 제시된 주장 목록:
    - `speaker_id`: 발언자 ID.
    - `claim_type`: `"COMPREHENSIBILITY"`, `"TRUTH"`, `"RIGHTNESS"`, `"TRUTHFULNESS"`.
    - `comprehensibility`, `evidence_score`, `normative_justification`, `sincerity_score`: 주장별 질적 척도.
  - `system_intrusion`: 체계 조종 매체 개입 (선택적):
    - `bribe_money`: 금전적 매수/로비 금액.
    - `coercive_power`: 행정명령/물리적 강제력 위협 강도.
  - `objections`: 반론 목록:
    - `target_claim`: 공격 대상 타당성 요구.
    - `strength`: 반론의 설득력/반박 강도.

## 출력 형식

표준 출력(stdout)으로 JSON 객체를 한 줄로 출력합니다 (`separators=(',', ':')`).
```json
{
  "history": [
    {
      "session_id": 1,
      "target_norm": "Universal Free Public Education Policy",
      "interaction_type": "COMMUNICATIVE",
      "status": "CONSENSUS_REACHED",
      "legitimacy_score": 0.817,
      "claim_scores": {
        "COMPREHENSIBILITY": 0.931,
        "TRUTH": 0.92,
        "RIGHTNESS": 0.836,
        "TRUTHFULNESS": 0.9
      },
      "symmetry_ratio": 1.0,
      "detail": "unforced force of the better argument prevailed; rational communicative consensus achieved"
    }
  ],
  "summary": {
    "total_sessions": 1,
    "consensus_count": 1,
    "colonized_count": 0,
    "dissensus_count": 0,
    "lifeworld_status": {
      "cultural_meaning": 820.0,
      "social_integration": 825.0,
      "socialization": 800.0,
      "colonization_index": 0.09,
      "pathology_state": "HEALTHY_DEMOCRATIC_SPHERE"
    },
    "legitimate_norms_count": 1,
    "distorted_norms_count": 0
  }
}
```

### 요약 필드 설명:
- `total_sessions`: 총 토론 세션 수.
- `consensus_count`: 이상적 담화 상황을 충족하여 합의된 규범 수.
- `colonized_count`: 화폐나 권력의 개입으로 굴절된 식민지화된 사이비 합의 수.
- `dissensus_count`: 논박되거나 불화로 끝난 세션 수.
- `lifeworld_status`: 최종 생활세계 상태 및 식민지화 지수, 병리 상태 진단:
  - `pathology_state`:
    - `HEALTHY_DEMOCRATIC_SPHERE` ($colonization\_index < 0.40$)
    - `SIGNIFICANT_SYSTEM_COLONIZATION` ($0.40 \le colonization\_index < 0.70$)
    - `LEGITIMATION_CRISIS_AND_ANOMIE` ($colonization\_index \ge 0.70$)
- `legitimate_norms_count`: 정당한 규범 목록 수.
- `distorted_norms_count`: 왜곡된 규범 목록 수.
