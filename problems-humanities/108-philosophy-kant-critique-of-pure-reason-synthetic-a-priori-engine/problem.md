# 임마누엘 칸트의 순수이성비판: 코페르니쿠스적 전환, 선천적 종합판단, 12 범주 및 현상 대 물자체 엔진

## 문제 설명

근대 서양 철학의 최고봉 **임마누엘 칸트(Immanuel Kant, 1724–1804)**는 1781년 출간된 불후의 주저 **『순수이성비판』(Kritik der reinen Vernunft)**을 통해, 대륙 합리론(데카르트·스피노자·라이프니츠)의 독단론(Dogmatism)과 영국 경험론(로크·버클리·흄)의 회의주의(Skepticism)를 변증법적으로 지양하고 종합하는 **비판철학(Critical Philosophy)**을 수립했습니다.

칸트는 철학사에서 **"코페르니쿠스적 전환(Copernican Revolution)"**이라 불리는 혁명적 역발상을 제안했습니다:
> *"지금까지는 우리의 모든 지식이 대상에 맞추어야 한다고 가정되어 왔다... 이제는 대상이 우리의 인식 능력에 맞추어야 한다고 가정해 보자."*

인간은 대상을 수동적으로 모사하는 거울이 아니라, 자신의 선험적 인식 틀(시공간과 12 범주)을 통해 무질서한 감각 여건을 **객관적 경험의 대상(현상, Phenomenon)**으로 능동적으로 입법하고 구성하는 주체입니다.

```
       [ 외부의 물자체 (Ding an sich / Noumenon) ]  *인식 불가능 (Unknowable)*
                            │
                            ▼ (감각 촉발)
               [ 1. 선험적 감성론 (Transcendental Aesthetic) ]
                 - 순수 직관의 선험적 형식:
                   * 공간 (Space): 외적 감각의 형식 (기하학)
                   * 시간 (Time): 내적 감각의 형식 (산술)
                            │
                            ▼ (감각적 직관들: Sensible Intuitions)
               [ 2. 선험적 분석론 (Transcendental Analytic) ]
                 - "개념 없는 직관은 맹목이고, 내용 없는 사유는 공허하다"
                 - 오성(Verstand)의 12 범주 (분량, 성질, 관계, 양상)
                 - 통각의 선험적 통일 (Transcendental Apperception): "Ich denke"
                            │
                            ▼ (객관적 경험의 구성)
               [ 3. 인식된 현상 (Phenomenon / Erscheinung) ]
                 - 선천적 종합판단 (Synthetic A Priori Judgments) 성립!
                   * 수학 (7+5=12), 기하학 (직선 최단거리), 자연과학 (인과율)
                            │
                            ▼ (한계를 초월하려는 사변적 이성)
               [ 4. 선험적 변증론 (Transcendental Dialectic) ]
                 - 이성의 3대 이념: 영혼(심리학), 우주(우주론), 신(신학)
                 - 선험적 가상 및 이율배반(Antinomy) 발생 -> "물자체 영역 경고!"
```

본 시스템은 칸트의 순수이성비판 인식 모델을 완벽하게 재현한 **선험적 관념론(Transcendental Idealism) 지성 엔진**을 구현합니다.

---

## 핵심 엔진 아키텍처 및 규칙

### 1. 선험적 감성론 (Transcendental Aesthetic)
- 외부 세계의 원초적 감각(`raw_sensations`)이 마음에 주어질 때:
  - 모든 지각은 내적 감각의 형식인 **시간(`temporal_timestamp`)**을 반드시 가져야 합니다.
  - 외적 대상(`is_external: true`)은 외적 감각의 형식인 **공간(`spatial_coord`)**을 반드시 가져야 합니다.
  - 시간이나 공간 형식이 결여된 데이터는 인간 감성에 의해 직관될 수 없어 실패(`aesthetic_form_failures`)로 처리됩니다.

### 2. 선험적 분석론 (Transcendental Analytic)과 12 범주
- 오성의 순수 개념인 **12 범주(Categories)**:
  - **분량(QUANTITY)**: `UNITY`, `PLURALITY`, `TOTALITY`
  - **성질(QUALITY)**: `REALITY`, `NEGATION`, `LIMITATION`
  - **관계(RELATION)**: `SUBSTANCE`, `CAUSALITY`, `COMMUNITY`
  - **양상(MODALITY)**: `POSSIBILITY`, `ACTUALITY`, `NECESSITY`
- 직관된 감각들이 범주를 통해 종합(Synthesis)될 때만 비로소 객관적 대상(`OBJECT_OF_EXPERIENCE_CONSTITUTED`)이 구성됩니다.
- 범주와 결합되지 못한 감각은 **"맹목적 직관(Blind Intuition)"**이 되며, 대상 없이 작동한 범주는 **"공허한 개념(Empty Concept)"**이 됩니다.
- **통각의 선험적 통일 (`ich_denke_active`)**:
  - 모든 표상에 "나는 생각한다(Ich denke)"가 결합되어야만 단일한 의식의 통일체로 완성됩니다. 비활성 시 지각이 파편화(`FRAGMENTED_SENSIBILITY`)됩니다.

### 3. 선천적 종합판단 (Synthetic A Priori Judgments) 판별
- **`ANALYTIC` (분석판단)**: 주어 개념에 술어가 이미 포함됨. 지식을 확장하지 않으나 선험적 필연성을 가짐.
- **`SYNTHETIC_A_POSTERIORI` (경험적 종합판단)**: 경험에 의해 지식을 확장하지만 우연적임.
- **`SYNTHETIC_A_PRIORI` (선천적 종합판단)**: 경험 이전에 성립하는 보편타당한 필연성이면서도 지식을 실질적으로 확장함 (수학 $7+5=12$, 기하학 최단거리, 물리학 인과율).

