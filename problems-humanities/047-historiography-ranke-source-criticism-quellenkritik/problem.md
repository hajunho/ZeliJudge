# Problem #047: 역사학(Historiography) 레오폴트 폰 랑케(Leopold von Ranke)의 실증주의 사료비판(Quellenkritik) 판정기

## 1. 개요 및 인문학적 배경 (Overview & Humanistic Background)

근대 역사학의 아버지로 불리는 독일의 역사학자 **레오폴트 폰 랑케(Leopold von Ranke, 1795~1886)**는 "역사가는 과거를 심판하거나 미래를 훈계하는 것이 아니라, **오직 그것이 실제로 어떠했는가(Wie es eigentlich gewesen)**를 보여줄 뿐이다"라는 실증주의 역사학의 대명제를 선언했습니다.

랑케 이전의 역사 서술은 신화, 교훈극, 설화, 궁정 연대기의 과장과 미화로 얼룩져 있었습니다. 랑케는 이를 엄밀한 과학적 학문으로 변혁하기 위해 **사료비판(Quellenkritik / Source Criticism)**의 2단계 방법론을 정립했습니다:

```
+-----------------------------------------------------------------------------------------------+
|                       Rankean Historiographical Source Criticism Pipeline                     |
+-----------------------------------------------------------------------------------------------+
  [ 원본 사료 문서 수집 ]
            |
            v
  [ 1단계: 외적 비판 (External Criticism / Lower Criticism) ]
    - 재질, 연륜연대, 고문서 서식 검사
    - 시대착오적 어휘(Anachronism) 검출
    - 위작(Forgery) 판명 시 즉시 사료 풀에서 배제 (예: 콘스탄티누스 기증서)
            |
            v (진품 확인)
  [ 2단계: 내적 비판 (Internal Criticism / Higher Criticism) ]
    - 저자의 신뢰도: 당대 목격자(Eyewitness) 여부
    - 시간적 근접성: 사건 발생 시점과 기록 시점의 시차 감쇠(Temporal Decay Half-Life)
    - 저자의 이해관계 및 편향(Conflict of Interest Bias)
            |
            v
  [ 3단계: 상호 확증 및 전재 사료 중복 배제 (Corroboration & Independence) ]
    - '단일 증언은 증언이 아니다 (Testis unus, testis nullus)' 원칙
    - 선행 사료를 그대로 베껴 쓴 후대 사료(Copying dependency) 필터링
    - 독립된 다수 사료의 상호 교차 검증 -> 역사적 사실성 지수(Factuality Index) 산출
```

이 문제에서는 다양한 역사적 사료의 물리적 진위, 저자 신뢰도, 시간적 감쇠, 사료 간 전재 계통을 분석하여, 각 역사적 주장의 역사적 사실성 지수(`factuality_index`)와 최종 판정(`verdict`)을 산출하는 사료비판 엔진을 구현합니다.

---

## 2. 입출력 규격 (Input & Output Specification)

### 입력 형식 (Standard Input)
표준 입력(stdin)으로 JSON 객체가 주어집니다.
```json
{
  "config": {
    "temporal_decay_half_life_years": 50.0
  },
  "claims": [
    {
      "claim_id": "armistice_signed_1918",
      "description": "Compiegne Armistice signed on 11 Nov 1918"
    }
  ],
  "sources": [
    {
      "source_id": "foch_memoir_notes",
      "created_year": 1918,
      "event_year": 1918,
      "physical_authenticity": {
        "material_age_consistent": true,
        "anachronisms_detected": 0
      },
      "author_reliability": {
        "direct_eyewitness": true,
        "competence_score": 0.95,
        "conflict_of_interest_bias": 0.05
      },
      "corroboration_links": [],
      "attested_claims": [
        {"claim_id": "armistice_signed_1918", "stance": "SUPPORT"}
      ]
    }
  ]
}
```

- `config`:
  - `temporal_decay_half_life_years` (float, 기본값 50.0): 시간적 지연에 따른 신뢰도 반감기(년 단위).
