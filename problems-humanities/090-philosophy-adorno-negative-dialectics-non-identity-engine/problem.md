# 테오도어 아도르노의 부정변증법: 비동일성(Nichtidentische), 동일화 사고 비판 및 성좌(Konstellation) 엔진

## 문제 설명

프랑크푸르트 학파의 대표 철학자 테오도어 W. 아도르노(Theodor W. Adorno)는 1966년 주저 **『부정변증법(Negative Dialektik)』**을 통해 헤겔의 전통적 변증법과 서구 합리주의 철학 전체에 근본적인 도전을 던졌습니다.

헤겔의 관념론적 변증법은 '정-반-합(These-Antithese-Synthese)', 즉 부정의 부정을 통해 더 높은 차원의 긍정적 통일성(지양, *Aufhebung*)과 전체성(절대정신)에 도달할 수 있다고 보았습니다. 그러나 아도르노는 아우슈비츠의 비극 이후 이러한 긍정적 총체성이야말로 개별자의 고통과 특수성을 폭력적으로 말살하는 **동일화 사고(Identitätsdenken)**의 정점이라고 폭로했습니다.

아도르노의 부정변증법은 다음의 세 가지 핵심 기둥 위에 서 있습니다:

1. **동일화 사고의 폭력 (Die Gewalt des Identitätsdenkens)**:
   인간의 이성은 개념을 통해 개별 사물을 파악하려 합니다. 그러나 개념은 언제나 사물의 본질 전체를 포괄하지 못하며, 사물에는 개념으로 환원되지 않는 질적 잉여인 **비동일자/비동일성(das Nichtidentische)**이 남습니다. 자본주의 교환가치 논리와 관료주의가 이 잔여를 억압하고 "사물은 개념과 일치한다"고 강변할 때, 그것은 동일화의 폭력($V_{\text{ident}}$)이 됩니다.
2. **긍정 종합의 거부와 규정적 부정 (Bestimmte Negation)**:
   부정변증법은 모순을 거짓된 화해(*Versöhnung*)로 봉합하지 않습니다. 헤겔처럼 모순을 절대적 체계 안으로 화해시키는 '종합 편향'을 철저히 거부하며, 해소되지 않는 모순과 개별자의 **신체적 고통(Suffering, Leiden)**을 사유의 가장 강력한 원동력으로 보존합니다.
3. **성좌 모델 (Konstellation)**:
   사물을 단일한 상위 개념으로 환원하여 정의하는 대신, 대상의 주위에 서로 다른 비판적 개념들을 마치 밤하늘의 별자리처럼 배치하는 **성좌(Konstellation)** 방법론을 제안합니다. 복수의 개념들이 사물의 서로 다른 측면을 에워싸며 상호 조명할 때, 사물을 개념적으로 폭력 점유하지 않고도 사물의 침묵하는 **비판적 진리 내용(Wahrheitsgehalt)**을 열어젖힐 수 있습니다.

본 문제에서는 아도르노의 부정변증법을 모델링한 **비동일성 비판 및 성좌 역학 엔진**을 구현해야 합니다.

---

## 시스템 아키텍처 및 부정변증법 도식

```
+---------------------------------------------------------------------------------------------------+
|               Theodor W. Adorno: Negative Dialectics & Non-Identity Engine                        |
+---------------------------------------------------------------------------------------------------+

     [ Particular Object: Intrinsic Qualities ]       [ Abstract Conceptual Framework ]
     +----------------------------------------+       +---------------------------------------------+
     | Attributes: a_1, a_2, ..., a_k         |       | Primary Concept C_1: expected_attrs         |
     | Weights: w(a_i) [0..1]                 |       | Additional Concepts: C_2, ..., C_m          |
     +----------------------------------------+       | Hegelian Synthesis Bias: B [0..1]           |
                         |                            +---------------------------------------------+
                         |                                           |
                         +-------------------+   +-------------------+
                                             |   |
                                             v   v
     [ 1. Identitarian Subsumption & Residue Analysis ]
     - Subsumed Attributes: Intersect = Actual & Expected
     - Non-Identical Residue: NonId = Actual - Expected
     - Subsumption Degree: S = |Intersect| / |Expected|
     - Identitarian Violence: V_ident = S * (|NonId| / |Actual|)
     - Non-Identical Suffering: Suffering = sum(w(a) for a in NonId)
                                             |
                                             v
     [ 2. Constellation Illumination & Non-Reconciliation ]
     - Active Concepts Count: m >= 2
     - Multi-Concept Illumination: P_const = 1 - prod(1 - S_j)  (if m >= 2 else 0.0)
     - Non-Reconciliation Index: NonReconciled = 1.0 - B
     - Critical Truth Content: TruthContent = P_const * (Suffering / (1.0 + V_ident))
                                             |
                                             v
     [ 3. Critical Epistemological Regimes ]
     - TOTALITARIAN_IDENTITY    : V_ident >= 0.40 and P_const < 0.60
     - NEGATIVE_CONSTELLATION   : TruthContent >= 0.40 and NonReconciled >= 0.50
     - FALSE_HEGELIAN_SYNTHESIS : NonReconciled < 0.40 and S >= 0.60
     - DIALECTICAL_TENSION      : All other transitional states
```

