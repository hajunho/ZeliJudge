# [Humanities #019 깊이 읽기] 문체론(Stylometry)과 버로우스의 델타(Burrows' Delta): 문학적 지문과 정량적 작가 식별의 통계학

## 1. 계량문체론(Stylometry)의 역사와 패러다임 전환

문체론(Stylometry)은 문학 작품이나 역사 문서의 문체적 특징을 통계적·계량적으로 분석하여 저작권 귀속(Authorship Attribution), 위작 검증, 텍스트 연대 추정 등을 수행하는 디지털 인문학(Digital Humanities)과 법언어학(Forensic Linguistics)의 핵심 분과입니다.

19세기 말 T. C. 멘덴홀(Mendenhall, 1887)의 단어 길이 분포 연구로부터 출발한 고전 문체론은, 1964년 하버드 대학 통계학자 프레더릭 모스텔러(Frederick Mosteller)와 시카고 대학 데이비드 월리스(David Wallace)의 기념비적 저작 **『Inference and Disputed Authorship: The Federalist』**를 통해 현대적 과학의 반열에 올랐습니다.

```
                  [ 저자의 뇌 (작문 인지 과정) ]
                                 │
                 ┌───────────────┴───────────────┐
                 ▼ (의식적 선택: 흉내 내기 쉬움)  ▼ (무의식적 습관: 흉내 불가능)
           [ 내용어 (Content Words) ]       [ 기능어 (Function Words) ]
           - 명사, 동사, 형용사               - 전치사, 접속사, 대명사, 조사
           - 주제(Topic)에 따라 급변          - 통사 구조를 연결하는 보이지 않는 뼈대
           - 모방 및 표절에 취약              - 신경언어학적 고유 지문 (Fingerprint)
```

모스텔러와 월리스가 밝혀낸 가장 중대한 통찰은 다음과 같습니다:
- **내용어(Content Words)**: 소설이나 논문의 주제(전쟁, 사랑, 정치, 경제 등)에 따라 출현 빈도가 요동치며, 다른 작가가 의도적으로 모방하기 매우 쉽습니다.
- **기능어(Function Words)**: 'the', 'of', 'and', 'upon', 'whilst', 'by', 'in', 'that'과 같은 허사나 전치사, 접속사 등은 작가가 글을 쓸 때 거의 100% 무의식적으로 선택하는 통사적 연결 부품입니다. 저자는 자신이 특정 기능어를 몇 퍼센트 비율로 쓰고 있는지 스스로도 인지하지 못하므로, 주제나 장르가 바뀌어도 이 비율은 평생에 걸쳐 극도로 안정된 통계적 항상성을 유지합니다.

---

## 2. 존 버로우스(John Burrows)의 델타(Delta) 척도

2002년 영문학자 존 버로우스 교수가 발표한 **'Delta' (Literary and Linguistic Computing, 2002)**는 복잡한 베이지안 다변량 모델이나 머신러닝 없이도 직관적이면서 놀라울 정도로 정밀한 작가 식별을 가능하게 하여 전 세계 인문학 연구소의 표준 프로토콜로 자리 잡았습니다.

### 2.1 Z-Score 변환의 필연성
서로 다른 기능어들은 자연어 코퍼스 내에서 출현 빈도의 스케일이 극단적으로 차이 납니다:
- 초고빈도어 'the'는 전체 단어의 $5\% \sim 8\%$를 차지합니다.
- 중빈도 기능어 'whilst'나 'upon'은 $0.05\% \sim 0.2\%$ 수준에 불과합니다.

만약 원시 빈도(Raw Frequency)나 단순 상대 빈도의 유클리드 거리를 취한다면, 거리는 오직 'the'나 'and' 같은 소수의 최상위 단어들에 의해 독점되고, 작가의 독특한 문체적 개성을 대변하는 'whilst'나 'upon' 같은 단어들의 미세한 차이는 완전히 묻혀버립니다.

따라서 버로우스는 각 단어 $w_i$의 상대 빈도 분포를 **표준화 점수(Z-score)**로 변환하여 모든 특징(Feature)의 가중치를 대등하게(Scale-invariant) 맞추었습니다:

$$z_i(D) = \frac{f_i(D) - \mu_i}{\sigma_i}$$

여기서 $\mu_i$는 후보 작가군 전체에서의 단어 $w_i$의 평균 상대 빈도이며, $\sigma_i$는 표준편차입니다. Z-Score 변환을 거치면 빈도가 높은 단어이든 낮은 단어이든 모든 단어가 평균 0, 분산 1의 표준 정규 분포 공간 상의 좌표로 매핑됩니다.

### 2.2 맨해튼 거리 기반 버로우스 델타(Burrows' Delta)
미상 텍스트 $T$와 후보 작가 $A_j$ 간의 버로우스 델타 거리는 선택된 $N$개의 MFW(Most Frequent Words) 차원에 대한 Z-Score 차이의 절댓값 평균(맨해튼 거리의 정규화 형태)으로 정의됩니다:

