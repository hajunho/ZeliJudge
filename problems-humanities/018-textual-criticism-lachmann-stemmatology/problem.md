# [역사학/문헌학/서지학] 고문헌 필사본 계통론(Stemmatology / Textual Criticism)과 라흐만(Lachmann) 방법론 기반 이본(Variant Readings) 분기 계통수(Stemma Codicum) 복원 엔진

## 문제 설명

고대와 중세의 위대한 역사서, 철학서, 종교 경전(플라톤, 아리스토텔레스, 성서, 호메로스 서사시, 한국의 『삼국사기(三國史記)』, 『고려사(高麗史)』, 『삼국유사(三國遺事)』, 팔만대장경 등)은 저자가 직접 쓴 최초의 친필 원본(Autograph)이 오늘날까지 남아 있는 경우가 극히 드뭅니다.
우리가 현재 접하는 고문헌은 수백~수천 년 동안 수많은 필사자(Scribes)와 목판 각수들이 대를 이어 손으로 베껴 쓰며 필사 오류(Omission, Dittography, Substitution, Conjectural Emendation)가 겹겹이 누적된 **전승 사본들(Manuscript Witnesses, $A, B, C, \dots$)**뿐입니다.

19세기 고전 문헌학자 **카를 라흐만(Karl Lachmann, 1793~1851)**은 이러한 필사본들의 무질서한 이본(異本, Variant Readings) 속에서 원본 텍스트(Archetype, $\Omega$)를 수학적·계통학적으로 복원하는 **라흐만 방법론(Lachmannian Method / Stemmatology)**을 정립했습니다.

라흐만 계통론의 핵심 공리는 다음과 같습니다:
1. **오류에 의한 계통 묶기 (Common Errors / Bindefehler)**:
   - 두 필사본이 우연히 독립적으로 동일한 오류를 범할 확률은 극히 낮으므로, **"동일한 오류를 공유하는 필사본들은 공통의 조상 사본(Hyparchetype, $\alpha, \beta$)을 갖는다"**는 원리입니다.
   - **결속 오류 (Conjunctive Error, Bindefehler)**: 두 사본을 하나의 가계(Family)로 묶어주는 공유 파생 오류.
   - **분리 오류 (Separative Error, Trennfehler)**: 사본 $A$에는 존재하지만 사본 $B$에는 없는 오류. 이것이 존재하면 $B$가 $A$로부터 직접 복사된 것이 아님을 증명합니다.
2. **불필요한 사본의 제거 (Eliminatio Codicum Descriptorum)**:
   - 만약 사본 $B$가 사본 $A$의 모든 오류를 포함하면서 자기만의 추가 오류만을 갖고 있다면, $B$는 $A$를 단순히 직접 베낀 '종속 사본(Codex Descriptus)'에 불과합니다.
   - 따라서 $B$는 원본 복원에 아무런 독립적 가치가 없으므로 계통 분석에서 즉시 제거(Eliminatio)됩니다.
3. **오염 전승 (Contamination / Horizontal Transmission)**:
   - 필사자가 한 권의 모본(Exemplar)만 베낀 것이 아니라, 다른 계통의 사본을 옆에 두고 대조하며 섞어 베낀 경우를 '오염(Contamination)'이라 합니다.
   - 이는 단순한 트리(Tree) 구조를 다중 부모를 갖는 방향성 비순환 그래프(DAG / Network)로 변형시킵니다.
4. **원본 재구성 (Recensio)과 다수결의 법칙**:
   - 원형을 복원할 때, 사본의 물리적 개수가 아니라 **독립된 계통(Branches)의 다수결**을 따릅니다:
     > **"사본은 세는 것이 아니라 달아보는 것이다" (Codices sunt ponderandi, non numerandi)**
   - 예컨대 계통 $\alpha$에 속한 사본이 100개이고 계통 $\beta, \gamma$에 속한 사본이 각 1개뿐이더라도, 세 독립 계통의 투표 결과가 1($\alpha$) : 2($\beta, \gamma$)라면 다수결에 의해 원본 읽기는 $\beta, \gamma$의 것이 채택됩니다.

역사학·고문헌학 및 디지털 인문학(Digital Humanities) 연구팀의 일원이 되어, 복수의 고문헌 필사본 이본 대조 데이터를 입력받아 필사본 간 해밍 거리 행렬, 결속 오류 및 분리 오류, 종속 사본(Codex Descriptus) 식별, 오염 전승 탐지, 그리고 계통 분기 다수결에 기반한 원본 텍스트(Archetype) 복원 엔진을 구현하십시오.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다.

```json
{
  "loci": [
    {"id": "loc_1", "desc": "noun subject"},
    {"id": "loc_2", "desc": "adjective"}
  ],
  "archetype": {
    "loc_1": "rex",
    "loc_2": "magnus"
  },
  "witnesses": {
    "A": {"loc_1": "lex", "loc_2": "parvus"},
    "B": {"loc_1": "lex", "loc_2": "parvus"}
  }
}
```

- `loci` (Array): 이본이 존재하는 본문 이본 위치(Locus) 목록.
- `archetype` (Object, 선택적): 알려진 기준 원형(Archetype) 읽기 맵.
- `witnesses` (Object): 현존하는 각 필사본의 위치별 읽기 맵 (`{ "A": { "loc_1": "lex", ... }, ... }`).

---

## 출력 형식

표준 출력(stdout)으로 고문헌 계통 분석 결과 요약 및 상세 판정이 담긴 JSON 객체를 한 줄(Single-line)로 출력합니다.

```json
{
  "tradition_summary": {
    "witnesses_count": 2,
    "loci_count": 2,
    "codices_descripti_count": 0,
    "families_detected": 1,
    "contaminated_witnesses_count": 0,
    "ambiguous_loci_count": 0
  },
  "pairwise_differences": {
    "A-B": 0
  },
  "conjunctive_errors": { ... },
  "separative_errors_summary": { ... },
  "codices_descripti": [ ... ],
  "identified_families": [ ... ],
  "contaminated_witnesses": [ ... ],
  "reconstructed_archetype": { ... }
}
```
