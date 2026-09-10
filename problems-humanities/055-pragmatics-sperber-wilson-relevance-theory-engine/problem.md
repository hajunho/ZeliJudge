# 문제 055: 스페르베르-윌슨 인지 화용론 관련성 이론 최적 해석 추론기 (Sperber & Wilson Relevance Theory Cognitive Engine)

## 문제 설명

1986년 인지과학자 **단 스페르베르(Dan Sperber)**와 언어학자 **디어드리 윌슨(Deirdre Wilson)**은 저서 『관련성: 의사소통과 인지(Relevance: Communication and Cognition)』에서 전통적인 그라이스식 대화 격률 목록을 단 하나의 근본적인 인간 인지 원리인 **관련성 원칙(Principle of Relevance)**으로 통섭했습니다.

스페르베르와 윌슨에 따르면 인간의 인지 시스템은 최소한의 정신적 처리 노력으로 최대한의 인지적 효과를 얻도록 진화했습니다:
> **관련성(Relevance) 공식**:
> $$\text{Relevance} = \frac{\text{Positive Cognitive Effects (인지적 효과)}}{\text{Mental Processing Effort (처리 노력)}}$$

### 1. 긍정적 인지적 효과 (Positive Cognitive Effects)
새로운 발화(입력)가 수용자의 기존 인지 환경(기존 신념/가정)과 상호작용하여 다음과 같은 변화를 일으킬 때 인지적 효과가 발생합니다:
1. **맥락적 함의(Contextual Implication)**: 새로운 정보와 기존 가정이 결합하여 둘 중 어느 하나만으로는 도출할 수 없었던 새로운 결론을 합성함.
2. **기존 가정의 강화(Strengthening)**: 이미 가지고 있던 가설이나 신념의 확신도/신뢰도를 상승시킴.
3. **기존 가정의 반박 및 소거(Contradiction & Elimination)**: 새로운 고신뢰 증거를 통해 기존의 오해나 거짓 가정을 격파하고 폐기함.

### 2. 정신적 처리 노력 (Mental Processing Effort)
발화를 표상하고, 맥락 지식을 인출하며, 함의를 추론하는 데 소모되는 인지적 자원(문법적 복잡성, 난해한 어휘, 장황함, 불필요하게 깊은 추론 단계).

### 3. 의사소통적 관련성 원칙 (Communicative Principle of Relevance)
모든 명시적 직시(Ostensive Stimulus) 행위는 그 자체가 **최적의 관련성(Optimal Relevance)**을 갖추고 있다는 가정을 수반합니다. 청자는 최소한의 노력으로 충분한 인지적 효과를 산출하는 해석 가설을 즉각 최적해로 채택합니다.

본 문제에서는 청자의 기존 신념 체계(사전 확률/신뢰도)와 연역적 추론 규칙 집합, 그리고 화자의 후보 발화(해석 가설) 목록을 입력받아, 각 후보의 인지적 효과와 처리 노력을 계량화하고 **최적 관련성을 산출하는 최종 해석 가설**을 결정하는 **관련성 이론 인지 엔진**을 구현해야 합니다.

---

## 입력 형식

표준 입력(stdin)으로 다음과 같은 단일 JSON 객체가 주어집니다:

```json
{
  "prior_beliefs": {
    "raining": 0.2,
    "picnic_planned": 1.0
  },
  "inference_rules": [
    {
      "premises": ["raining", "picnic_planned"],
      "conclusion": "cancel_picnic",
      "strength": 0.9
    }
  ],
  "candidates": [
    {
      "id": "cand_concise",
      "explicature": {"raining": 0.9},
      "processing_effort": 1.5
    },
    {
      "id": "cand_verbose",
      "explicature": {"raining": 0.9},
      "processing_effort": 4.5
    }
  ]
}
```

- `prior_beliefs`: 청자의 인지 환경에 존재하는 기존 신념 및 신뢰도 (`{"신념명": float}`).
- `inference_rules`: 맥락 추론 규칙 리스트:
  - `premises`: 전제 신념 목록 (모든 전제가 신뢰도 $\ge 0.5$이어야 발화).
  - `conclusion`: 전제 결합 시 도출되는 결론 신념 명칭.
  - `strength`: 추론 결합 강도 계수 ($0 < \text{strength} \le 1.0$).
  - *단, 맥락적 함의로 인정받으려면 전제 중 최소 1개 이상이 후보 발화의 신규 명시(explicature)에서 기원해야 함.*
- `candidates`: 평가할 후보 해석 가설 리스트:
  - `id`: 후보 식별자.
  - `explicature`: 해당 발화가 직설적으로 갱신/주장하는 사실 및 신뢰도 (`{"신념명": float}`).
  - `processing_effort`: 해당 발화를 해석하는 데 소모되는 인지적 처리 노력 ($> 0$).

---

## 출력 형식

표준 출력(stdout)으로 다음 구조를 갖는 단일 JSON 객체를 한 줄로 출력합니다:

```json
{
  "optimal_candidate_id": "cand_concise",
  "highest_relevance_ratio": 3.15,
  "candidate_evaluations": [
    {
      "candidate_id": "cand_concise",
      "cognitive_effects_score": 4.725,
      "processing_effort": 1.5,
      "relevance_ratio": 3.15,
      "contextual_implications": [
        {
          "conclusion": "cancel_picnic",
          "confidence": 0.81,
          "premises": ["raining", "picnic_planned"]
        }
      ],
      "strengthenings": [],
      "eliminations": [
        {
          "fact": "raining",
          "eliminated_prior": 0.2,
          "new": 0.9,
          "gain": 0.7
        }
      ]
    }
  ]
}
```

---

## 제약 사항

- $1 \le \text{candidates} \le 20$
- $1 \le \text{inference\_rules} \le 50$
- 신뢰도 범위: $0.0 \le \text{confidence} \le 1.0$
- 메모리 제한: 512 MB
- 실행 시간 제한: 3.0 초
