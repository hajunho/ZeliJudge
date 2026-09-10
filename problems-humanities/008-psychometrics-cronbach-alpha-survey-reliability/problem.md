# #008 [설문지의 배신과 연구윤리: 심리측정학 크론바흐 알파(Cronbach's $\alpha$) 내적 일관성 신뢰도와 역문항(Reverse-Scoring) 자동 정제 엔진 (Psychometrics & Psychology: Cronbach's Alpha Reliability & Reverse-Scored Item Purification Engine)]

## 1. 장애 및 실무 시나리오

사회과학(심리학, 경영학, 교육학, 신문방송학) 대학원 석·박사 연구팀 및 대형 여론조사 기관은 매 학기 설문지(리커트 척도)를 이용한 대규모 실증 조사 데이터를 수집하고 통계 분석을 수행합니다.

설문 문항을 통해 피설문자의 '직무 스트레스', '브랜드 충성도', '학습 몰입도'와 같은 **잠재적 심리 구인(Latent Construct)**을 측정할 때 가장 핵심적인 통계 관문은 **내적 일관성 신뢰도(Internal Consistency Reliability)**를 검증하는 **크론바흐 알파 계수(Cronbach's $\alpha$)**입니다.

그러나 설문 분석 과정에서 다음과 같은 빈번한 통계적 재앙이 발생하여 연구가 원점으로 되돌아가는 사태가 속출하고 있습니다:
1. **역코딩(Reverse Scoring) 누락 참사**: "나는 회사가 즐겁다"(긍정)와 "나는 이직하고 싶다"(부정)를 섞어놓고, 부정 문항을 반전($P+1 - x$)하지 않은 채 원점수 그대로 합산하여 $\alpha$ 계수가 음수나 $0.1$대로 폭락하는 참사.
2. **불량 문항으로 인한 신뢰도 파탄**: 전체 문항 중 1~2개 문항이 모호하게 번역되었거나 피설문자의 오해를 불러일으켜, 학술지 게재 최소 기준($\alpha \ge 0.70$)을 미달함.
3. **'문항 삭제 시 신뢰도(Alpha if item deleted)' 수작업 계산 지옥**: 어떤 문항을 제거해야 척도가 살아나는지 일일이 수작업으로 조합을 돌리다가 논문 제출 마감 시한을 놓침.

연구윤리위원회와 통계 분석 지원실은 설문 원시 데이터가 주어졌을 때, 역문항을 자동 반전 코딩하고, 표본 분산 기반의 크론바흐 알파 계수와 수정된 항목-총점 상관계수(Item-Total Correlation)를 산출하여 불량 문항 정제를 자동 권고하는 **심리측정학 신뢰도 분석 엔진**을 구축하기로 했습니다.

---

## 2. 심리학·교육측정학 및 계량통계학 이론

### 2.1 크론바흐 알파 계수 (Cronbach's $\alpha$, Lee Cronbach, 1951)
동일한 개념을 측정하는 $k$개의 문항들로 구성된 척도의 신뢰도를 측정하는 공식:

$$\alpha = \frac{k}{k - 1} \left( 1 - \frac{\sum_{j=1}^{k} s_j^2}{s_X^2} \right)$$

- $k$: 문항 수 ($k \ge 2$)
- $s_j^2$: $j$번째 문항 점수의 표본 분산 (자유도 $N - 1$)
- $s_X^2$: 응답자별 총점($X_i = \sum_{j=1}^k y_{ij}$)의 표본 분산

```
+-------------------------------------------------------------------------+
|                  크론바흐 알파 계수 학술 판정 표준 가이드라인               |
+-------------------+-----------------------------------------------------+
| 알파 계수 범위     | 내적 일관성 신뢰도 수준 및 학술적 의미                |
+-------------------+-----------------------------------------------------+
| alpha >= 0.80     | [우수] EXCELLENT_RELIABILITY: 완벽한 신뢰도 확보.      |
| 0.70 <= alpha < 0.80 | [양호] ACCEPTABLE_RELIABILITY: 학술 연구 통과 기준. |
| alpha < 0.70      | [미달] UNRELIABLE_POOR_CONSISTENCY: 척도 정제 필수.  |
+-------------------+-----------------------------------------------------+
```

### 2.2 리커트 척도 역문항(Reverse Scoring) 공식
불성실 응답(한 줄로 찍기)을 방지하기 위해 척도 중간에 반대 방향으로 배치된 역문항은 $P$점 리커트 척도에서 다음과 같이 선형 반전 변환합니다:

$$y_{new} = (P + 1) - y_{raw}$$

- 5점 척도: $1 \rightarrow 5, 2 \rightarrow 4, 3 \rightarrow 3, 4 \rightarrow 2, 5 \rightarrow 1$
- 7점 척도: $1 \rightarrow 7, 2 \rightarrow 6, \dots, 7 \rightarrow 1$

### 2.3 수정된 항목-총점 상관계수 및 문항 삭제 시 알파
- **수정된 항목-총점 상관계수 ($r_{it}$)**: 해당 문항 점수($y_j$)와 그 문항을 제외한 나머지 문항들의 합계 점수($X^{(-j)}$) 사이의 피어슨 상관계수. $r_{it} < 0.30$이거나 음수이면 불량 문항 강력 의심.
- **문항 삭제 시 알파 ($\alpha_{(-j)}$)**: $j$번째 문항을 영구 삭제했을 때 나머지 $k-1$개 문항으로 재계산한 알파값. $\alpha_{(-j)} > \alpha$라면 해당 문항이 전체 신뢰도를 갉아먹고 있음을 의미.

---

## 3. 입력 사양 (Input Specification)

표준 입력(stdin)으로 설문 문항 및 응답자 데이터 JSON 객체가 주어집니다:

```json
{
  "survey_id": "SURVEY-01",
  "survey_title": "직무 스트레스 척도",
  "scale_points": 5,
  "items": [
    { "item_id": "Q1", "item_text": "업무 스트레스가 심하다", "is_reverse_scored": false },
    { "item_id": "Q2", "item_text": "출근 시 불안감이 든다", "is_reverse_scored": false },
    { "item_id": "Q3", "item_text": "직장 생활이 평온하다", "is_reverse_scored": true },
    { "item_id": "Q4", "item_text": "휴일에도 심리적 압박을 느낀다", "is_reverse_scored": false }
  ],
  "responses": [
    { "respondent_id": "R-01", "answers": { "Q1": 1, "Q2": 2, "Q3": 5, "Q4": 1 } }
  ]
}
```

### 처리 조건:
1. `scale_points` 기준에 따라 `is_reverse_scored: true`인 문항의 응답값을 즉시 변환합니다.
2. 응답자 표본 수 $N < 10$인 경우 `"INSUFFICIENT_SAMPLE_SIZE"`를 반환합니다.
3. 표본 분산은 $N-1$을 분모로 하는 비편향 표본 분산(Unbiased Sample Variance)을 사용합니다.

---

## 4. 출력 사양 (Output Specification)

표준 출력(stdout)으로 다음 스키마의 JSON을 한 줄로 출력합니다:

```json
{
  "status": "EXCELLENT_RELIABILITY",
  "survey_id": "SURVEY-01",
  "survey_title": "직무 스트레스 척도",
  "sample_size": 15,
  "items_count": 4,
  "cronbach_alpha": 0.9848,
  "item_analysis": [
    {
      "item_id": "Q1",
      "is_reverse_scored": false,
      "mean": 3.2,
      "variance": 1.7429,
      "corrected_item_total_correlation": 0.9632,
      "alpha_if_deleted": 0.9781
    }
  ],
  "purification_candidate": null,
  "diagnostics": [
    "크론바흐 알파 계수 0.9848로 내적 일관성 신뢰도가 매우 우수합니다."
  ],
  "recommendation": "모든 문항이 동일한 심리적 구인을 일관되게 측정하고 있으므로 문항 수정 없이 본 분석(요인분석/회귀분석)에 활용하십시오."
}
```

### 판정 상태 (`status`):
1. `"INSUFFICIENT_SAMPLE_SIZE"`: 표본 수 $N < 10$.
2. `"EXCELLENT_RELIABILITY"`: $\alpha \ge 0.80$ (최우수 신뢰도).
3. `"ACCEPTABLE_RELIABILITY"`: $0.70 \le \alpha < 0.80$ (학술 논문 통과 기준).
4. `"UNRELIABLE_POOR_CONSISTENCY"`: $\alpha < 0.70$ (신뢰도 결여, 불량 문항 정제 필수).
