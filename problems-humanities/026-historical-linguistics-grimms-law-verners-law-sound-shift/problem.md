# 역사비교언어학: 인도유럽조어(PIE)에서 게르만조어로의 제1차 자음추이 그림의 법칙(Grimm's Law) 및 베르너의 법칙(Verner's Law) 음운 변천 시뮬레이터

## 문제 설명

영어 단어 *father*는 왜 라틴어 *pater*, 고대 그리스어 *patḗr*, 산스크리트어 *pitā́*와 첫 글자가 다를 뿐 아니라 가운데 자음마저 다를까요?
반면, 같은 가족 어휘인 영어 *brother*는 산스크리트어 *bhrā́tā*, 고대 그리스어 *phrā́tēr*, 라틴어 *frāter*와 비교했을 때 왜 가운데 자음이 *father*처럼 울림소리(Voiced)로 변하지 않고 거친 마찰음 *th*($\theta$)로 남아있을까요?

이 수수께끼는 19세기 근대 언어학을 과학적 학문의 반열에 올려놓은 역사비교언어학(Historical Comparative Linguistics)의 양대 금자탑, **그림의 법칙 (Grimm's Law, 1822)**과 **베르너의 법칙 (Verner's Law, 1877)**에 의해 완벽하게 규명되었습니다.

---

### 1. 그림의 법칙 (Grimm's Law, 제1차 게르만 자음추이)

인도유럽조어(Proto-Indo-European, PIE)가 게르만조어(Proto-Germanic, PGmc)로 분화되면서 파열음(Stops) 체계 전체가 3단계 연쇄 이동(Chain Shift)을 겪었습니다:

1. **Phase 1: 무성 파열음 $\to$ 무성 마찰음 (Voiceless stops $\to$ Voiceless fricatives)**:
   - $*p \to *f$ (예: 라틴어 *pater* $\to$ 영어 *father*)
   - $*t \to *\theta$ (`th`) (예: 라틴어 *tres* $\to$ 영어 *three*)
   - $*k \to *h$ / $*x$ (예: 라틴어 *cord-* $\to$ 영어 *heart*, 라틴어 *canis* $\to$ 영어 *hound*)
   - $*k^w \to *hw$ (예: 라틴어 *quod* $\to$ 영어 *what*)
   - **자음군 제약 예외 (Spirant Law)**: 무성 마찰음/장애음(`s, f, th, h`) 바로 뒤에 위치한 무성 파열음은 마찰음으로 변하지 않고 원형 파열음 상태를 유지합니다! (예: 라틴어 *stare* $\to$ 영어 *stand*, *spuere* $\to$ *spew*). 또한 $*pt \to *ft$, $*kt \to *ht$와 같이 연속된 두 파열음에서는 첫 번째 파열음만 마찰음으로 변하고 두 번째 파열음은 파열음으로 보존됩니다.

2. **Phase 2: 유성 파열음 $\to$ 무성 파열음 (Voiced stops $\to$ Voiceless stops)**:
   - $*b \to *p$ (예: 리투아니아어 *bala* $\to$ 영어 *pool*)
   - $*d \to *t$ (예: 라틴어 *decem*, 그리스어 *deka* $\to$ 영어 *ten*, 라틴어 *duo* $\to$ 영어 *two*)
   - $*g \to *k$ (예: 라틴어 *granum* $\to$ 영어 *corn*, 라틴어 *genus* $\to$ 영어 *kin*)
   - $*g^w \to *kw$ (예: 그리스어 *gynē* $\to$ 영어 *queen*)

3. **Phase 3: 유성 유기음 $\to$ 유성 파열음/마찰음 (Voiced aspirates $\to$ Voiced stops/fricatives)**:
   - $*b^h \to *b$ (예: 산스크리트어 *bhrātā* $\to$ 영어 *brother*)
   - $*d^h \to *d$ (예: 산스크리트어 *dhā-* $\to$ 영어 *do*)
   - $*g^h \to *g$ (예: 라틴어 *hostis* < *ghostis* $\to$ 영어 *guest*)
   - $*g^{wh} \to *w$ (예: 인도유럽조어 *gwherm-* $\to$ 영어 *warm*)

---

### 2. 베르너의 법칙 (Verner's Law, 강세 조건부 유성화)

그림의 법칙만으로는 설명되지 않는 '불규칙한 예외'들이 존재했습니다. 예를 들어 PIE $*ph₂tḗr$의 $*t$는 그림의 법칙에 따르면 무성 마찰음 $*th$가 되어야 하지만, 실제 게르만조어에서는 유성음 $*d$(*fader*)로 변했습니다. 반면 $*bʰráh₂tēr$의 $*t$는 그대로 무성 마찰음 $*th$(*brother*)로 남았습니다.

