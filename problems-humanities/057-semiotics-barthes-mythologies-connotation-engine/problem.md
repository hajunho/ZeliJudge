# 문제 057: 롤랑 바르트의 신화론(Mythologies): 1차 외연(Denotation)에서 2차 내포(Connotation) 및 이데올로기 탈신화화 엔진 (Roland Barthes' Mythologies & Ideological Demythologization Engine)

## 문제 배경
20세기 프랑스의 기호학자이자 문화비평가인 **롤랑 바르트(Roland Barthes, 1915~1980)**는 1957년 출간된 불후의 저작 『신화론(Mythologies)』에서 대중문화(광고, 뉴스 사진, 잡지 표지, 프로레슬링 등)가 어떻게 지배 계급의 역사적 이데올로기를 마치 '자연스럽고 당연한 상식'인 것처럼 둔갑시키는지를 폭로했습니다.

바르트는 소쉬르의 기호학(기표 Signifier + 기의 Signified = 기호 Sign)을 2단계 계층 구조로 확장했습니다:
1. **1차 언어 체계 (외연적 의미, Denotation)**:
   - 문자 그대로의 물리적·사실적 대상.
   - 예: 프랑스 군복을 입은 흑인 소년이 프랑스 국기를 향해 경례를 하고 있는 사진 (기표 1 + 기의 1 = 기호 1).
2. **2차 신화 체계 (내포적 의미, Connotation / Myth)**:
   - 1차 기호 전체가 2차 체계의 **형식(Form / 기표 2)**으로 흡수됩니다!
   - 여기에 2차 이데올로기적 **개념(Concept / 기의 2)**이 덧씌워집니다 (예: "프랑스 제국의 인종 융합과 식민지 지배의 영광").
   - 이로써 2차 기호인 **신화(Myth)**가 탄생합니다!

```
 ┌──────────────────────────────────────────────┐
 │ 1차 기호 체계 (외연 Denotation)              │
 │  [ 1. 기표 Signifier ]  +  [ 2. 기의 Signified ]
 │           └──────────────┬──────────────┘    │
 │                          │                   │
 │                [ 3. 기호 Sign (외연) ]       │
 └──────────────────────────┼───────────────────┘
                            ▼
 ┌──────────────────────────────────────────────┐
 │ 2차 신화 체계 (내포 Connotation / Myth)      │
 │          [ I. 형식 Form (기표 2) ]           │  +  [ II. 개념 Concept (기의 2) ]
 │                     └────────────────────────┬──────────────────────┘
 │                                              │
 │                                    [ III. 신화 Signification ]
 └──────────────────────────────────────────────┴────────────────────────────┘
```

바르트에 따르면 신화의 본질은 **'탈정치화된 발화(Depoliticized Speech)'**입니다. 즉, 피와 착취가 얽힌 역사적·정치적 우연성을 마치 영원불변한 자연적 사실인 양 **자연화(Naturalization)**하는 것입니다.

신화를 대하는 독자의 태도는 세 가지로 나뉩니다:
1. **순진한 소비자 (Naive Consumer)**: 형식을 곧장 사실로 받아들여 신화의 이데올로기를 순수하고 자연스러운 현실로 수용함 (`NATURALIZED_ACCEPTANCE`).
2. **냉소적 생산자 (Cynical Producer)**: 1차 기호를 의도적인 알리바이(핑계)로 조작하여 이데올로기를 전파하는 광고주/선전가 (`INSTRUMENTAL_PROPAGANDA`).
3. **신화 해체자 (Mythologist)**: 1차 외연적 사실과 2차 이데올로기적 왜곡을 분리하여 신화의 동기를 비판적으로 폭로함 (`CRITICAL_DEMYTHOLOGIZATION`).

본 문제에서는 텍스트 및 미디어 아티팩트에 내재된 1차 외연과 2차 신화를 파싱하고, 독자의 비판적 스탠스에 따라 신화를 해체하거나 수용 상태를 평가하는 **롤랑 바르트 신화 분석 엔진**을 구현해야 합니다.

---

## 시스템 동작 규칙 및 엔진 명세

### 1. 1차 외연 계층 분석 (Denotation Layer)
- 미디어 아티팩트(`media_artifacts`)에 탐지된 각 기호 식별자(`sign_id`)에 대해:
  - 사전(`lexicon_denotations`)에서 해당 기호의 기표(`signifier_1`), 기의(`signified_1`), 문자적 영역(`literal_domain`)을 추출하여 외연 계층(`denotative_layers`)에 기록합니다.