- `claims`: 판정 대상 역사적 주장 목록 (`claim_id`, `description`).
- `sources`: 분석 대상 사료 목록.
  - `source_id`, `created_year`, `event_year`.
  - `physical_authenticity`: `material_age_consistent` (bool), `anachronisms_detected` (int).
  - `author_reliability`: `direct_eyewitness` (bool), `competence_score` (float: 0.0~1.0), `conflict_of_interest_bias` (float: 0.0~1.0).
  - `corroboration_links`: 해당 사료가 베껴 쓴 선행 사료 ID 목록 (`copied_from`).
  - `attested_claims`: 진술한 주장 및 지지/반박 입장 (`claim_id`, `stance`: `"SUPPORT"` 또는 `"REFUTE"`).

### 처리 규칙 (Processing Rules)

1. **외적 비판 (진위 판별)**:
   - `auth_score = max(0.0, 1.0 - 0.4 * anachronisms - (0.5 if not consistent else 0.0))`
   - `auth_score < 0.3`인 경우 `is_forgery = true`로 판정하며, 위작 사료는 주장 판정에서 완전히 배제됩니다.
2. **시간적 근접성 감쇠**:
   - $\Delta t = |	ext{created\_year} - 	ext{event\_year}|$
   - $	ext{temporal\_score} = 2.0^{-rac{\Delta t}{	ext{half\_life}}}$
3. **내적 비판 (가중치 계산)**:
   - $	ext{eye\_score} = 1.0$ (목격자) 또는 $0.6$ (전언/간접).
   - $	ext{credibility\_weight} = 	ext{round}(	ext{auth\_score} 	imes 	ext{temporal\_score} 	imes 	ext{eye\_score} 	imes 	ext{competence} 	imes (1.0 - 	ext{bias}), 3)$
4. **전재(Copying) 사료 배제 및 독립 증언 선별**:
   - 동일 주장을 지지하는 사료 집합 중, 다른 지지 사료의 내용을 그대로 베껴 쓴 사료(`corroboration_links`에 포함된 사료)는 독립 증인(`independent_support_witnesses`)에서 제외합니다. (반박 사료도 동일 적용)
5. **사실성 지수 (`factuality_index`) 및 판정**:
   - $W_{	ext{sup}} = \sum_{s \in 	ext{Indep\_Support}} 	ext{credibility\_weight}(s)$
   - $W_{	ext{ref}} = \sum_{s \in 	ext{Indep\_Refute}} 	ext{credibility\_weight}(s)$
   - 단일 증언 페널티(*Testis unus*): 독립 지지 증인이 1개 이하인 경우 $	ext{witness\_factor} = 0.65$, 2개 이상이면 $1.0$.
   - $	ext{raw\_prob} = rac{W_{	ext{sup}}}{W_{	ext{sup}} + W_{	ext{ref}} + 0.05} 	imes 	ext{witness\_factor}$
   - $	ext{factuality\_index} = 	ext{round}(\min(1.0, \max(0.0, 	ext{raw\_prob})), 2)$
   - 판정 (`verdict`):
     - $\ge 0.70$: `"HISTORICALLY_ESTABLISHED"`
     - $\ge 0.45$: `"PROBABLE_PLAUSIBLE"`
     - $\ge 0.20$: `"CONTESTED_AMBIGUOUS"`
     - 미만: `"REJECTED_UNSUBSTANTIATED"`

### 출력 형식 (Standard Output)
단일 행의 표준 JSON 형식으로 출력합니다.
```json
{
  "sources_analyzed": 2,
  "source_evaluations": {
    "foch_memoir_notes": {
      "source_id": "foch_memoir_notes",
      "is_forgery": false,
      "authenticity_score": 1.0,
      "temporal_proximity_score": 1.0,
      "credibility_weight": 0.902,
      "copied_from": []
    }
  },
  "claims_adjudication": [
    {
      "claim_id": "armistice_signed_1918",
      "description": "Compiegne Armistice signed on 11 Nov 1918",
      "factuality_index": 0.97,
      "verdict": "HISTORICALLY_ESTABLISHED",
      "independent_support_witnesses": ["erzberger_delegation_report", "foch_memoir_notes"],
      "independent_refute_witnesses": [],
      "support_weight_sum": 1.757,
      "refute_weight_sum": 0.0
    }
  ]
}
```

---

## 3. 제약 사항 (Constraints)
- 사료 수: $1 \le S \le 50$
- 주장 수: $1 \le C \le 20$
- 연도: $-3000 \le \text{year} \le 2100$
- Python 3 표준 라이브러리만 사용합니다 (`json`, `sys`, `math`).
