# 이론 정리: 노엄 촘스키와 모리스 할레의 『SPE』 생성음운론 및 변별 자질 이론

## 1. 생성음운론(Generative Phonology)의 등장 배경

1968년 노엄 촘스키(Noam Chomsky)와 모리스 할레(Morris Halle)가 출간한 『영어의 음성 패턴(The Sound Pattern of English, SPE)』은 현대 이론언어학 역사상 가장 혁신적인 저작 중 하나입니다.

구조주의 음소론(Structuralist Phonemics)에서는 음소(Phoneme)를 최소의 의미 변별 단위로서 원자적(Atomic) 기호로 취급했습니다. 그러나 구조주의적 접근법은 다음과 같은 음운 현상의 일반성을 설명하지 못했습니다:
- 왜 무성 파열음 [p, t, k]는 모음 사이에서 한꺼번에 유성음화([b, d, g])되는가?
- 왜 비음 [m, n, ŋ]은 후행하는 자음의 조음 위치(양순음, 치경음, 연구개음)에 따라 체계적으로 동화되는가?

촘스키와 할레는 인간의 언어 지식이 개별 소리의 목록이 아니라 **생물학적·음향적 조음 기관의 특성을 반영하는 이진 변별 자질(Binary Distinctive Features)**의 조합 체계로 구성되어 있다고 주장했습니다.

---

## 2. SPE 변별 자질 체계 (Distinctive Feature System)

SPE는 모든 분절음(Segment)을 직교하는 이진 자질($[+F]$ 또는 $[-F]$)의 매트릭스(Matrix)로 환원합니다:

### 주요 부류 자질 (Major Class Features)
- **$[\pm\text{cons}]$ (Consonantal)**: 성도(Vocal tract) 내부에 뚜렷한 기류 방해(협착)가 존재하는 소리 (자음 vs 모음/반모음).
- **$[\pm\text{son}]$ (Sonorant)**: 성대 진동과 자발적인 발성을 유지할 수 있는 기류 통로가 확보된 소리 (모음, 비음, 유음, 활음 vs 파열음, 마찰음, 파찰음).
- **$[\pm\text{syll}]$ (Syllabic)**: 음절의 핵(Nucleus) 역할을 할 수 있는 소리 (모음, 성절 자음).

### 공동 및 조음 위치 자질 (Cavity & Place Features)
- **$[\pm\text{cor}]$ (Coronal)**: 혀의 앞부분(설첨 또는 설단)이 중립 위치보다 올라가서 형성되는 소리 (치음, 치경음, 후치경음: [t, d, s, z, n, l]).
- **$[\pm\text{ant}]$ (Anterior)**: 경구개치경부(Alveopalatal)보다 앞쪽(입술, 이, 치경)에서 조음되는 소리 (양순음, 순치음, 치음, 치경음).
- **$[\pm\text{high}], [\pm\text{low}], [\pm\text{back}]$**: 혀 몸통(Tongue body)의 전후/고저 위치.

### 조음 방식 및 발성원 자질 (Manner & Source Features)
- **$[\pm\text{cont}]$ (Continuant)**: 기류가 성도의 중심부를 통해 끊기지 않고 지속되는 소리 (마찰음, 모음 vs 파열음, 비음).
- **$[\pm\text{nas}]$ (Nasal)**: 구개수(Velum)가 내려가 비강으로 공기가 통과하는 소리 ([m, n, ŋ]).
- **$[\pm\text{strid}]$ (Strident)**: 거친 음향적 마찰 소음(Sibilant/Strident)을 동반하는 소리 ([s, z, ʃ, ʒ, tʃ, dʒ]).
- **$[\pm\text{voice}]$ (Voice)**: 성대의 주기적 진동을 동반하는 소리 (유성음 vs 무성음).

---

## 3. 음운 재작성 규칙의 형식 체계 ($A \to B \ / \ C \ \_ \ D$)

