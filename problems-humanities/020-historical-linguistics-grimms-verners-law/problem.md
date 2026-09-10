# [Humanities #020] 역사비교언어학의 금자탑: 그림의 법칙(Grimm's Law)과 베르너의 법칙(Verner's Law), 인도유럽조어(PIE) 게르만어파 제1차 자음 추이 및 고대 강세 조건부 음운 재구(Reconstruction) 엔진

## 문제 설명

19세기 초, 인문학 역사상 가장 위대한 과학적 발견 중 하나가 탄생했습니다. 그림 동화의 수집가로 널리 알려진 독일의 언어학자 **야코프 그림(Jacob Grimm)**은 1822년, 라틴어·그리스어·산스크리트어 등 고대 인도유럽어와 게르만어파(영어, 독일어, 고트어, 노르드어 등) 사이의 자음 대응 관계가 단순한 우연이 아니라 **"예외 없는 엄밀한 음운 법칙(First Germanic Sound Shift)"**에 의해 지배되고 있음을 증명했습니다.

그림의 법칙은 3단계의 대규모 자음 연쇄 변동을 설명합니다:
1. **제1막 (무성 파열음 $\to$ 무성 마찰음)**:
   - 인도유럽조어(PIE)의 무성 파열음 $p, t, k, k^w$가 게르만어에서 무성 마찰음 $f, \theta(\text{th}), h(x), hw$로 전환됩니다.
   - 예: 라틴어 *pater* $\to$ 영어 *father*, 라틴어 *tres* $\to$ 영어 *three*, 라틴어 *cornu* $\to$ 영어 *horn*.
   - *(단, $s$ 뒤에 오는 파열음 $sp, st, sk$나 선행 파열음 뒤의 치음 $pt \to ft, kt \to ht$는 마찰음화에서 면제되는 스피란트 예외를 가집니다.)*
2. **제2막 (유성 무기 파열음 $\to$ 무성 파열음)**:
   - PIE의 단순 유성 파열음 $b, d, g, g^w$가 게르만어에서 무성 파열음 $p, t, k, k^w$로 무성음화됩니다.
   - 예: 라틴어 *duo* $\to$ 영어 *two*, 라틴어 *granum* $\to$ 영어 *corn*.
3. **제3막 (유성 유기 파열음 $\to$ 유성 파열음)**:
   - PIE의 유성 유기음 $b^h, d^h, g^h, g^{wh}$가 기식성을 잃고 유성 파열음 $b, d, g, g^w$로 단순화됩니다.
   - 예: 산스크리트어 *bhrātā* $\to$ 영어 *brother*.

하지만 19세기 비교언어학자들을 반세기 동안 깊은 수수께끼에 빠뜨린 거대한 "예외"가 존재했습니다:
- 어째서 PIE $\*bhr\bar{a}\text{́}t\bar{e}r$(형제)의 치음 $t$는 그림의 법칙대로 무성 마찰음 $th$가 되어 영어 *brother*(고트어 *brōþar*)가 되었는데,
- 어째서 PIE $\*p\text{ǝ}t\text{ḗ}r$(아버지)의 치음 $t$는 $\*f\text{æ}\theta er$가 아니라 유성음 $d$로 바뀌어 영어 *father*(고대영어 *fæder*, 고트어 *fadar*)가 되었는가?
- 왜 라틴어 *centum*과 그리스어 *hekatón*에 대응하는 고트어 숫자는 $\*hun\theta$가 아니라 *hund*(백, hundred)인가?

