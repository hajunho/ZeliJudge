# #006 [기레기는 이제 그만!: 낚시성 기사와 어그로 탐지기: 뉴스 헤드라인-본문 의미적 불일치(Clickbait & Stance Inconsistency) 분석 엔진 (Media Communication: Clickbait Headline-Body Stance Inconsistency & Sensationalism Detection Engine)]

## 1. 장애 및 실무 시나리오

포털 뉴스 서비스 및 언론사 콘텐츠 유통 플랫폼은 매일 수십만 건의 언론 기사를 실시간으로 송고받고 있습니다.

언론사 간의 치열한 조회수(PV) 경쟁과 광고 수익 극대화로 인해, 독자를 기만하는 **'낚시성 기사(Clickbait)'**와 **'제목-본문 불일치 왜곡 보도(Headline-Body Stance Mismatch)'**가 범람하여 미디어 생태계를 심각하게 오염시키고 있습니다:

```
[흔히 마주치는 악성 낚시 보도 유형]
1. 부정어 반전(Negation Flip): 제목은 "A씨 전격 구속!"이라고 단정했으나, 본문은 "법원, 구속영장 기각... 혐의 사실무근"으로 정반대 사실을 서술.
2. 미끼용 인물/키워드 내걸기(Bait-and-Switch): 제목에 유명 스타(손흥민 등) 이름을 대문짝만하게 걸었으나, 본문은 일반 해외 축구 소식만 나열.
3. 어그로 수식어 도배: "충격!", "경악!", "결국 눈물...", "알고 보니...", "발칵" 등 선정적 수식어 남발.
4. 문장부호 스팸: "이럴 수가?!?!", "경악 대반전 실체 폭로!!!" 등 물음표와 느낌표의 무분별한 도배.
```

포털 뉴스 제휴평가위원회(제평위)와 팩트체크 센터는 저널리즘 윤리를 훼손하는 불량 기사를 자동으로 모니터링하고 제휴 점수를 감점할 수 있는 **자연어 처리(NLP) 기반 클릭베이트 & 헤드라인-본문 불일치 검증 엔진**을 구축하기로 했습니다.

---

## 2. 신문방송학·미디어커뮤니케이션 및 자연어 처리(NLP) 이론

### 2.1 저널리즘 윤리와 황색 저널리즘(Yellow Journalism)
한국기자협회 윤리강령 제4조(정당한 정보수집 및 보도) 및 신문윤리실천요강 제3조(보도준칙)는 **"제목은 기사의 내용을 과장하거나 왜곡해서는 안 되며, 기사 본문의 사실적 맥락을 충실히 반영해야 한다"**고 명시하고 있습니다. 사실과 다른 자극적 제목으로 클릭을 유도하는 행위는 독자의 신뢰를 파괴하는 명백한 기만행위입니다.

### 2.2 의미적 불일치 판별 알고리즘 아키텍처
1. **단어 토큰화 및 불용어 제거**: 조사, 어미 등 문법적 기능어(Stopwords)를 배제하고 실질 어휘만을 추출.
2. **TF 벡터 코사인 유사도 (Cosine Similarity)**:
   헤드라인 벡터 $\vec{H}$와 본문 벡터 $\vec{B}$의 내적 및 노름(Norm)을 통해 주제적 일치성을 측정:
   $$\text{Sim}(H, B) = \frac{\vec{H} \cdot \vec{B}}{\|\vec{H}\| \|\vec{B}\|}$$
3. **핵심 키워드 본문 커버리지 (Keyword Coverage)**:
   헤드라인에 등장한 실질 명사 집합 중 본문에도 실제로 출현하는 키워드의 비율:
   $$\text{Coverage} = \frac{|Tokens(H) \cap Tokens(B)|}{|Tokens(H)|}$$
4. **부정어 반전(Negation Flip) 문맥 탐색**:
   본문 내 부정 단어("기각", "사실무근", "부인", "허위", "오보", "아니다")의 전후 5단어 윈도우 내에 헤드라인의 핵심어가 위치하는지 검사. 일치할 경우 **악의적 왜곡(Malicious Mismatch)**으로 즉각 분류.
5. **종합 클릭베이트 점수 (Clickbait Score)**:
   선정적 어휘 출현율, 문장부호 과용 점수, 커버리지 결여 페널티, 코사인 유사도 결여 페널티를 종합 가중 합산하여 $0.0 \sim 1.0$ 구간의 점수로 정량화.

---

## 3. 입력 사양 (Input Specification)

표준 입력(stdin)으로 하나의 기사 JSON 객체가 주어집니다:

```json
{
  "article_id": "NEWS-2026-001",
  "headline": "한국은행, 기준금리 0.25%p 인하 결정... 경기 회복세 견인",
  "body": "한국은행 금융통화위원회가 오늘 본회의를 열고 기준금리를 기존 연 3.50%에서 3.25%로 0.25%포인트 전격 인하하기로 결정했습니다..."
}
```

### 처리 규칙:
- 본문 단어 수(공백 기준 `split()`)가 20단어 미만인 경우 `"INSUFFICIENT_ARTICLE_BODY"`로 즉시 처리.
- 헤드라인 내 특수기호 제거 후 토큰화(한 글자 단어 및 불용어 제외).

---

## 4. 출력 사양 (Output Specification)

표준 출력(stdout)으로 다음 스키마의 JSON을 한 줄로 출력합니다:

```json
{
  "status": "CREDIBLE_REPORTING",
  "article_id": "NEWS-2026-001",
  "headline": "한국은행, 기준금리 0.25%p 인하 결정... 경기 회복세 견인",
  "word_count": 52,
  "clickbait_score": 0.4213,
  "metrics": {
    "cosine_similarity": 0.3536,
    "keyword_coverage": 0.75,
    "sensational_words_count": 0,
    "detected_sensational_words": [],
    "punctuation_spam_score": 0.3,
    "negation_flip_detected": false
  },
  "diagnostics": [
    "헤드라인과 본문 간 내용 일치도 우수(유사도 0.3536, 커버리지 75.0%).",
    "저널리즘 윤리 준수 및 신뢰할 수 있는 정상 보도로 판정."
  ],
  "recommendation": "정상 송고 승인(Pass)."
}
```

### 판정 상태 (`status`):
1. `"INSUFFICIENT_ARTICLE_BODY"`: 본문 단어 수 $< 20$.
2. `"MALICIOUS_FAKE_NEWS_MISMATCH"`: 부정어 반전(Negation Flip)이 발생하여 사실과 정반대로 왜곡된 제목.
3. `"SUSPICIOUS_CLICKBAIT_EXAGGERATION"`: 부정어 반전은 없으나 클릭베이트 점수 $\ge 0.50$인 낚시성·과장 기사.
4. `"CREDIBLE_REPORTING"`: 사실에 기반하고 내용이 일치하는 정상 기사.