$$\Delta_{\text{Burrows}}(T, A_j) = \frac{1}{N} \sum_{i=1}^N |z_i(T) - z_i(A_j)|$$

- $\Delta = 0$: 대상 텍스트의 기능어 Z-Score 프로파일이 후보 작가의 문체 프로파일과 완벽히 일치함을 의미합니다.
- $\Delta$ 값이 작을수록 문체적 거리가 가깝고, 해당 작가가 집필했을 확률이 기하급수적으로 높아집니다.

---

## 3. 코사인 델타(Cosine Delta / Smith-Aldridge Distance)

2011년 피터 스미스(Peter Smith)와 앨런 올드리지(Elena Aldridge), 그리고 2017년 슈테판 에버트(Stefan Evert) 교수 연구팀은 고차원 문체 공간에서 버로우스의 맨해튼 거리가 지니는 '차원의 저주(Curse of Dimensionality)'를 보완하기 위해 **코사인 델타(Cosine Delta)**를 제안했습니다.

$$\text{Cosine\_Similarity}(T, A_j) = \frac{\sum_{i=1}^N z_i(T) z_i(A_j)}{\sqrt{\sum_{i=1}^N z_i(T)^2} \sqrt{\sum_{i=1}^N z_i(A_j)^2}}$$

$$\Delta_{\text{Cosine}}(T, A_j) = 1.0 - \text{Cosine\_Similarity}(T, A_j)$$

코사인 델타는 문서의 절대적인 길이 편향에 영향을 받지 않고 Z-Score 벡터 간의 **사잇각(Directional Orientation)**만을 측정하므로, 짧은 시편(Poem)이나 극작품의 짧은 대화 단편을 비교할 때 버로우스 델타보다 더 강건한(Robust) 분류 정확도를 보여줍니다.

---

## 4. 롤링 델타(Rolling Delta)와 공동 집필(Collaborative Authorship) 탐지

문학사에서 가장 흥미로운 수수께끼 중 하나는 두 명 이상의 대문호가 한 작품을 공동으로 집필했을 때 발생합니다 (예: 셰익스피어와 플레처의 『The Two Noble Kinsmen』, 괴테와 실러의 협업 작품, 현대 저널리즘 기사 등).

텍스트 전체를 하나의 통짜 문서로 분석하면 두 작가의 문체가 혼합되어 제3의 엉뚱한 작가로 오분류되기 쉽습니다. 이를 극복하는 기법이 바로 **롤링 윈도우(Rolling Window)** 분석입니다:

```
[ Full Document Tokens: 1, 2, 3, ..., L ]
 ├── Window 0: [ 0 ~ W ]  ──► Delta Calculation ──► Predicted: Shakespeare
 ├── Window 1: [ S ~ S+W ] ──► Delta Calculation ──► Predicted: Shakespeare
 │        ...
 ├── Window m: [ m*S ~ m*S+W ] ──► Transition! ──► Predicted: Fletcher  <--- Handoff Point!
 └── Window m+1: ... ──► Predicted: Fletcher
```

1. 텍스트를 일정한 단어 수($W$, 예: 100~500 단어)의 윈도우로 분할하고, 스텝 크기($S$)만큼 슬라이딩합니다.
2. 각 윈도우 조각에 대해 후보 작가군과의 델타 거리를 독립적으로 계산하여 윈도우별 최적 매칭 작가를 도출합니다.
3. 윈도우를 따라 전진하다가 예측 작가가 $A$에서 $B$로 전환되는 지점을 감지함으로써, **어느 막(Act)과 어느 장(Scene)에서 집필의 펜이 다른 작가에게 넘어갔는지**를 단어 오프셋 단위로 정확히 역추적할 수 있습니다.

---

## 5. 인문학적 의의와 현대적 응용

- **『연방주의자 논집』의 역사적 종결**: 해밀턴 사후 200년간 지속된 저작권 논쟁에서, 계량문체론은 12편의 미상 논문이 전적으로 제임스 매디슨(James Madison)의 독자 저작임을 99.9% 이상의 신뢰도로 입증하여 미국 헌정사 논쟁을 종식시켰습니다.
- **셰익스피어 정경(Shakespearean Canon)의 복원**: 옥스퍼드 셰익스피어 전집 편집진은 롤링 델타 분석을 공식 채택하여 『헨리 6세』 1부~3부가 크리스토퍼 말로 및 토머스 내시와의 공동 저작임을 밝혀내고 표지에 공저자로 등재했습니다.
- **법언어학 및 수사학(Forensic Attribution)**: 유서(Suicide Notes)의 진위 판정, 익명 협박 편지 작성자 추적, 학술 표절 및 생성형 AI 대필 텍스트의 인간 저자성 검증 등 현대 사회의 중대한 법적 증거 분석 도구로 활발히 사용되고 있습니다.