1877년 덴마크의 언어학자 **카를 베르너(Karl Verner)**는 고대 산스크리트어와 베다 성전, 고대 그리스어에 보존되어 있던 **고대 인도유럽조어의 고저 악센트(Pitch Accent) 위치**를 추적하여 이 50년 묵은 미스터리를 완벽히 풀어냈습니다:
> **베르너의 법칙(Verner's Law)**:
> 그림의 법칙(제1막)으로 형성된 무성 마찰음($f, th, h, hw$) 및 고유 무성 마찰음 $s$는, **유성음 환경(모음 및 공명음 사이)에 위치하고 직전 음절 모음에 원래 PIE 강세가 오지 않은 경우(즉, 강세가 뒤 음절에 오거나 앞선 모음이 비강세인 경우), 유성 파열음/마찰음($b, d, g, gw, z$)으로 유성화**된다! (또한 유성화된 $z$는 서게르만/북게르만어에서 $r$로 전이되는 로타시즘 Rhotacism을 거친다).

당신은 국립국어원 및 역사비교언어학 전산연구소의 연구원이 되어, 인도유럽조어(PIE) 어근 음소열과 고대 악센트 위치를 분석하여 그림의 법칙과 베르너의 법칙을 연쇄 적용하고 원시 게르만어(Proto-Germanic) 형태를 무결하게 재구하는 **역사비교언어학 음운 추이 재구 엔진**을 구현해야 합니다.

---

## 음운 체계 및 규칙 적용 순서 (Rule Ordering)

### 1. 음소 기호 분류
- **모음(Vowels) 및 성절 공명음(Syllabic Nuclei)**:
  `["a", "e", "i", "o", "u", "ā", "ē", "ī", "ō", "ū", "ǝ", "y", "m̥", "n̥", "l̥", "r̥"]`
- **공명음(Sonorants)**:
  `["r", "l", "m", "n", "w", "j"]`
- **유성 환경(Voiced Environment)**: 모음 집합과 공명음 집합의 합집합입니다.

### 2. 그림의 법칙 (Grimm's Law - 1차 변동)
각 단어의 음소 토큰을 좌에서 우로 순회하며 변동을 적용합니다:
1. **스피란트 예외 (Exceptions)**:
   - 직전 토큰이 `"s"`인 경우 (`sp`, `st`, `sk`): 마찰음화되지 않고 원래 자음 유지 (`GRIMM_EXCEPTION_PROTECTED_BY_S`).
   - 직전 토큰이 `"p"` 또는 `"k"`이고 현재 토큰이 `"t"`인 경우 (`pt`, `kt`): 선행 자음은 마찰음(`ft`, `ht`)이 되지만 후행 `"t"`는 보존됨 (`GRIMM_SPIRANT_LAW_PROTECTED_T`).
2. **제1막 (무성 파열음 $\to$ 무성 마찰음)** (`GRIMM_ACT_1_VOICELESS_TO_FRICATIVE`):
   - `"p"` $	o$ `"f"`
   - `"t"` $	o$ `"th"`
   - `"k"` $	o$ `"h"`
   - `"kw"` $	o$ `"hw"`
3. **제2막 (유성 무기 파열음 $\to$ 무성 파열음)** (`GRIMM_ACT_2_VOICED_TO_VOICELESS`):
   - `"b"` $	o$ `"p"`
   - `"d"` $	o$ `"t"`
   - `"g"` $	o$ `"k"`
   - `"gw"` $	o$ `"kw"`
4. **제3막 (유성 유기 파열음 $\to$ 유성 파열음)** (`GRIMM_ACT_3_ASPIRATED_TO_VOICED`):
   - `"bh"` $	o$ `"b"`
   - `"dh"` $	o$ `"d"`
   - `"gh"` $	o$ `"g"`
   - `"gwh"` $	o$ `"gw"`

### 3. 베르너의 법칙 (Verner's Law - 2차 변동)
`enable_verners_law`가 `true`인 경우, 그림의 법칙을 거친 토큰열에 대해 수행합니다:
- 대상 무성 마찰음: `["f", "th", "h", "hw", "s"]`
- **적용 조건 (모두 만족해야 함)**:
  1. 단어의 첫머리가 아님 ($j > 0$) 및 마지막 토큰이 아님 ($j < n - 1$).
  2. **유성 환경**: 직전 토큰($j-1$)과 직후 토큰($j+1$)이 모두 유성 환경(모음 또는 공명음)에 속함.
  3. **비선행 강세 조건 (Verner Condition)**:
     - 현재 자음보다 앞에 위치한 가장 가까운 모음(Nucleus)의 토큰 인덱스(`prec_vowel_idx`)를 찾습니다.
     - 만약 해당 선행 모음의 인덱스가 단어의 주 강세 모음 인덱스(`accent_token_index`)와 **다르다면** (즉, 직전 모음에 강세가 없었다면) 베르너의 법칙이 발동합니다!
- **유성화 매핑**:
  - `"f"` $	o$ `"b"`
  - `"th"` $	o$ `"d"`
  - `"h"` $	o$ `"g"`
  - `"hw"` $	o$ `"gw"`
  - `"s"` $	o$ `"z"` (단, `apply_rhotacism`이 `true`이면 `"z"` $	o$ `"r"`로 변환하며 규칙명은 `VERNER_LAW_VOICING_AND_RHOTACISM`, 그렇지 않으면 `VERNER_LAW_VOICING`).

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다:
```json
{
  "config": {
    "enable_verners_law": true,
    "apply_rhotacism": true
  },
  "words": [
    {
      "id": "father",
      "tokens": ["p", "ǝ", "t", "ē", "r"],
      "accent_token_index": 3
    },
    {
      "id": "brother",
      "tokens": ["bh", "ā", "t", "ē", "r"],
      "accent_token_index": 1
    }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 다음 형식의 단일 JSON 객체를 공백 없이(또는 표준 JSON 포맷) 한 줄로 출력합니다:
```json
{
  "total_words_analyzed": 2,
  "results": [
    {
      "id": "father",
      "pie_tokens": ["p", "ǝ", "t", "ē", "r"],
      "pgmc_tokens": ["f", "ǝ", "d", "ē", "r"],
      "reconstructed_word": "fǝdēr",
      "transformations": [
        {
          "token_index": 0,
          "original": "p",
          "stage": "GRIMM_ACT_1_VOICELESS_TO_FRICATIVE",
          "result": "f"
        },
        {
          "token_index": 2,
          "original": "t",
          "stage": "GRIMM_ACT_1_VOICELESS_TO_FRICATIVE",
          "result": "th"
        },
        {
          "token_index": 2,
          "original": "th",
          "stage": "VERNER_LAW_VOICING",
          "result": "d",
          "preceding_vowel_index": 1,
          "accent_index": 3
        }
      ]
    },
    {
      "id": "brother",
      "pie_tokens": ["bh", "ā", "t", "ē", "r"],
      "pgmc_tokens": ["b", "ā", "th", "ē", "r"],
      "reconstructed_word": "bāthēr",
      "transformations": [
        {
          "token_index": 0,
          "original": "bh",
          "stage": "GRIMM_ACT_3_ASPIRATED_TO_VOICED",
          "result": "b"
        },
        {
          "token_index": 2,
          "original": "t",
          "stage": "GRIMM_ACT_1_VOICELESS_TO_FRICATIVE",
          "result": "th"
        }
      ]
    }
  ]
}
```