---

## 수리 및 비판철학적 계산 공식

### 1. 동일화 환원 및 비동일적 잔여 분석
대상 객체는 고유 속성과 가중치 쌍으로 구성된 집합 $A = \{a_1: w_1, a_2: w_2, \dots, a_k: w_k\}$를 갖습니다.
주 개념 $C_1$이 요구하는 기대 속성 집합을 $C_{\text{exp}}$라 할 때:
- 포섭된 속성 집합: $\text{Intersect} = A \cap C_{\text{exp}}$
- 비동일적 잔여 집합: $\text{NonId} = A \setminus C_{\text{exp}}$
- 포섭도(Subsumption Degree):
  $$S = \frac{|\text{Intersect}|}{|C_{\text{exp}}|}$$
- 동일화 폭력도(Identitarian Violence):
  $$V_{\text{ident}} = S \times \frac{|\text{NonId}|}{|A|}$$
- 비동일자의 고통 가중치(Non-Identical Suffering):
  $$\text{Suffering} = \sum_{a \in \text{NonId}} w(a)$$

### 2. 성좌(Konstellation) 조명도와 진리 내용
- 개념의 개수 $m = |\text{concepts}|$가 2개 미만인 경우, 성좌를 이루지 못하므로 $P_{\text{const}} = 0.0$입니다.
- 개념의 개수가 2개 이상인 경우($m \ge 2$), 각 개념 $C_j$의 포섭률 $S_j$에 대해 다면 조명도는 다음과 같이 계산됩니다:
  $$P_{\text{const}} = 1.0 - \prod_{j=1}^m (1.0 - S_j)$$
- 비화해성 지수(Non-Reconciliation Index):
  $$\text{NonReconciled} = 1.0 - B \quad (B: \text{헤겔식 긍정 종합 편향})$$
- 비판적 진리 내용(Critical Truth Content, *Wahrheitsgehalt*):
  $$\text{TruthContent} = \min\left(1.0, \max\left(0.0, P_{\text{const}} \times \frac{\text{Suffering}}{1.0 + V_{\text{ident}}}\right)\right)$$

### 3. 비판적 인식론 레짐 4단계 판정
1. $V_{\text{ident}} \ge 0.40$ 이고 $P_{\text{const}} < 0.60$인 경우:
   $$\to \mathbf{TOTALITARIAN\_IDENTITY} \quad (\text{전체주의적 동일화 사고: 개별자의 폭력적 환원})$$
2. 그렇지 않고 $\text{TruthContent} \ge 0.40$ 이고 $\text{NonReconciled} \ge 0.50$인 경우:
   $$\to \mathbf{NEGATIVE\_CONSTELLATION} \quad (\text{부정변증법적 성좌: 비동일성의 구출과 진리 개시})$$
3. 그렇지 않고 $\text{NonReconciled} < 0.40$ 이고 $S \ge 0.60$인 경우:
   $$\to \mathbf{FALSE\_HEGELIAN\_SYNTHESIS} \quad (\text{거짓된 헤겔주의적 긍정 종합: 모순의 강제 봉합})$$
4. 그 외의 모든 경우:
   $$\to \mathbf{DIALECTICAL\_TENSION} \quad (\text{해소되지 않는 변증법적 긴장})$$

---

## 입력 형식

표준 입력(stdin)으로 다음 구조의 JSON 객체가 주어집니다:

```json
{
  "object": {
    "attributes": {
      "market_price": 0.90,
      "exchange_value": 0.85,
      "artistic_singularity": 0.95,
      "creator_suffering": 0.80
    }
  },
  "concepts": [
    {
      "name": "CommercialAsset",
      "expected_attributes": ["market_price", "exchange_value"]
    }
  ],
  "hegelian_synthesis_bias": 0.50
}
```

---

## 출력 형식

표준 출력(stdout)으로 동일화 비판 분석, 성좌 지표, 비판 레짐을 담은 JSON 객체를 공백 없는 압축 형식(`separators=(',', ':')`)으로 출력합니다:

```json
{
  "identitarian_critique": {
    "subsumed_attributes": ["exchange_value", "market_price"],
    "non_identical_residue": ["artistic_singularity", "creator_suffering"],
    "subsumption_degree": 1.0,
    "identitarian_violence": 0.5,
    "non_identical_suffering": 1.75
  },
  "constellation_metrics": {
    "active_concepts_count": 1,
    "constellation_illumination": 0.0,
    "hegelian_reconciliation": 0.5,
    "non_reconciliation_index": 0.5,
    "truth_content": 0.0
  },
  "critical_regime": "TOTALITARIAN_IDENTITY"
}
```

(모든 수치는 소수점 4자리까지 반올림하여 표기합니다.)

---

## 제약 조건

- 속성 개수: $1 \le |A| \le 1,000$
- 개념 개수: $1 \le |C| \le 50$
- 모든 속성 가중치 및 종합 편향: $[0.0, 1.0]$ 범위의 실수
- 표준 라이브러리만을 사용하여 순수 파이썬으로 구현해야 함
