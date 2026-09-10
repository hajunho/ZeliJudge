# [언어학/국어음운론] 한국어 표준 발음법과 생성 음운론 규칙 적용 순서(SPE Rule Ordering) 전산 엔진

## 문제 설명

자연어 처리(NLP), 음성 합성(TTS, Text-to-Speech), 음성 인식(STT, Speech-to-Text) 및 컴퓨터 언어학(Computational Linguistics) 분야에서, 표기 문자(철자, Grapheme)를 실제 화자의 음성적 발음(Phoneme)으로 변환하는 **G2P(Grapheme-to-Phoneme) 전산 변환 엔진**은 핵심 음운론적 기반 기술입니다.

한국어는 표음문자인 한글을 사용하면서도 형태소를 밝혀 적는 **형태음소적 표기법(Morphophonemic Orthography)**을 채택하고 있어, 표기와 실제 발음 사이에 정밀하고 복잡한 음운 변동 규칙이 작용합니다.
대한민국 국립국어원의 **「표준 발음법」(제8항~제30항)**과 촘스키(Noam Chomsky) & 할레(Morris Halle)의 **생성 음운론(Generative Phonology / SPE 모델)**에 따르면, 한국어 음운 변동은 단순한 독립적 규칙의 나열이 아니라 엄밀한 **규칙 적용 순서(Rule Ordering)**에 따라 지배됩니다.

어떤 규칙이 먼저 적용되어 다음 규칙의 적용 환경을 만들어내는 **피딩(Feeding)** 관계나, 먼저 적용되어 다른 규칙의 적용을 차단하는 **블리딩(Bleeding)** 및 **반블리딩(Counterbleeding)** 관계가 체계적으로 작동합니다:
1. **ㄴ 첨가(N-Insertion)**: 합성어 및 파생어 경계에서 앞 단어가 자음으로 끝나고 뒷 단어가 [i] 또는 반모음 [j]로 시작할 때 초성에 [ㄴ]이 첨가됩니다. (예: `꽃잎` $\to$ `꽃닢`, `물약` $\to$ `물냑`)
2. **거센소리되기(Aspiration / 격음화 / 축약)**: 평폐쇄음(ㄱ, ㄷ, ㅂ, ㅈ)과 'ㅎ'이 결합하여 거센소리(ㅋ, ㅌ, ㅍ, ㅊ)로 축약됩니다. (예: `축하` $\to$ `추카`, `놓고` $\to$ `노코`, `닫히다` $\to$ `다티다`)
3. **구개음화(Palatalization / 교체)**: 끝소리가 'ㄷ', 'ㅌ'인 형태소가 모음 'ㅣ'나 반모음 'j'로 시작하는 형식 형태소를 만날 때 'ㅈ', 'ㅊ'으로 교체됩니다. 특히 'ㄷ' 뒤에 접미사 '-히-'가 결합하여 거센소리 'ㅌ'을 이룬 경우에도 구개음화가 연쇄 적용되어 [ㅊ]으로 발음됩니다(표준 발음법 제17항 붙임). (예: `굳이` $\to$ `구지`, `닫히다` $\to$ `다치다`)
4. **된소리되기(Tensification / 경음화 / 교체)**: 장애음(ㄱ, ㄷ, ㅂ 및 해당 성분을 포함하는 겹받침) 뒤에서 예사소리(ㄱ, ㄷ, ㅂ, ㅅ, ㅈ)가 된소리(ㄲ, ㄸ, ㅃ, ㅆ, ㅉ)로 교체됩니다. 생성 음운론 관점에서 이는 자음군 단순화 이전에 기저의 장애음 성분에 의해 유발(Counterbleeding)됩니다. (예: `국밥` $\to$ `국빱`, `넓다` $\to$ `널따`, `맑게` $\to$ `말께`)
5. **자음군 단순화(Coda Cluster Simplification / 탈락)**: 음절 말 또는 자음 앞에서 겹받침 중 하나가 탈락합니다. (원칙: ㄳ$\to$ㄱ, ㄵ$\to$ㄴ, ㄼ$\to$ㄹ, ㄽ$\to$ㄹ, ㄾ$\to$ㄹ, ㅄ$\to$ㅂ, ㄺ$\to$ㄱ, ㄻ$\to$ㅁ, ㄿ$\to$ㅂ; 예외: 용언 어간 '밟-'의 'ㄼ'은 자음 앞에서 [ㅂ]으로 발음되며, 용언 어간 'ㄺ'은 어미 'ㄱ' 앞에서 [ㄹ]로 발음). (예: `흙만` $\to$ `흑만`, `밟다` $\to$ `밥따`, `맑게` $\to$ `말께`)
6. **음절의 끝소리 규칙(Coda Neutralization / 평파열음화 / 교체)**: 음절 말 또는 자음 앞의 받침이 7개 대표음(ㄱ, ㄴ, ㄷ, ㄹ, ㅁ, ㅂ, ㅇ) 중 하나로 중화됩니다. (예: `꽃` $\to$ `꼳`, `잎` $\to$ `입`)
7. **비음화(Nasalization / 교체)**:
   - 1단계(/ㄹ/의 비음화): 미음(ㅁ), 이응(ㅇ), 기역(ㄱ), 비읍(ㅂ) 받침 뒤의 유음 'ㄹ'은 비음 'ㄴ'으로 교체됩니다. (예: `백로` $\to$ `백노`)
   - 2단계(평파열음 비음화): 평파열음 받침(ㄱ, ㄷ, ㅂ)이 비음(ㄴ, ㅁ) 앞에서 비음(ㅇ, ㄴ, ㅁ)으로 교체됩니다. (예: `백노` $\to$ `뱅노`, `흙만` $\to$ `흥만`, `꽃닢` $\to$ `꼰닙`)
