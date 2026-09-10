# Problem #046: 인지언어학(Cognitive Linguistics) 개념적 은유 이론(Conceptual Metaphor Theory)과 조지 레이코프(George Lakoff)의 정치 담론 프레이밍(Framing) 분석기

## 1. 개요 및 인문학적 배경 (Overview & Humanistic Background)

인간은 세계를 어떻게 이해하고 언어로 표현할까요? 고대 아리스토텔레스 이래 2천 년 동안 서양 철학에서 은유(Metaphor)는 시인들의 단순한 수사학적 기교나 장식품에 불과한 것으로 여겨졌습니다.
그러나 1980년, 인지언어학(Cognitive Linguistics)의 창시자 **조지 레이코프(George Lakoff, 1941~)**와 철학자 **마크 존슨(Mark Johnson)**은 기념비적인 저서 『삶으로서의 은유(*Metaphors We Live By*, 1980)』를 통해 인간의 일상적 인지 체계 자체가 근본적으로 은유적이라는 혁명적인 선언을 던졌습니다.

우리는 구체적인 신체적 경험을 가진 **근원 영역(Source Domain: 전쟁, 상거래/화폐, 여정, 건축물 등)**을 매개로 삼아, 눈에 보이지 않는 추상적인 **목표 영역(Target Domain: 논쟁, 시간, 사랑, 도덕, 국가 등)**을 개념화합니다:

```
+-----------------------------------------------------------------------------------------------+
|                      Conceptual Metaphor Mapping (Cross-Domain Projection)                    |
+-----------------------------------------------------------------------------------------------+
  [ 근원 영역: 전쟁 (WAR) ]            ======== 체계적 인지 사상 =======>   [ 목표 영역: 논쟁 (ARGUMENT) ]
   - 공격하다 (attack)                   ----------------------------->    - 상대 주장의 허점을 비판하다
   - 방어하다 (defend)                   ----------------------------->    - 자신의 논지를 방어하다
   - 요새/진지 (position)                ----------------------------->    - 학술적/정치적 입장
   - 승리/패배 (win / surrender)         ----------------------------->    - 토론에서 이기다 / 항복하다

  [ 근원 영역: 상업/화폐 (MONEY) ]     ======== 체계적 인지 사상 =======>   [ 목표 영역: 시간 (TIME) ]
   - 쓰다/소비하다 (spend)              ----------------------------->    - 시간을 보내다
   - 낭비하다 (waste)                   ----------------------------->    - 시간을 허비하다
   - 투자하다 (invest)                  ----------------------------->    - 시간을 쏟다
   - 빌리다/빚지다 (borrow / debt)       ----------------------------->    - 시간을 벌다
```

