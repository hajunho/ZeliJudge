# [Humanities #019] 문체론과 고전 문학의 과학적 탐정: 존 버로우스(John Burrows)의 델타(Delta) 통계량, 고빈도 기능어(MFW) Z-Score 정규화 기반 미상 문헌 작가 식별(Authorship Attribution) 및 롤링 델타(Rolling Delta) 협업 작가 구간 탐지 엔진

## 문제 설명

문학 연구와 역사학, 법언어학(Forensic Linguistics)에서 가장 매력적이면서도 격렬한 논쟁을 불러일으키는 주제 중 하나는 바로 **"익명 또는 위작 논란이 있는 문헌의 진정한 저자는 누구인가?"**라는 작가 식별(Authorship Attribution) 문제입니다:
- 미국 건국의 초석이 된 『연방주의자 논집(The Federalist Papers)』 85편 중 해밀턴(Alexander Hamilton)과 매디슨(James Madison)이 서로 자신의 저작이라 주장했던 12편의 미상 논문은 과연 누구의 글인가? (1964년 모스텔러와 월리스 Mosteller & Wallace의 고전적 통계 분석)
- 셰익스피어(William Shakespeare)의 희곡 『두 귀족 친척(The Two Noble Kinsmen)』이나 『헨리 8세』는 존 플레처(John Fletcher)와의 공동 집필인가? 막과 장별로 누가 어느 대목을 썼는가?
- 중국 4대 기서 『홍루몽(紅樓夢)』 120회 중 후반 40회는 원작자 조설근(曹雪芹)의 미완성 유고를 고악(高鶚)이 위작·속작한 것인가?
- 조선왕조실록 사관(史官)들의 익명 사론(史論)이나 은밀히 투서된 익명 상소문의 진정한 배후 인물은 누구인가?

인간의 의식적인 문체(주제 단어, 수사적 은유)는 모방하거나 흉내 내기 쉽지만, 무의식적으로 문장의 골격을 짜는 데 사용하는 **기능어(Function Words: 전치사, 접속사, 대명사, 보조사, 한문 허사 등)**의 사용 빈도는 작가 고유의 신경언어학적 지문(Stylistic Fingerprint)처럼 작용합니다.