### 4. 선험적 변증론: 현상(Phenomenon) vs 물자체(Ding an sich)
- 형이상학적 탐구(`metaphysical_inquiries`) 중 초감성적 물자체 영역(`IMMORTAL_SOUL`, `COSMOLOGICAL_INFINITY`, `GOD_EXISTENCE`)에 대한 지식 주장은 감각적 직관이 결여되어 있으므로 **선험적 가상 및 이율배반(`TRANSCENDENTAL_ILLUSION_ANTINOMY`, `knowable = false`)**으로 판정합니다.
- 오직 시공간과 범주로 구성된 경험적 대상(`EMPIRICAL_OBJECT`)만이 학문적 지식의 대상인 **현상(`PHENOMENON_ERSCHEINUNG`, `knowable = true`)**으로 공인됩니다.

---

## 입력 형식

JSON 문자열이 표준 입력(`stdin`)으로 주어집니다:

```json
{
  "agent_id": "Kant_Königsberg",
  "ich_denke_active": true,
  "raw_sensations": [
    {"id": "SENS_01", "content": "Visual red billiard ball", "spatial_coord": [1.0, 2.0, 0.0], "temporal_timestamp": 100, "is_external": true},
    {"id": "SENS_02", "content": "Impact sound", "spatial_coord": [1.0, 2.0, 0.0], "temporal_timestamp": 105, "is_external": true}
  ],
  "categories_applied": [
    {
      "op_id": "SYNTH_CAUSALITY",
      "category_type": "RELATION",
      "category_name": "CAUSALITY",
      "target_sensations": ["SENS_01", "SENS_02"]
    }
  ],
  "synthetic_judgments": [
    {"id": "J_01", "statement": "7 + 5 = 12", "type": "SYNTHETIC_A_PRIORI", "domain": "MATHEMATICS"}
  ],
  "metaphysical_inquiries": [
    {"query_id": "Q_SOUL", "topic": "IMMORTAL_SOUL"},
    {"query_id": "Q_OBJECT", "topic": "EMPIRICAL_OBJECT"}
  ]
}
```

---

## 출력 형식

평가된 지성 메트릭, 구성된 현상 목록, 판단 판별 결과, 변증론적 물자체 비판 결과를 JSON 형태로 표준 출력(`stdout`)에 공백 없이 출력합니다:

```json
{
  "agent_id": "Kant_Königsberg",
  "metrics": {
    "raw_sensations_received": 2,
    "intuited_representations": 2,
    "aesthetic_form_failures": 0,
    "synthesized_phenomena_count": 1,
    "blind_intuitions_count": 0,
    "empty_concepts_count": 0,
    "synthetic_a_priori_judgments": 1,
    "antinomies_contained": 1,
    "transcendental_unity_of_apperception": true,
    "critical_philosophy_score": 57.0
  },
  "verdict": "DEVELOPING_CRITICAL_PHILOSOPHY",
  "phenomena": {
    "SYNTH_CAUSALITY": {
      "op_id": "SYNTH_CAUSALITY",
      "category": "RELATION:CAUSALITY",
      "synthesized_targets": ["SENS_01", "SENS_02"],
      "apperception_unified": true,
      "status": "OBJECT_OF_EXPERIENCE_CONSTITUTED"
    }
  },
  "judgments": [
    {
      "id": "J_01",
      "statement": "7 + 5 = 12",
      "type": "SYNTHETIC_A_PRIORI",
      "domain": "MATHEMATICS",
      "status": "AMPLIATIVE_UNIVERSALLY_NECESSARY",
      "extends_knowledge": true,
      "is_a_priori": true
    }
  ],
  "dialectic_critique": [
    {
      "query_id": "Q_SOUL",
      "topic": "IMMORTAL_SOUL",
      "realm": "DING_AN_SICH_NOUMENON",
      "knowable": false,
      "epistemic_verdict": "TRANSCENDENTAL_ILLUSION_ANTINOMY",
      "reason": "Exceeds sensible intuition; regulative ideal of reason only, cannot be constituted into scientific knowledge"
    },
    {
      "query_id": "Q_OBJECT",
      "topic": "EMPIRICAL_OBJECT",
      "realm": "PHENOMENON_ERSCHEINUNG",
      "knowable": true,
      "epistemic_verdict": "LEGITIMATE_OBJECT_OF_EXPERIENCE",
      "reason": "Structured through space-time intuition and categories under transcendental apperception"
    }
  ]
}
```

---

## 점수 및 판정 공식

1. **비판철학 성숙도 점수 (`critical_philosophy_score`)**:
   - $	ext{aesthetic\_score} = (	ext{intuited} / 	ext{raw\_sensations}) 	imes 25.0$ (감각이 없으면 기본 25.0)
   - $	ext{analytic\_score} = \min(35.0, 	ext{synthesized\_phenomena} 	imes 12.0)$
   - $	ext{synthetic\_score} = \min(20.0, 	ext{synthetic\_a\_priori} 	imes 10.0)$
   - $	ext{critique\_score} = \min(20.0, 	ext{antinomies\_contained} 	imes 10.0)$
   - `apperception_penalty`: `ich_denke_active`가 `false`이면 `-30.0`
   - $	ext{total\_score} = \max(0.0, \min(100.0, 	ext{round}(	ext{sum}, 2)))$
2. **인식 단계 판정 (`verdict`)**:
   - $\ge 80.0$: `"TRANSCENDENTAL_IDEALISM_MATURE"`
   - $\ge 50.0$: `"DEVELOPING_CRITICAL_PHILOSOPHY"`
   - $< 50.0$: `"PRE_CRITICAL_DOGMATIC_SLUMBER"`