### 국가는 가정이다 (THE NATION AS A FAMILY)와 정치 담론 프레이밍
레이코프는 『도덕의 정치(*Moral Politics*, 1996)』와 『코끼리는 생각하지 마(*Don't Think of an Elephant!*, 2004)』에서, 현대 정치 대립의 심층에는 국가를 가정으로 비유하는 두 가지 상반된 인지 모델이 자리 잡고 있음을 규명했습니다:

1. **엄격한 아버지 모델 (Strict Father Model - 보수주의 프레임)**:
   - 세상은 험난하고 위험하며, 인간은 엄격한 규율과 훈육을 통해서만 올바른 도덕적 자립을 이룰 수 있습니다.
   - 핵심 어휘: 훈육(`discipline`), 처벌(`punish`), 자립(`self-reliance`), 질서(`order`), 권위(`authority`), 힘(`strength`).
2. **자애로운 부모 모델 (Nurturant Parent Model - 진보주의 프레임)**:
   - 세상은 상호 연결된 공동체이며, 부모의 역할은 자녀에게 공감하고 보살핌을 제공하여 타인을 배려하도록 양육하는 것입니다.
   - 핵심 어휘: 보살핌(`care`), 공감(`empathy`), 보호(`protection`), 상호 지원(`support`), 협력(`cooperation`), 공정함(`fairness`).

이 문제에서는 주어진 텍스트 코퍼스를 토큰화하여 근원 영역-목표 영역 간의 개념적 은유 활성화 강도를 정량화하고, 엄격한 아버지 대 자애로운 부모 인지 모델의 단서 어휘를 추출하여 정치 담론의 지배적 프레임(`detected_frame`)과 프레임 편향 지수(`frame_bias_index`)를 계산하는 인지언어학 분석 엔진을 구현합니다.

---

## 2. 입출력 규격 (Input & Output Specification)

### 입력 형식 (Standard Input)
표준 입력(stdin)으로 JSON 객체가 주어집니다.
```json
{
  "config": {
    "frame_classification_threshold": 0.15
  },
  "source_domain_lexicon": {
    "WAR": ["attack", "defend", "shoot", "battle", "win", "enemy", "target", "weapon"],
    "COMMERCE_RESOURCE": ["spend", "waste", "invest", "save", "borrow", "cost", "budget"],
    "STRICT_FATHER": ["discipline", "punish", "reward", "self-reliance", "order", "authority", "strength"],
    "NURTURANT_PARENT": ["care", "nurture", "empathy", "protection", "support", "cooperation", "community"]
  },
  "metaphor_schemata": [
    {
      "id": "ARGUMENT_IS_WAR",
      "source": "WAR",
      "target": "ARGUMENT",
      "context_keywords": ["debate", "argument", "point", "discussion", "claim"]
    }
  ],
  "documents": [
    {
      "doc_id": "debate_speech_01",
      "text": "Your claims in this debate are indefensible. We will attack your weak points and shoot down every false argument until we win the battle."
    }
  ]
}
```

- `config`:
  - `frame_classification_threshold` (float, 기본값 0.15): 보수/진보 프레임 구분을 위한 편향 지수 임계치.
- `source_domain_lexicon`: 근원 영역 및 도덕 인지 모델별 단서 어휘 목록.
- `metaphor_schemata`: 개념적 은유 스키마 정의 (`id`, `source`, `target`, `context_keywords`).
- `documents`: 분석 대상 텍스트 문서 배열 (`doc_id`, `text`).

### 처리 규칙 (Processing Rules)

1. **텍스트 토큰화 (Tokenization)**:
   - 텍스트를 소문자로 변환한 후 정규식 `[a-zA-Z\-]+`를 사용하여 단어 단위 토큰으로 분리합니다.
2. **개념적 은유 활성화 판정 (Metaphor Activation)**:
   - 각 문서에 대해 `metaphor_schemata`의 `context_keywords`(목표 영역 단서)가 1개 이상 존재하고, 대응하는 `source` 도메인 어휘(근원 영역 단서)가 1개 이상 출현하면 해당 개념적 은유가 활성화된 것으로 판정합니다.
   - `metaphor_strength = round((source_matches_count + target_matches_count) / token_count * 100.0, 2)`
3. **정치 프레이밍 지수 산출 (Framing Analysis)**:
   - `c_strict`: 문서 내 `STRICT_FATHER` 어휘 출현 총 횟수.
   - `c_nurturant`: 문서 내 `NURTURANT_PARENT` 어휘 출현 총 횟수.
   - `total_frame = c_strict + c_nurturant`.
   - `total_frame == 0`인 경우: `frame_bias_index = 0.0`, `detected_frame = "NEUTRAL_UNFRAMED"`.
   - `total_frame > 0`인 경우:
     - `frame_bias_index = round((c_strict - c_nurturant) / total_frame, 2)`
     - `frame_bias_index > frame_classification_threshold`: `"STRICT_FATHER_FRAME"`
     - `frame_bias_index < -frame_classification_threshold`: `"NURTURANT_PARENT_FRAME"`
     - 그 외: `"BICONCEPTUAL_CONTESTED_FRAME"`
4. 각 단서 어휘 목록은 고유 단어들을 알파벳 오름차순으로 정렬하여 출력합니다.

### 출력 형식 (Standard Output)
단일 행의 표준 JSON 형식으로 출력합니다.
```json
{
  "analyzed_documents_count": 1,
  "document_results": [
    {
      "doc_id": "debate_speech_01",
      "word_count": 21,
      "activated_metaphors": [
        {
          "metaphor_id": "ARGUMENT_IS_WAR",
          "target_cues": ["argument", "claims", "debate", "points"],
          "source_cues": ["attack", "battle", "shoot", "win"],
          "metaphor_strength": 38.1
        }
      ],
      "framing_analysis": {
        "detected_frame": "NEUTRAL_UNFRAMED",
        "frame_bias_index": 0.0,
        "strict_father_cues": [],
        "nurturant_parent_cues": []
      }
    }
  ]
}
```

---

## 3. 제약 사항 (Constraints)
- 문서당 단어 수: $1 \le W \le 5,000$
- 문서 수: $1 \le D \le 100$
- Python 3 표준 라이브러리만 사용합니다 (`json`, `sys`, `re`).
