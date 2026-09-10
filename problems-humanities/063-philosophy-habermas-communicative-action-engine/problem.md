# 위르겐 하버마스: 의사소통행위이론, 4대 타당성 요구 및 이상적 담화 상황 합의 엔진 (Jürgen Habermas: Communicative Action & Ideal Speech Situation Engine)

## 문제 설명

20세기 후반과 21세기를 대표하는 독일의 철학자이자 프랑크푸르트 학파 비판이론의 거장 **위르겐 하버마스(Jürgen Habermas, 1929~)**는 대작 『의사소통행위이론』(*Theorie des kommunikativen Handelns*, 1981)을 통해 현대 사회의 위기와 민주적 합리성의 회복 가능성을 천명했습니다.

하버마스는 근대화가 낳은 비극(관료제화, 배금주의, 파시즘)이 이성 그 자체의 결함 때문이 아니라, 대상을 계산하고 조작하려는 **'도구적 이성(Instrumental Reason)'**만이 비대해지고 인간 상호 간의 대화와 합의를 이끄는 **'의사소통적 이성(Communicative Reason)'**이 억압되었기 때문이라고 진단했습니다.

### 1. 발화의 4대 보편적 타당성 요구 (Universal Validity Claims)
인간이 언어를 통해 타인과 상호이해(Verständigung)에 도달하고자 할 때, 모든 발화는 다음 4가지 타당성 요구를 암묵적으로 제기합니다:

1. **이해가능성 (Comprehensibility)**: 표현이 문법적·의미론적으로 명료하여 상대방이 알아들을 수 있는가?
2. **진리성 (Truth, Wahrheit)**: 발화된 명제가 객관적 외적 세계의 사실에 부합하는가?
3. **정당성 (Rightness, Richtigkeit)**: 발화가 상호주관적 사회 세계의 정당한 도덕·법률적 규범 체계에 부합하는가?
4. **진실성 (Sincerity, Wahrhaftigkeit)**: 화자가 자신의 주관적 내면 세계를 속이지 않고 진정성 있게 말하고 있는가?

### 2. 소통 행위 vs 전략적 행위
- **의사소통 행위 (Communicative Action)**: 참여자 모두가 상호이해와 합리적 동의를 목적으로 대화에 임하며, 4대 타당성 요구를 온전히 충족합니다.
- **전략적 행위 (Strategic Action)**: 겉으로는 대화하는 척하지만, 실제로는 타인을 자신의 이기적 목적을 위한 도구로 이용하거나 기만하는 행위입니다. 이는 진실성($S$)을 구조적으로 왜곡($S - 0.40$)시킵니다.

### 3. 체계에 의한 생활세계의 식민지화 (Colonization of the Lifeworld)
사회는 의사소통을 통해 의미와 연대를 생산하는 **생활세계(Lebenswelt: 가정, 학교, 공론장, 문화)**와, 화폐(Money)와 권력(Power)이라는 비언어적 **조종 매체(Steering Media)**를 통해 효율성을 추구하는 **체계(System: 시장 경제, 국가 행정기구)**로 구성됩니다.
체계의 매체(화폐와 권력)가 생활세계를 침범하여 토론을 돈과 위력으로 억누르는 현상을 **'생활세계의 식민지화(Kolonisierung der Lebenswelt)'**라고 부릅니다.

### 4. 이상적 담화 상황 (Ideale Sprechsituation)
어떠한 외적 강제나 기만 없이, 오직 **'더 나은 논증의 힘(Zwang des besseren Arguments)'**에 의해서만 모든 참여자가 자유롭고 평등하게 합의에 도달하는 규범적 상태입니다.

본 문제는 하버마스의 4대 타당성 요구 검증, 전략적 행위 왜곡 감지, 조종 매체에 의한 식민지화 지수 산출 및 이상적 담화 합의 도달 여부를 평가하는 인문 사회철학적 담론 분석 엔진을 구현하는 것입니다.

```
                      [ 화자의 발화 (Utterance) ]
                                  |
                                  v
    +-------------------------------------------------------------+
    |               4대 타당성 요구 (Universal Claims)             |
    |  - 이해가능성(C)  - 진리성(T)  - 정당성(R)  - 진실성(S)     |
    +-------------------------------------------------------------+
                                  |
               (행위 유형: STRATEGIC인 경우 진실성 왜곡 감점)
                                  |
                                  v
                 유효 타당성 점수 (Effective Validity, V)
                                  |
             +--------------------+--------------------+
             |                                         |
             v                                         v
   [ 조종 매체 침탈 검사 ]                     [ 합의 도달 여부 판정 ]
   (Money & Power -> Colonization κ)           - V >= Threshold & κ <= 0.30:
   - κ > 0.50: COLONIZED_BY_SYSTEM               RATIONAL_CONSENSUS_REACHED
   - κ > 0.25: MEDIA_INFILTRATED               - V < 0.50 또는 κ > 0.50:
   - 그 외: AUTONOMOUS_LIFEWORLD                 SYSTEMIC_DISTORTION
                                               - 그 외: CONTESTED_DELIBERATION
```

