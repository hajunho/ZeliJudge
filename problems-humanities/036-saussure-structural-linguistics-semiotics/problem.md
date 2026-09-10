# 문제 036: 소쉬르의 구조주의 언어학과 기호학적 의미 분석기 (Ferdinand de Saussure's Structural Linguistics & Semiotics Engine)

## 문제 설명

20세기 인문학의 지형을 뒤흔든 **구조주의(Structuralism)**의 창시자이자 현대 언어학의 아버지인 페르디낭 드 소쉬르(Ferdinand de Saussure, 1857~1913)는 유고작 『일반언어학 강의』(*Cours de linguistique générale*, 1916)에서 언어를 단순한 '단어와 사물의 이름표 목록'이 아니라, 기호들이 맺는 상호 관계와 차이(Difference)에 의해 가치가 규정되는 자율적 체계로 파악했습니다.

소쉬르 기호학(Semiotics / Sémiologie)의 핵심 개념은 다음과 같습니다:

1. **기호(Signe)의 이면성**:
   - **기표 (Signifiant, 시뇨피앙)**: 감각적으로 지각되는 음성 이미지(Sound-Image) 또는 문자 형태.
   - **기의 (Signifié, 시뇨피에)**: 기표를 통해 마음에 떠오르는 심리적·개념적 의미(Concept).
2. **기호의 자의성 (L'arbitraire du signe)**:
   - 기표와 기의 사이에는 아무런 내적·필연적 인과관계가 없습니다. 동일한 '우거진 다년생 식물'이라는 기의에 대해 한국어는 [나무], 영어는 [tree], 프랑스어는 [arbre]라는 완전히 다른 기표를 자의적으로 부여합니다.
   - 따라서 언어의 의미는 "긍정적인 실체로서 존재하는 것이 아니라, 오직 다른 단어들과의 차이(Difference)에 의해서만 규정"됩니다.
3. **언어의 두 가지 축 (The Two Axes of Language)**:
   - **통합체적 축 (Syntagmatic Axis / 결합축)**:
     - 단어들이 시간적·선형적으로 결합하여 문장을 이루는 수평적 연쇄 관계(In Praesentia).
     - 특정 품사(POS) 순서 패턴(예: `[NOUN, VERB, NOUN]`)을 준수해야 문법적으로 유효한 통합체가 됩니다.
   - **계열체적 축 (Paradigmatic Axis / 선택축 / 연상축)**:
     - 문장의 특정 자리에 문법적으로 대치 가능한 단어들의 수직적 연상 집합(In Absentia).
     - 동일한 품사군 내에서 문맥상 대체 가능한 유의어(Synonym) 후보군과 대조적인 반의어(Antonym) 후보군을 형성합니다.
4. **찰스 오스굿의 의미 미분법 (Charles Osgood's Semantic Differential)**:
   - 인지언어학자 찰스 오스굿(Charles E. Osgood, 1952)은 기의의 감정적·심리적 의미를 정량화하기 위해 **EPA 3차원 공간**을 제안했습니다:
     1. **Evaluation (평가성: 긍정-부정 / Good-Bad)**: $[-3.0, +3.0]$
     2. **Potency (역량성: 강함-약함 / Strong-Weak)**: $[-3.0, +3.0]$
     3. **Activity (활동성: 능동-수동 / Active-Passive)**: $[-3.0, +3.0]$
   - 두 단어 사이의 의미적 거리(Semantic Distance)는 3차원 유클리드 거리로 계산됩니다:
     $$D(w_1, w_2) = \sqrt{(E_1 - E_2)^2 + (P_1 - P_2)^2 + (A_1 - A_2)^2}$$

당신은 소쉬르의 기호학 이론과 오스굿의 의미 미분법을 결합하여, 기호의 자의성 검증, 통합체 문법 연쇄 분석, 계열체 대체어 추천 및 정서 벡터 합성을 수행하는 언어 분석 엔진을 구현해야 합니다.

---

## 입력 형식 (JSON)

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다.

```json
{
  "lexicon": [
    {
      "signifier": "peace",
      "signified": "freedom from disturbance",
      "pos": "NOUN",
      "epa": [2.8, 1.5, -1.0],
      "language": "en"
    },
    {
      "signifier": "war",
      "signified": "state of armed conflict",
      "pos": "NOUN",
      "epa": [-2.5, 2.7, 2.6],
      "language": "en"
    }
  ],
  "syntagm_rules": [
    {
      "name": "SVO_SENTENCE",
      "pattern": ["NOUN", "VERB", "NOUN"]
    }
  ],
  "operations": [
    {
      "step": 1,
      "op": "CHECK_ARBITRARINESS",
      "signified": "woody perennial plant"
    },
    {
      "step": 2,
      "op": "SEMANTIC_DISTANCE",
      "word1": "peace",
      "word2": "war"
    },
    {
      "step": 3,
      "op": "ANALYZE_SYNTAGM",
      "words": ["poet", "writes", "verse"]
    },
    {
      "step": 4,
      "op": "QUERY_PARADIGM",
      "target_word": "king",
      "top_k": 2
    }
  ]
}
```

### 연산 종류
1. `CHECK_ARBITRARINESS`: 특정 기의(`signified`)를 가리키는 서로 다른 언어/형태의 기표(`signifier`)들을 수집하여 기호의 자의성을 검증합니다. 기표가 2개 이상이면 `is_arbitrary: true`.
2. `SEMANTIC_DISTANCE`: 두 단어 $w_1, w_2$ 간의 EPA 3차원 유클리드 거리를 소수점 둘째 자리까지 반올림(`round(d, 2)`)하여 계산합니다.
3. `ANALYZE_SYNTAGM`: 주어진 단어들의 선형 연쇄를 분석하여 사전에 등록된 품사 규칙(`syntagm_rules`)과의 일치 여부(`valid`), 품사 시퀀스, 그리고 문장 전체의 합성 정서 벡터(`composite_epa`, 단어별 EPA의 평균)를 반환합니다.
4. `QUERY_PARADIGM`: 대상 단어(`target_word`)와 동일한 품사를 가진 계열체 후보들 중, EPA 거리가 가장 가까운 `top_k`개의 유의어 대체 후보(`closest_substitutes`)와 거리가 가장 먼 `top_k`개의 반의어 후보(`furthest_opposites`)를 추출합니다.

---

## 출력 형식 (JSON)

표준 출력(stdout)으로 다음 스키마를 만족하는 단일 줄 JSON 객체를 출력합니다.

```json
{
  "operations_log": [
    {
      "step": 1,
      "op": "CHECK_ARBITRARINESS",
      "signified": "woody perennial plant",
      "distinct_signifiers_count": 3,
      "signifiers": [
        {"signifier": "tree", "language": "en", "epa": [1.5, 1.2, -0.1]},
        {"signifier": "나무", "language": "ko", "epa": [1.5, 1.2, -0.1]}
      ],
      "is_arbitrary": true
    },
    {
      "step": 2,
      "op": "SEMANTIC_DISTANCE",
      "word1": "peace",
      "word2": "war",
      "distance": 6.52
    }
  ],
  "lexicon_size": 2
}
```

---

## 제약 조건

- 어휘 사전 단어 수: $2 \le |\text{lexicon}| \le 50$
- 품사 종류: `NOUN`, `VERB`, `ADJ`, `ADV` 등
- EPA 벡터 각 성분: $-3.0 \le E, P, A \le +3.0$
- 연산 수: $1 \le M \le 20$
