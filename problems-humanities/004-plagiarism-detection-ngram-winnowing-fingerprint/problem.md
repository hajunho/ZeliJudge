# #004 [학문의 양심과 AI 복붙의 최후: N-gram 자카드 유사도와 윈나우잉(Winnowing) 문서 핑거프린팅 표절 검사기 (Academic Plagiarism Detection: N-gram Jaccard Similarity & Winnowing Document Fingerprinting Engine)]

## 1. 장애 및 실무 시나리오

국내 유명 연구중심 대학원 및 학술출판재단은 매 학기 수만 건에 달하는 석·박사 학위 논문 및 학술지 투고 논문의 표절 심사를 진행하고 있습니다.

최근 생성형 AI(ChatGPT 등)와 인터넷 지식 검색이 보편화되면서, 기존 논문들의 구문을 교묘하게 긁어모아 재배치하는 **짜깁기(Mosaic / Patchwork Plagiarism)** 및 특수문자 삽입, 띄어쓰기 변형을 통한 기계식 검사 회피 시도가 폭증하고 있습니다:

```
[지능화된 표절 수법 사례]
1. 단순 복붙(Verbatim): 타인의 핵심 결론 문장을 글자 하나 안 바꾸고 그대로 복사.
2. 모자이크 짜깁기: 논문 A에서 두 문장, 논문 B에서 한 문장을 이어 붙여 출처 없이 작성.
3. 기호 조작 난독화: 단어 사이에 특수기호나 중복 공백을 삽입하여 단순 문자열 일치 검색을 우회.
```

단순히 전체 텍스트를 통째로 문자열 검색(`A in B`)하거나 모든 단어의 $N$-gram 해시를 메모리에 적재하는 방식은 다음과 같은 치명적 한계를 가집니다:
- 수백만 편의 논문 코퍼스를 대상으로 모든 부분문자열을 인덱싱하면 **메모리(RAM) 사용량이 수백 테라바이트로 폭증**하여 시스템이 다운됩니다.
- 문장의 어순을 바꾸거나 수식어를 몇 개 끼워 넣는 것만으로도 전체 일치율이 0%로 떨어져 지능형 표절을 적발하지 못합니다.

학술위원회는 스탠퍼드 대학교 연구진이 고안하고 카피킬러(CopyKiller), 턴잇인(Turnitin), MOSS(Measure of Software Similarity) 등 세계적 표절 검사 시스템의 표준 알고리즘으로 채택된 **윈나우잉(Winnowing) 국소성 보존 문서 핑거프린팅 알고리즘**과 **자카드 유사도(Jaccard Similarity)**를 기반으로 한 고성능 경량 표절 검사 엔진을 구축하고자 합니다.

---

## 2. 문헌정보학·저작권법 및 컴퓨터 과학 이론

### 2.1 윈나우잉(Winnowing) 알고리즘 (Schleimer et al., ACM SIGMOD 2003)
윈나우잉은 긴 텍스트에서 모든 $k$-gram 해시를 보관하지 않고, **슬라이딩 윈도우(Sliding Window) $w$** 내에서 대표 해시(최솟값)만을 선별하여 문서의 지문(Fingerprint)을 $O(N)$ 공간과 시간에 추출하는 알고리즘입니다.

```
+-------------------------------------------------------------------------+
|                  윈나우잉(Winnowing) 핑거프린트 추출 과정                 |
|                                                                         |
| 원본 텍스트: "인공지능의 법적 책임"                                       |
|                                                                         |
| 1. K-gram 분할 (k=5):                                                   |
|    g0: "인공지능의", g1: "공지능의 ", g2: "지능의 법", g3: "능의 법적", ... |
|                                                                         |
| 2. 다항 롤링 해시(Rolling Hash):                                         |
|    H = [h0, h1, h2, h3, h4, h5, ...]                                    |
|                                                                         |
| 3. 크기 w의 슬라이딩 윈도우에서 최솟값 선별:                              |
|    Window 0: [h0, h1, h2, h3] -> min: (h2, pos=2)                      |
|    Window 1: [h1, h2, h3, h4] -> min: (h2, pos=2) (기존과 동일 -> 무시)   |
|    Window 2: [h2, h3, h4, h5] -> min: (h5, pos=5) (신규 최솟값 -> 지문 채택)|
|                                                                         |
| 핵심 수학적 보장(Guarantee):                                             |
| 길이 t = w + k - 1 이상의 임의의 공통 부분문자열은                       |
| 반드시 최소 1개 이상의 윈나우잉 핑거프린트 일치를 보장함!                   |
+-------------------------------------------------------------------------+
```