8. **유음화(Lateralization / 교체)**: 비음 'ㄴ'이 유음 'ㄹ'의 앞이나 뒤에서 유음 [ㄹ]로 동화됩니다. (예: `신라` $\to$ `실라`, `물냑` $\to$ `물략`)
9. **연음 법칙(Resyllabification / 재음절화)**: 모음으로 시작하는 형식 형태소 앞(또는 합성어 경계 이후)에서 앞 음절의 받침이 뒷 음절의 초성 자리로 이동합니다. (예: `식용유` $\to$ `시굥뉴`, `옷이` $\to$ `오시`)

인문정보학(Digital Humanities) 및 자연어 처리(NLP) 음운론 연구팀의 일원이 되어, 한국어 단어와 형태·통사적 부가 정보(합성어 경계, 용언 어간 여부, 파생 접미사 여부)를 입력받아 표준 발음법과 규칙 적용 순서에 따른 중간 유도 단계(Derivation Trace), 최종 한글 발음 표기, 국제음성기호(IPA), 4대 음운 변동(교체·탈락·첨가·축약) 분류 통계를 정밀 산출하는 **한국어 표준 발음 및 생성 음운론 전산 엔진**을 구현하십시오.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다.

```json
{
  "queries": [
    {
      "word": "흙만",
      "is_compound": false,
      "compound_boundaries": [],
      "is_predicate": false,
      "has_hi_suffix": false,
      "special_lb_b": false
    }
  ]
}
```

- `queries` (Array): 분석 대상 단어 목록
  - `word` (String): 한글 완성형 단어 문자열
  - `is_compound` (Boolean): 합성어 또는 접두사 파생어 여부 (ㄴ 첨가 적용 조건)
  - `compound_boundaries` (Array of Integer): 형태소 경계 인덱스 목록 (인덱스 $i$는 $i$번째 음절과 $i+1$번째 음절 사이의 경계)
  - `is_predicate` (Boolean): 용언(동사/형용사) 어간-어미 구조 여부 ('밟다'의 ㄼ$\to$ㅂ 예외, '맑게'의 ㄺ$\to$ㄹ 예외, 어간 비음 뒤 된소리되기 적용 조건)
  - `has_hi_suffix` (Boolean): 사동/피동 접미사 '-히-' 결합 여부 (표준 발음법 제17항 붙임 구개음화 연쇄 적용 조건)
  - `special_lb_b` (Boolean): '넓적하다', '넓둥글다' 등 ㄼ$\to$ㅂ 예외 단어 여부