SPE의 음운 규칙은 기저형(Underlying Representation)을 물리적 발화인 표면형(Surface Representation)으로 변환하는 형식 문법(Formal Grammar) 규칙입니다:

$$A \to B \ / \ C \ \_ \ D$$

1. **기저형(UR)**: 화자의 정신적 문법(Mental Lexicon)에 저장된 추상적 형태소 표상 (예: 영어 복수형 접미사 `/z/`, 형태소 `/kæt/`, `/bʌs/`).
2. **조건 매칭 ($C \ \_ \ D$)**: 분절음 $A$가 선행 환경 $C$와 후행 환경 $D$ 사이에 위치하는 구조를 스캔.
3. **구조적 변환 ($A \to B$)**:
   - **변이(Mutation)**: 특정 자질값 변경 (예: 무성 장애음 뒤 유성음의 무성음화: $[+\text{strid}] \to [-\text{voice}] \ / \ [-\text{voice}] \ \_$).
   - **삽입(Epenthesis, $\emptyset \to B$)**: 자음 연속을 방지하기 위해 중립 모음 삽입 (예: $[+\text{strid}] \ \_ \ [+\text{strid}]$ 환경에서 $[\partial]$ 삽입).
   - **탈락(Deletion, $A \to \emptyset$)**: 모음 연속(Hiatus)이나 어말 자음군 단순화.

---

## 4. 음운 규칙의 순서성(Rule Ordering)과 동시 적용 원칙

SPE의 핵심적 계산 특성은 **규칙 간의 외적 순서(Extrinsic Ordering)**입니다:
1. 규칙 집합은 순서쌍 $\langle R_1, R_2, \dots, R_m \rangle$으로 주어집니다.
2. 개별 규칙 $R_i$가 문자열에 적용될 때, 해당 규칙에 매칭되는 모든 위치는 **동시에(Simultaneously)** 변환됩니다. 이는 단일 규칙 내에서 연쇄적인 자기 공급(Self-feeding) 무한 루프를 방지합니다.
3. $R_1$의 결과 문자열이 $R_2$의 입력으로 공급되며, 이는 규칙 적용 순서에 따라 **공급(Feeding)** 또는 **차단(Bleeding)** 현상을 유발합니다.

### 예: 영어 복수형 접미사의 도출
- 기저형: `/bæs + z/` (bus + plural)
- **규칙 1 (슈와 삽입)**: $\emptyset \to [\partial] \ / \ [+\text{strid}] \ \_ \ [+\text{strid}]$
  - `/bæsz/` $\to$ `[bæsəz]` (매칭 위치 1개, 삽입 성공)
- **규칙 2 (진행적 무성음화)**: $[+\text{voice}] \to [-\text{voice}] \ / \ [-\text{voice}] \ \_$
  - 이제 접미사 `[z]` 앞에는 무성자음 `[s]`가 아니라 유성모음 `[ə]`가 위치하므로 규칙 2의 환경이 **차단(Bleed)**됩니다.
  - 따라서 `*[bæsəs]`가 아닌 정격형 `[bæsəz]`가 성공적으로 도출됩니다.

---

## 5. 컴퓨터 언어학 및 계산 음운론에서의 의의

1990년대 로널드 카플란(Ronald Kaplan)과 마틴 케이(Martin Kay)는 기념비적 논문 *Phonological Knowledge and Transducers (1994)*를 통해, **순환(Cycle)이 없는 모든 SPE 음운 재작성 규칙은 정규 관계(Regular Relation)를 구성하며 유한 상태 변환기(Finite State Transducer, FST)의 합성(Composition)으로 완전히 동일하게 컴파일될 수 있음**을 수학적으로 증명했습니다.

이 발견은 음성 인식(ASR), 텍스트-음성 변환(TTS), 형태소 분석기(Morpheme Analyzer) 등 현대 자연어 처리 전산 엔진의 근간을 형성했습니다.