### 2.2 동점자 처리 규칙 (Tie-Breaking Rule)
윈도우 내에 최솟값 해시가 2개 이상 존재하는 경우, **가장 오른쪽(나중 위치)**에 있는 최솟값을 선택합니다. 이를 통해 윈도우가 오른쪽으로 이동할 때 유효 핑거프린트의 수명을 최대한 연장시켜 전체 지문 집합의 크기를 최소화합니다.

### 2.3 유사도 지표
1. **자카드 유사도 (Jaccard Similarity)**:
   $$J(Q, R) = \frac{|FP_Q \cap FP_R|}{|FP_Q \cup FP_R|}$$
2. **포용률 (Containment Ratio)**:
   Query 문서가 Reference 문서의 내용을 얼마나 포함하고 있는지를 나타내는 단방향 표절률:
   $$C(Q, R) = \frac{|FP_Q \cap FP_R|}{|FP_Q|}$$
3. **글로벌 표절률 (Global Plagiarism Ratio)**:
   Query 문서의 전체 핑거프린트 중 코퍼스 내 적어도 하나 이상의 참고문헌에 등장하는 핑거프린트의 비율.

---

## 3. 입력 사양 (Input Specification)

표준 입력(stdin)으로 하나의 JSON 객체가 주어집니다:

```json
{
  "document_id": "DOC-2026-001",
  "document_title": "양자 컴퓨팅과 고전 암호 체계의 붕괴 전망",
  "query_text": "검사 대상 텍스트 본문...",
  "reference_corpus": [
    {
      "doc_id": "REF-001",
      "doc_title": "참고문헌 1 제목",
      "text": "참고문헌 1 본문..."
    }
  ],
  "config": {
    "k_gram": 5,
    "window_size": 4,
    "similarity_threshold": 0.25
  }
}
```

### 처리 조건:
1. **텍스트 정규화**:
   - 한글, 영문, 숫자, 밑줄을 제외한 모든 특수문자/구두점(`[^\w\s가-힣]`)을 공백으로 치환합니다.
   - 연속된 공백을 단일 공백으로 축소하고 양 끝 공백을 제거(`strip`)합니다.
2. **최소 길이 검사**:
   - 정규화된 Query 텍스트 길이가 $k + w - 1$ 미만이면 즉시 `"INSUFFICIENT_TEXT_LENGTH"`를 반환합니다.
3. **결정론적 다항 해시 (Polynomial Rolling Hash)**:
   - $h = \left( \sum_{i=0}^{k-1} ord(c_i) \times 31^{k-1-i} \right) \pmod{10^9 + 7}$

---

## 4. 출력 사양 (Output Specification)

표준 출력(stdout)으로 다음 스키마의 JSON을 한 줄로 출력합니다:

```json
{
  "status": "CRITICAL_PLAGIARISM_DETECTED",
  "document_id": "DOC-2026-002",
  "document_title": "인공지능 불법행위 책임 연구",
  "text_length": 139,
  "plagiarism_ratio": 1.0,
  "matched_fingerprints_count": 57,
  "total_fingerprints_count": 57,
  "reference_matches": [
    {
      "doc_id": "REF-001",
      "doc_title": "인공지능의 법적 주체성과 불법행위 책임에 관한 고찰",
      "jaccard_similarity": 1.0,
      "containment_ratio": 1.0,
      "matched_fingerprints": 57
    }
  ],
  "diagnostics": [
    "전체 핑거프린트의 100.0%가 기존 코퍼스와 일치합니다. 심각한 저작권 침해 및 복사-붙여넣기(Copy-Paste) 표절 의심."
  ],
  "recommendation": "학위 논문 심사 보류 또는 학술지 게재 철회 권고. 연구윤리위원회 징계 회부 대상."
}
```

### 판정 상태 (`status`):
1. `"INSUFFICIENT_TEXT_LENGTH"`: 텍스트 길이가 $k + w - 1$ 미만.
2. `"CRITICAL_PLAGIARISM_DETECTED"`: 표절률 $\ge 50\%$ (논문 취소 및 중징계 대상).
3. `"SUSPICIOUS_HIGH_SIMILARITY"`: 표절률 $\ge \text{similarity_threshold}$ 및 $< 50\%$ (인용 누락 및 소명 요구).
4. `"ACADEMIC_INTEGRITY_CLEAR"`: 표절률 $< \text{similarity_threshold}$ (연구윤리 통과).
