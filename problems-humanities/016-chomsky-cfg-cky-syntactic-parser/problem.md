# [언어학/통사론/컴퓨터언어학] 촘스키 구구조 문법(Chomsky CFG)과 CKY(Cocke-Younger-Kasami) 동적 계획법 통사 파싱 & 구조적 중의성(Syntactic Ambiguity) 해소 엔진

## 문제 설명

인간의 언어는 단순한 단어의 선형적 나열(Linear Sequence)이 아니라, 단어들이 모여 구(Phrase)를 이루고 구들이 모여 절(Clause)과 문장(Sentence)을 구성하는 **위계적 구구조(Hierarchical Phrase Structure / Constituency)**를 지닙니다.

1957년 언어학자이자 인지과학의 선구자인 **노엄 촘스키(Noam Chomsky)**는 저작 *Syntactic Structures(통사 구조)*를 통해 자연어의 문법을 수학적 형식 언어로 기술하는 **문맥 자유 문법(Context-Free Grammar, CFG)**을 제창하였으며, 이는 현대 컴퓨터 과학의 컴파일러 구문 분석과 자연어 처리(NLP) 구문 분석(Parsing)의 초석이 되었습니다.

그러나 자연어는 인공 프로그래밍 언어와 달리 본질적으로 **구조적 중의성(Structural Syntactic Ambiguity)**을 가집니다:
- **전치사구 부착 중의성 (PP-Attachment Ambiguity)**:
  - 예: *"The astronomer saw the star with a telescope"*
    1. **도구 해석 (VP 부착)**: 천문학자가 망원경을 가지고 별을 보았다.  
       `[VP [VP [V saw] [NP the star]] [PP with a telescope]]`
    2. **수식 해석 (NP 부착)**: 천문학자가 망원경을 가진 별을 보았다.  
       `[VP [V saw] [NP [NP the star] [PP with a telescope]]]`
- **접속사 중의성 (Coordination Ambiguity)**:
  - 예: *"old men and women"*
    1. 나이 든 남자들과 (모든) 여성들 (`[NP [NP old men] and [NP women]]`)
    2. 나이 든 (남자들과 여자들) (`[NP old [NP men and women]]`)

이러한 중의성을 효율적으로 탐색하고 가장 유력한 해석을 찾아내기 위해, 컴퓨터 언어학에서는 문법을 **촘스키 정규형(Chomsky Normal Form, CNF)**으로 변환한 뒤 **CKY(Cocke-Younger-Kasami) 동적 계획법(Dynamic Programming)** 알고리즘을 적용합니다.
또한 규칙마다 확률을 부여하는 **확률적 문맥 자유 문법(Probabilistic CFG, PCFG)**을 통해 각 구구조 수형도의 결합 확률 $P(T) = \prod_{(A \to \alpha) \in T} P(A \to \alpha)$을 계산하여 가장 가능성 높은 트리(**Viterbi Parse**)를 도출합니다.

컴퓨터 언어학 및 디지털 인문학 연구팀의 일원이 되어, 임의의 CNF 문법과 문장을 입력받아 2차원 CKY 파트 차트를 구축하고, 모든 유효한 구구조 수형도(Parse Tree)를 괄호 표기법(Penn Treebank Style)으로 복원하며, 구문론적 적격성 판정 및 중의성 해소를 수행하는 **촘스키 CKY 통사 분석기 엔진**을 구현하십시오.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다.

```json
{
  "grammar": [
    {"lhs": "S", "rhs": ["NP", "VP"], "prob": 1.0},
    {"lhs": "VP", "rhs": ["V", "NP"], "prob": 0.6},
    {"lhs": "VP", "rhs": ["VP", "PP"], "prob": 0.4},
    {"lhs": "NP", "rhs": ["Det", "N"], "prob": 0.6},
    {"lhs": "NP", "rhs": ["NP", "PP"], "prob": 0.4},
    {"lhs": "PP", "rhs": ["P", "NP"], "prob": 1.0},
    {"lhs": "Det", "rhs": ["the"], "prob": 0.6},
    {"lhs": "N", "rhs": ["dog"], "prob": 0.5},
    {"lhs": "N", "rhs": ["cat"], "prob": 0.5},
    {"lhs": "V", "rhs": ["chased"], "prob": 1.0}
  ],
  "queries": [
    {
      "query_id": "Q1",
      "sentence": "the dog chased the cat",
      "start_symbol": "S"
    }
  ]
}
```

- `grammar` (Array of Object): 기본 문법 규칙 목록 (각 규칙: `lhs`, `rhs`, `prob`).
  - `rhs` 길이가 2이면 비말단 기호 생성 규칙 ($A \to B \; C$).
  - `rhs` 길이가 1이면 어휘 말단 기호 생성 규칙 ($A \to a$).
- `queries` (Array of Object): 분석 대상 문장 쿼리 목록.
  - `query_id` (String): 쿼리 고유 식별자
  - `sentence` (String): 공백으로 구분된 토큰 시퀀스
  - `start_symbol` (String, 선택적): 시작 비말단 기호 (기본값 `"S"`)
  - `grammar` (Array of Object, 선택적): 해당 쿼리에만 적용할 오버라이드 문법

---

## 출력 형식

표준 출력(stdout)으로 각 쿼리의 통사 분석 결과가 담긴 JSON 객체를 한 줄(Single-line)로 출력합니다.

```json
{
  "results": [
    {
      "query_id": "Q1",
      "sentence": "the dog chased the cat",
      "token_count": 5,
      "tokens": ["the", "dog", "chased", "the", "cat"],
      "is_grammatical": true,
      "is_ambiguous": false,
      "parse_count": 1,
      "viterbi_parse": {
        "rank": 1,
        "probability": 0.108,
        "parse_tree": "(S (NP (Det the) (N dog)) (VP (V chased) (NP (Det the) (N cat))))"
      },
      "all_parses": [
        {
          "rank": 1,
          "probability": 0.108,
          "parse_tree": "(S (NP (Det the) (N dog)) (VP (V chased) (NP (Det the) (N cat))))"
        }
      ],
      "chart_summary": [
        {"span": [0, 1], "length": 1, "tokens": ["the"], "constituents": ["Det"]},
        {"span": [1, 2], "length": 1, "tokens": ["dog"], "constituents": ["N"]},
        {"span": [0, 2], "length": 2, "tokens": ["the", "dog"], "constituents": ["NP"]}
      ]
    }
  ]
}
```

### 사양 정의
- `is_grammatical`: 시작 기호(예: `S`)로 전체 문장(`span [0, n]`)을 도출하는 수형도가 1개 이상 존재하면 `true`, 없으면 `false`.
- `is_ambiguous`: 유효한 수형도가 2개 이상 존재하면 `true`, 아니면 `false`.
- `viterbi_parse`: 가장 높은 확률을 지닌 최적 수형도 (동률 시 사전순 정렬).
- `all_parses`: 확률 내림차순, 트리 사전순으로 정렬된 전체 수형도 목록.
- `chart_summary`: CKY 파싱 차트에서 하나 이상의 비말단 기호가 유도된 `span [i, i+l]`들의 요약 목록.
