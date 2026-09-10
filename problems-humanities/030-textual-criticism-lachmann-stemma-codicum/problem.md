# 문제 #030: 수천 년 전 호메로스와 키케로의 원본 텍스트를 수백 권의 엉터리 필사본 속에서 어떻게 복원할까요?!: 문헌비평학(Textual Criticism): 카를 라흐만(Karl Lachmann)의 필사본 계통수(Stemma Codicum), 공통 오류(Errores Coniunctivi) 및 조본(Archetype) 역추적 엔진

## 1. 개요 (Story & Context)
고대 그리스·로마의 고전(호메로스의 《일리아스》, 키케로의 연설문, 플라톤의 대화편, 베르길리우스의 《아이네이스》)이나 성경 원본(Autograph)은 단 한 줄도 남아있지 않습니다. 오늘날 우리가 읽는 모든 고대 텍스트는 수백 년, 수천 년 동안 중세 수도원의 수많은 서기관들이 손으로 베껴 쓰며 전승한 **필사본(Manuscripts / Witnesses)**들의 집합체입니다.

문제는 서기관들이 로봇이 아니라는 점이었습니다! 서기관들은 밤늦게 졸다가 줄을 통째로 건너뛰거나(Homeoteleuton), 어려운 단어를 쉬운 단어로 고쳐 쓰거나(Lectio facilior), 여백의 메모를 본문으로 착각해 집어넣는 등 수많은 **필사 오류(Scribal Corruptions)**를 누적시켰습니다. 필사본 C가 필사본 B를 베끼고, B가 A를 베끼는 과정에서 오류는 마치 유전병처럼 대를 이어 전파되었습니다.

19세기 독일의 위대한 고전문헌학자 **카를 라흐만(Karl Lachmann, 1793–1851)**은 이 혼돈을 과학적으로 정리하기 위해 근대 문헌비평학의 금자탑인 **‘계통학적 방법론(Lachmannian Method / Stemmatology)’**을 정립했습니다:
1. **공통/연접 오류(Errores Coniunctivi)**:
   우연히 서로 다른 서기관이 독립적으로 똑같이 범하기 힘든 특이한 오류(예: 고유명사의 기괴한 왜곡, 문장 누락). 두 필사본이 이 오류를 공유한다면, 두 필사본은 반드시 그 오류를 만들어낸 **동일한 공통 조상(Hyparchetype, $\alpha$)**으로부터 갈라져 나온 후손입니다!
2. **분리 오류(Errores Separativi)**:
   필사본 A에는 있지만 필사본 B에는 없는 오류. 이것이 존재한다면 B는 A를 베낀 직계 자식이 될 수 없습니다(A에서 빠진 문장이 B에서 기적처럼 되살아날 수는 없기 때문).
3. **파생 사본 제거(Eliminatio Codicum Descriptorum)**:
   만약 필사본 D가 필사본 C의 모든 오류를 100% 물려받았고 거기에 D만의 추가 오류까지 갖고 있다면, D는 C를 그대로 베낀 '무가치한 복사본(Codex Descriptus)'에 불과합니다! 따라서 원본을 복원할 때 D는 가차 없이 제거(Elimination)해야 합니다.
4. **계통수(Stemma Codicum)와 원형(Archetype, $\omega$) 복원**:
   독립적인 계통 분기(Branches)들의 다수결 대조(Recensio)를 통해 최초의 조본(Archetype)을 100% 수학적으로 역추적하고, 현대 학술 출판의 표준인 **비평 장치(Critical Apparatus)**를 자동 생성합니다!

여러분은 디지털 인문학 및 문헌학(Philology) 전산 연구원으로서, 필사본 이본 데이터를 분석하여 필사본 계통수를 복원하고 파생 사본을 걸러내는 **라흐만 문헌비평학 엔진**을 구현해야 합니다!

---

## 2. 입출력 규격 및 처리 규칙

### Mode 1: `"reconstruct_stemma"`
- **입력**:
  - `witnesses`: 필사본 기호 목록 (예: `["A", "B", "C", "D"]`)
  - `loci`: 검증할 본문 구절(Locus) 목록. 각 locus는 `original_reading`과 각 필사본별 독법 `variants: {"A": "...", "B": "..."}`을 포함.
- **처리 규칙**:
  1. 각 필사본의 오류 집합 산출 (`variant != original_reading`).
  2. **파생 사본 제거(`eliminated_descripti`)**: 필사본 $P$의 오류 집합이 필사본 $S$의 오류 집합의 진부분집합($P_{\text{err}} \subset S_{\text{err}}$, $|P_{\text{err}}| > 0$)이면, $S$는 $P$에서 파생된 사본으로 판정하여 독립 필사본 목록에서 제거.
  3. **독립 필사본의 계열(Hyparchetype) 그룹화**: 독립 필사본 간 공유하는 공통 오류(Conjunctive Errors)를 바탕으로 패밀리 그룹 형성.
  4. **비평 장치(Critical Apparatus) 합성**: 각 구절마다 최다 지지를 받은 독법을 `reconstructed_reading`으로 채택하고, 표준 학술 서식(`"readingA A B : readingB C D"`)으로 기록.

### Mode 2: `"evaluate_genealogy"`
- **입력**: `witness_a`, `witness_b`, `loci`
- **판정 규칙**:
  - $A$의 오류가 $B$의 오류의 진부분집합($A_{\text{only}} = 0, B_{\text{only}} > 0, \text{shared} > 0$): `"A_IS_ANCESTOR_OF_B"`
  - $B$의 오류가 $A$의 오류의 진부분집합($B_{\text{only}} = 0, A_{\text{only}} > 0, \text{shared} > 0$): `"B_IS_ANCESTOR_OF_A"`
  - 둘 다 공유 오류가 있고 각자 고유한 분리 오류가 있음($\text{shared} > 0, A_{\text{only}} > 0, B_{\text{only}} > 0$): `"COLLATERAL_COUSINS_SHARE_HYPARCHETYPE"`
  - 공유 오류가 없음($\text{shared} = 0$): `"INDEPENDENT_BRANCHES"`
  - 오류 집합이 완전히 일치하거나 둘 다 오류 없음: `"IDENTICAL_OR_PERFECT_WITNESSES"`