---

## 출력 형식

표준 출력(stdout)으로 각 쿼리의 음운론적 분석 결과를 담은 JSON 객체를 한 줄(Single-line)로 출력합니다.

```json
{
  "results": [
    {
      "word": "흙만",
      "phonetic": "흥만",
      "ipa": "[hɯŋ.man]",
      "rules_applied": [
        "CLUSTER_SIMPLIFICATION",
        "NASALIZATION"
      ],
      "derivation_steps": [
        {"rule": "CLUSTER_SIMPLIFICATION", "form": "흑만"},
        {"rule": "NASALIZATION", "form": "흥만"}
      ],
      "classification": {
        "substitutions": ["NASALIZATION"],
        "deletions": ["CLUSTER_SIMPLIFICATION"],
        "additions": [],
        "contractions": []
      }
    }
  ]
}
```

### 규칙 식별자 정의
- `N_INSERTION`: ㄴ 첨가
- `ASPIRATION`: 거센소리되기 (자음 축약 / 격음화)
- `PALATALIZATION`: 구개음화
- `TENSIFICATION`: 된소리되기 (경음화)
- `CLUSTER_SIMPLIFICATION`: 자음군 단순화
- `CODA_NEUTRALIZATION`: 음절의 끝소리 규칙 (평파열음화)
- `NASALIZATION`: 비음화 (/ㄹ/의 비음화 및 평파열음 비음화)
- `LATERALIZATION`: 유음화
- `RESYLLABIFICATION`: 연음 법칙

### 4대 음운 변동 분류 규격
- `substitutions` (교체): `CODA_NEUTRALIZATION`, `PALATALIZATION`, `NASALIZATION`, `LATERALIZATION`, `TENSIFICATION`
- `deletions` (탈락): `CLUSTER_SIMPLIFICATION`
- `additions` (첨가): `N_INSERTION`
- `contractions` (축약): `ASPIRATION`
- *(참고: `RESYLLABIFICATION`은 단순 재음절화로 4대 음운 변동 분류에는 포함되지 않음)*

---

## 입출력 예시

### 예시 1: 흙만 (자음군 단순화 $\to$ 비음화)
- 입력:
  ```json
  {"queries": [{"word": "흙만", "is_compound": false, "compound_boundaries": [], "is_predicate": false, "has_hi_suffix": false}]}
  ```
- 출력:
  ```json
  {"results": [{"word": "흙만", "phonetic": "흥만", "ipa": "[hɯŋ.man]", "rules_applied": ["CLUSTER_SIMPLIFICATION", "NASALIZATION"], "derivation_steps": [{"rule": "CLUSTER_SIMPLIFICATION", "form": "흑만"}, {"rule": "NASALIZATION", "form": "흥만"}], "classification": {"substitutions": ["NASALIZATION"], "deletions": ["CLUSTER_SIMPLIFICATION"], "additions": [], "contractions": []}}]}
  ```

### 예시 2: 꽃잎 (ㄴ 첨가 $\to$ 끝소리 규칙 $\to$ 비음화)
- 입력:
  ```json
  {"queries": [{"word": "꽃잎", "is_compound": True, "compound_boundaries": [0], "is_predicate": false, "has_hi_suffix": false}]}
  ```
- 출력:
  ```json
  {"results": [{"word": "꽃잎", "phonetic": "꼰닙", "ipa": "[k͈on.nip̚]", "rules_applied": ["N_INSERTION", "CODA_NEUTRALIZATION", "CODA_NEUTRALIZATION", "NASALIZATION"], "derivation_steps": [{"rule": "N_INSERTION", "form": "꽃닢"}, {"rule": "CODA_NEUTRALIZATION", "form": "꼳닢"}, {"rule": "CODA_NEUTRALIZATION", "form": "꼳닙"}, {"rule": "NASALIZATION", "form": "꼰닙"}], "classification": {"substitutions": ["CODA_NEUTRALIZATION", "CODA_NEUTRALIZATION", "NASALIZATION"], "deletions": [], "additions": ["N_INSERTION"], "contractions": []}}]}
  ```