### 2. 2차 내포 및 신화 분석 (Connotation & Myth Layer)
- 각 외연 기호가 2차 신화 사전(`myth_connotations`)의 `base_sign_id`와 매칭되는 경우:
  - 2차 형식: `form_2 = "{signifier_1} + {signified_1}"`
  - 2차 개념: `concept_2 = connoted_concept`
  - 자연화 강도 판정: `naturalization_strength >= ideology_weight_threshold`이면 `"NATURALIZED_MYTH"`, 미만이면 `"WEAK_CONNOTATION"`.

### 3. 독자 태도(Reader Stance)에 따른 해석 결과 판정
아티팩트의 `reader_stance`에 따라:
1. **`NAIVE_CONSUMER` (순진한 소비자)**:
   - 신화의 이데올로기를 인지하지 못하고 있는 그대로 받아들입니다.
   - `reading_result`: `"NATURALIZED_ACCEPTANCE"`
   - `exposed_ideology`: `null`
2. **`CYNICAL_PRODUCER` (냉소적 생산자/광고주)**:
   - 1차 기호를 수단화하여 메시지를 설득 도구로 활용합니다.
   - `reading_result`: `"INSTRUMENTAL_PROPAGANDA"`
   - `exposed_ideology`: `ideological_motive`
3. **`MYTHOLOGIST` (신화 해체자)**:
   - 신화 뒤에 숨은 역사적 이데올로기를 비판적으로 폭로합니다.
   - `reading_result`: `"CRITICAL_DEMYTHOLOGIZATION"`
   - `exposed_ideology`: `ideological_motive`

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "config": {
    "ideology_weight_threshold": 0.70
  },
  "lexicon_denotations": [
    {
      "sign_id": "deno_black_soldier_salute",
      "signifier": "프랑스 군복을 입은 흑인 병사의 삼색기 경례",
      "signified": "국가 군대에 대한 청년의 충성 예식",
      "literal_domain": "military_ceremony"
    }
  ],
  "myth_connotations": [
    {
      "myth_id": "myth_french_imperiality",
      "base_sign_id": "deno_black_soldier_salute",
      "connoted_concept": "프랑스 제국주의의 다민족 융합과 식민지 지배의 당위성",
      "ideological_motive": "식민지 착취의 역사적 불평등을 자연스러운 애국심으로 치환",
      "naturalization_strength": 0.95,
      "target_audience_class": "프랑스 본국 대중"
    }
  ],
  "media_artifacts": [
    {
      "artifact_id": "art_paris_match_1955",
      "title": "파리 마치(Paris Match) 표지 사진 (1955년)",
      "detected_denotations": ["deno_black_soldier_salute"],
      "reader_stance": "MYTHOLOGIST"
    }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 JSON 객체를 단일 행으로 출력합니다:

```json
{
  "summary": {
    "total_artifacts": 1,
    "total_myths_detected": 1,
    "demythologized_count": 1,
    "naturalized_acceptance_count": 0
  },
  "artifact_analyses": [
    {
      "artifact_id": "art_paris_match_1955",
      "title": "파리 마치(Paris Match) 표지 사진 (1955년)",
      "reader_stance": "MYTHOLOGIST",
      "denotative_layers": [
        {
          "sign_id": "deno_black_soldier_salute",
          "signifier_1": "프랑스 군복을 입은 흑인 병사의 삼색기 경례",
          "signified_1": "국가 군대에 대한 청년의 충성 예식",
          "literal_domain": "military_ceremony"
        }
      ],
      "connotative_myths": [
        {
          "myth_id": "myth_french_imperiality",
          "form_2": "프랑스 군복을 입은 흑인 병사의 삼색기 경례 + 국가 군대에 대한 청년의 충성 예식",
          "concept_2": "프랑스 제국주의의 다민족 융합과 식민지 지배의 당위성",
          "myth_type": "NATURALIZED_MYTH",
          "naturalization_strength": 0.95,
          "reading_result": "CRITICAL_DEMYTHOLOGIZATION",
          "exposed_ideology": "식민지 착취의 역사적 불평등을 자연스러운 애국심으로 치환"
        }
      ]
    }
  ]
}
```

---

## 제약 사항
- `1 <= len(lexicon_denotations) <= 200`
- `0 <= len(myth_connotations) <= 200`
- `1 <= len(media_artifacts) <= 50`
- `0.0 <= ideology_weight_threshold <= 1.0`