---

## 알고리즘 및 수학적 명세

### 1. 4대 타당성 요구 평가 및 유효 점수 ($V_{eff}$)
발화 $u$의 타당성 요구가 $C, T, R, S \in [0.0, 1.0]$일 때:
- **소통 행위 (`action_type == "COMMUNICATIVE"`)**:
  $$S_{eff} = S$$
- **전략적 행위 (`action_type == "STRATEGIC"`)**:
  $$S_{eff} = \max(0.0, 	ext{round}(S - 0.40, 4))$$
- 유효 타당성 점수:
  $$V_{eff} = 	ext{round}\left(rac{C + T + R + S_{eff}}{4}, 4ight)$$

### 2. 생활세계의 식민지화 지수 ($\kappa$)
화폐 압력 $M \in [0.0, 1.0]$과 권력 압력 $P \in [0.0, 1.0]$에 대해:
$$\kappa = 	ext{round}(w_{money} \cdot M + w_{power} \cdot P, 4)$$
(기본 가중치: $w_{money} = 0.40, w_{power} = 0.60$)
- 생활세계 자율성 지수: $	ext{Health} = \max(0.0, 	ext{round}(1.0 - \kappa, 4))$
- 식민지화 상태:
  - $\kappa > 0.50 \implies$ `"COLONIZED_BY_SYSTEM"` (체계에 의해 식민지화됨)
  - $\kappa > 0.25 \implies$ `"MEDIA_INFILTRATED"` (조종 매체 침투 진행)
  - 그 외 $\implies$ `"AUTONOMOUS_LIFEWORLD"` (자율적 생활세계)

### 3. 담화 판정 (Discourse Verdict)
- **이성적 합의 달성 (`RATIONAL_CONSENSUS_REACHED`)**:
  $$V_{eff} \ge 	ext{consensus\_threshold} \quad 	ext{AND} \quad \kappa \le 0.30$$
- **체계적 소통 왜곡 (`SYSTEMIC_DISTORTION`)**:
  $$V_{eff} < 0.50 \quad 	ext{OR} \quad \kappa > 0.50$$
- **경합적 숙의 진행 중 (`CONTESTED_DELIBERATION`)**:
  위 두 조건에 해당하지 않는 경우.

### 4. 종합 요약 통계 (Summary)
- `total_utterances`: 총 발화 수
- `rational_consensus_count`: 합의 도달 발화 수
- `systemic_distortion_count`: 체계적 왜곡 발화 수
- `mean_discourse_validity`: 평균 유효 타당성 점수 $ar{V}_{eff}$
- `mean_lifeworld_autonomy`: 평균 생활세계 자율성 지수 $\overline{	ext{Health}}$

---

## 입력 형식 (Input JSON Schema)

```json
{
  "config": {
    "consensus_threshold": 0.85,
    "colonization_weight_money": 0.40,
    "colonization_weight_power": 0.60
  },
  "discourse_participants": [
    {
      "participant_id": "CITIZEN-01",
      "name": "Civil Activist Clara",
      "role": "PUBLIC"
    }
  ],
  "utterances": [
    {
      "utterance_id": "UTT-001",
      "speaker_id": "CITIZEN-01",
      "action_type": "COMMUNICATIVE",
      "validity_claims": {
        "comprehensibility": 0.95,
        "truth": 0.90,
        "rightness": 0.92,
        "sincerity": 0.95
      },
      "steering_media_pressures": {
        "money": 0.05,
        "power": 0.05
      }
    }
  ]
}
```

---

## 출력 형식 (Output JSON Schema)

```json
{
  "summary": {
    "total_utterances": 1,
    "rational_consensus_count": 1,
    "systemic_distortion_count": 0,
    "mean_discourse_validity": 0.93,
    "mean_lifeworld_autonomy": 0.95
  },
  "utterance_evaluations": [
    {
      "utterance_id": "UTT-001",
      "speaker_id": "CITIZEN-01",
      "action_type": "COMMUNICATIVE",
      "effective_validity": 0.93,
      "colonization_index": 0.05,
      "lifeworld_status": "AUTONOMOUS_LIFEWORLD",
      "discourse_verdict": "RATIONAL_CONSENSUS_REACHED"
    }
  ]
}
```

---

## 제약 조건

- $1 \le 	ext{utterances} \le 100$
- 모든 부동 소수점 수치는 소수점 넷째 자리까지 반올림(`round(v, 4)`)하여 기록합니다.
- 표준 입력(`sys.stdin`)으로부터 UTF-8 JSON 문자열을 수신하고, 결과를 `json.dumps(..., ensure_ascii=False)`로 표준 출력에 인쇄합니다.