덴마크의 언어학자 카를 베르너(Karl Verner)는 산스크리트어와 고대 그리스어에 보존된 **고대 인도유럽조어의 고저 강세(Pitch Accent) 위치**를 추적하여 이 현상을 완벽하게 규명했습니다:

- **베르너의 법칙 발동 조건**:
  그림의 법칙 Phase 1에서 생성된 무성 마찰음($*f, *\theta, *h, *hw$) 및 고대 조어 마찰음 $*s$가:
  1. **유성음 환경 (Voiced Environment)**: 양쪽이 모두 유성음(모음, 유음 `l, r`, 비음 `m, n`, 반모음 `w, y`) 사이에 끼어 있고,
  2. **강세 비인접 조건**: 해당 자음의 **바로 앞 모음에 원시 인도유럽조어의 강세가 없었던 경우 (즉, 강세가 뒤따르는 음절에 위치했던 경우)**,
  $\to$ 무성 마찰음이 유성음으로 유성화(Voicing)됩니다!
  - $*f \to *b$
  - $*\theta (`th`) \to *d$
  - $*h \to *g$
  - $*hw \to *gw$
  - $*s \to *z$ (후에 북게르만/서게르만어군에서 로타시즘(Rhotacism)을 거쳐 *r*로 변천. 예: *was* vs *were*)

- 만약 바로 앞 모음에 강세가 있었다면(예: $*bʰrá-tēr$), 베르너의 법칙이 작동하지 않아 그림의 무성 마찰음($*th$)이 그대로 보존됩니다!

---

### 3. 게르만조어 어두 고정 강세화 (Initial Stress Shift)

베르너의 법칙이 완료된 후, 게르만조어는 자유 이동 피치 강세를 버리고 **모든 단어의 첫 번째 음절(모음)에 강세를 고정**하는 '게르만 어두 고정 강세화'를 단행했습니다.

당신은 역사비교언어학 및 전산언어학 연구소의 수석 연구원으로서, 인도유럽조어 형태소와 강세 위치를 입력받아 그림의 법칙 $\to$ 베르너의 법칙 $\to$ 게르만 어두 강세화 3단계 음운 변천 파이프라인을 정밀하게 모사하는 언어학 시뮬레이션 엔진을 구현해야 합니다.

---

## 입력 형식

표준 입력(stdin)으로 분석할 어휘 목록을 담은 단일 JSON 객체가 주어집니다:

```json
{
  "words": [
    {
      "word_id": "father",
      "pie_tokens": ["p", "a", "t", "e", "r"],
      "accent_token_index": 3
    },
    {
      "word_id": "brother",
      "pie_tokens": ["bh", "r", "a", "t", "e", "r"],
      "accent_token_index": 2
    }
  ]
}
```

- `words`: 어휘 객체 배열.
  - `word_id`: 어휘 식별자 (예: `"father"`).
  - `pie_tokens`: 인도유럽조어(PIE) 분절음 토큰 배열 (예: `["p", "a", "t", "e", "r"]`).
    - 유음/비음/반모음/모음은 유성음으로 간주됩니다.
    - 유성 유기음은 `"bh"`, `"dh"`, `"gh"`, `"gwh"`와 같이 표현됩니다.
  - `accent_token_index`: 원시 인도유럽조어에서 피치 강세가 위치한 모음 토큰의 0-based 인덱스.

---

## 출력 형식

표준 출력(stdout)으로 각 어휘의 그림의 법칙 변천 단계, 베르너의 법칙 변천 단계, 최종 게르만조어 형태 및 코퍼스 통계를 포함하는 단일 JSON 라인을 출력합니다:

```json
{
  "corpus_summary": {
    "total_words_analyzed": 2,
    "total_grimm_shifts": 4,
    "total_verner_voicings": 1
  },
  "words": [
    {
      "word_id": "father",
      "pie_form": "pater",
      "pie_accent_token_index": 3,
      "grimm_stage": {
        "tokens": ["f", "a", "th", "e", "r"],
        "form": "father",
        "changes": [
          {"index": 0, "from": "p", "to": "f", "phase": "GRIMM_PHASE_1"},
          {"index": 2, "from": "t", "to": "th", "phase": "GRIMM_PHASE_1"}
        ]
      },
      "verner_stage": {
        "tokens": ["f", "a", "d", "e", "r"],
        "form": "fader",
        "changes": [
          {
            "index": 2,
            "from": "th",
            "to": "d",
            "reason": "Voiced environment & preceding vowel unaccented in PIE",
            "preceding_vowel_index": 1,
            "pie_accent_index": 3
          }
        ]
      },
      "proto_germanic": {
        "tokens": ["f", "a", "d", "e", "r"],
        "form": "fader",
        "fixed_initial_accent_token_index": 1
      }
    }
  ]
}
```