2002년 호주 뉴캐슬 대학교의 영문학자 **존 버로우스(John Burrows)** 교수는 디지털 인문학(Digital Humanities) 역사상 가장 혁신적이고 널리 쓰이는 계량 문체 분석 척도인 **버로우스의 델타(Burrows' Delta)**를 제안했습니다. 버로우스의 델타는 후보 작가군 전체에서 가장 빈번하게 사용된 상위 단어군(Most Frequent Words, MFW)을 추출하고, 각 작가의 상대 빈도를 **표준 정규 분포(Z-score)**로 정규화한 뒤, 미상 텍스트와의 맨해튼 거리(Manhattan Distance)를 측정하여 가장 문체적 거리가 가까운 작가를 과학적으로 규명합니다.

더 나아가 문헌을 일정한 크기의 윈도우로 슬라이딩하면서 델타 거리를 추적하는 **롤링 델타(Rolling Delta)** 기법을 적용하면, 두 명 이상의 작가가 협업하여 작성한 텍스트에서 **집필자가 전환되는 분기점(Transition Points)**을 정확하게 탐지할 수 있습니다.

당신은 국립중앙도서관 및 디지털인문학 컴퓨터문체론 연구소의 수석 연구원이 되어, 다수의 후보 작가 코퍼스로부터 표준 MFW 어휘 목록과 Z-Score 매트릭스를 구축하고, 미상 고전문헌의 작가를 과학적으로 귀속시키며, 롤링 윈도우를 통해 공동 집필 구간의 작가 전환점을 추적하는 **버로우스 델타 계량 문체론 엔진**을 구현해야 합니다.

---

## 문체론 통계 및 알고리즘 규격

### 1. 텍스트 토큰화(Tokenization) 및 정규화
- 모든 텍스트는 영문 대소문자를 구분하지 않으며, 소문자(`lower()`)로 변환합니다.
- 토큰(단어)은 정규표현식 `\w+` (알파벳, 숫자, 유니코드 단어 문자 연속)로 추출합니다.
- 문서 $D$의 전체 단어 수 $L_D$는 추출된 토큰의 총 개수입니다.

### 2. 후보 작가 코퍼스 프로파일 및 MFW(Most Frequent Words) 선정
- 후보 작가 $k$명 ($A_1, A_2, \dots, A_k$)에 대해, 각 작가가 작성한 모든 텍스트의 토큰을 하나의 작가 코퍼스로 통합(Pooling)합니다. 작가 $A_j$의 총 토큰 수를 $L_{A_j}$라 합니다.
- 전체 참조 코퍼스(모든 작가 통합)에서 각 단어 $w$의 총 출현 횟수 $C(w)$를 집계합니다.
- 전체 단어들을 출현 빈도 내림차순($-C(w)$), 빈도가 같으면 단어 사전순 오름차순으로 정렬합니다.
- 각 작가 $A_j$에 대해 단어 $w$의 상대 빈도(Relative Frequency)를 계산합니다:
  $$f(w, A_j) = \frac{\text{count}(w, A_j)}{L_{A_j}}$$
- 정렬된 단어 목록을 순회하며, $k$명의 후보 작가에 걸친 모평균 $\mu(w)$과 모표준편차 $\sigma(w)$를 계산합니다:
  $$\mu(w) = \frac{1}{k} \sum_{j=1}^k f(w, A_j), \quad \sigma(w) = \sqrt{\frac{1}{k} \sum_{j=1}^k (f(w, A_j) - \mu(w))^2}$$
- **변별력 필터링**: 만약 단어 $w$의 표준편차가 $\sigma(w) \le 10^{-7}$이면(즉, 모든 후보 작가의 사용 빈도가 사실상 동일하여 작가 간 변별력이 전무한 단어), 해당 단어는 MFW 목록에서 제외합니다.
- $\sigma(w) > 10^{-7}$인 단어들만을 순서대로 최대 `mfw_count`개($N$)만큼 추출하여 최종 MFW 목록 $W = [w_1, w_2, \dots, w_N]$을 구성합니다.

### 3. Z-Score 정규화
- 각 MFW 단어 $w_i$ ($i = 1, \dots, N$)에 대해:
  - 후보 작가 $A_j$의 Z-Score:
    $$z_i(A_j) = \frac{f(w_i, A_j) - \mu(w_i)}{\sigma(w_i)}$$
  - 대상 텍스트(또는 윈도우) $T$ (총 단어 수 $L_T$, $w_i$ 출현수 $\text{count}(w_i, T)$)의 Z-Score:
    $$f(w_i, T) = \frac{\text{count}(w_i, T)}{L_T} \quad (L_T = 0\text{이면 } 0), \quad z_i(T) = \frac{f(w_i, T) - \mu(w_i)}{\sigma(w_i)}$$

### 4. 문체적 거리 척도(Distance Metrics) 계산
대상 텍스트 $T$와 후보 작가 $A_j$ 간의 문체 거리는 두 가지 국제 표준 공식으로 각각 산출합니다 (모두 소수점 4자리 반올림):
1. **버로우스의 델타 (Burrows' Delta - 표준 맨해튼 거리)**:
   $$\Delta_{\text{Burrows}}(T, A_j) = \frac{1}{N} \sum_{i=1}^N |z_i(T) - z_i(A_j)|$$
   (단, $N=0$이면 0.0)
2. **코사인 델타 (Cosine Delta / Smith-Aldridge Distance)**:
   $$\text{sim}_{\cos}(T, A_j) = \frac{\sum_{i=1}^N z_i(T) z_i(A_j)}{\sqrt{\sum_{i=1}^N z_i(T)^2} \sqrt{\sum_{i=1}^N z_i(A_j)^2}}$$
   $$\Delta_{\text{Cosine}}(T, A_j) = 1.0 - \text{sim}_{\cos}(T, A_j)$$
   (단, 어느 한쪽의 벡터 노름이 $10^{-9}$ 미만이면 유사도는 0.0, 즉 $\Delta_{\text{Cosine}} = 1.0$으로 처리하며, 코사인 유사도는 $[-1.0, 1.0]$ 범위로 클램핑합니다.)

### 5. 작가 귀속 판정 및 랭킹 (Attribution Ranking)
- 각 거리 척도별로 후보 작가들을 `delta` 오름차순(거리가 가까울수록 유력), 거리가 같으면 작가명 알파벳 오름차순으로 정렬합니다.
- 1위 작가를 `predicted_author`로 지정합니다.
- 신뢰도 마진(`confidence_margin`)은 2위 작가의 델타 거리와 1위 작가의 델타 거리의 차이($\Delta_2 - \Delta_1$)로 계산합니다 (소수점 4자리 반올림, 후보 작가가 1명이면 0.0).

### 6. 롤링 델타(Rolling Delta) 협업 작가 구간 및 전환점 탐지
- `rolling_window` 설정이 주어지고 `window_size > 0`이며 대상 텍스트의 총 단어 수가 `window_size` 이상인 경우에만 수행합니다:
  - 윈도우 인덱스 $m = 0, 1, 2, \dots$에 대해, 시작 단어 오프셋은 $\text{start} = m \times \text{step\_size}$입니다.
  - $\text{start} + \text{window\_size} \le L_T$인 동안 단어 구간 $[\text{start}, \text{start} + \text{window\_size})$을 추출합니다.
  - 해당 윈도우 토큰들의 Z-Score를 구하고 후보 작가들과의 Burrows' Delta 거리를 계산하여 가장 델타가 작은 최적 작가(`predicted_author`)를 결정합니다.
  - 이전 윈도우($m-1$)의 예측 작가와 현재 윈도우($m$)의 예측 작가가 달라진 경우, 집필 전환점(`transitions`)으로 기록합니다:
    `{"window_index": m, "word_offset": start, "from_author": prev_winner, "to_author": curr_winner}`
- 대상 텍스트의 단어 수가 `window_size` 미만이거나 `rolling_window`가 `null`인 경우 `rolling_analysis`는 `null`을 반환합니다.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다:
```json
{
  "config": {
    "mfw_count": 20,
    "rolling_window": {
      "window_size": 30,
      "step_size": 10
    }
  },
  "reference_corpus": [
    {
      "author": "Alexander_Hamilton",
      "texts": [
        "it has been frequently remarked that it seems to have been reserved..."
      ]
    },
    {
      "author": "James_Madison",
      "texts": [
        "among the numerous advantages promised by a well constructed union..."
      ]
    }
  ],
  "target_texts": [
    {
      "id": "federalist_disputed_51",
      "text": "the passions of men will not conform to the dictates of reason..."
    }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 다음 형식의 단일 JSON 객체를 공백 없이(또는 표준 JSON 포맷) 한 줄로 출력합니다:
```json
{
  "corpus_metadata": {
    "candidate_authors": ["Alexander_Hamilton", "James_Madison"],
    "total_mfw_selected": 20,
    "top_mfw": ["the", "of", "and", "to", "in", "..."]
  },
  "attributions": [
    {
      "id": "federalist_disputed_51",
      "word_count": 28,
      "burrows_delta": {
        "predicted_author": "James_Madison",
        "confidence_margin": 0.152,
        "ranking": [
          {"author": "James_Madison", "delta": 0.8542},
          {"author": "Alexander_Hamilton", "delta": 1.0062}
        ]
      },
      "cosine_delta": {
        "predicted_author": "James_Madison",
        "confidence_margin": 0.0821,
        "ranking": [
          {"author": "James_Madison", "delta": 0.7214},
          {"author": "Alexander_Hamilton", "delta": 0.8035}
        ]
      },
      "rolling_analysis": null
    }
  ]
}
```
