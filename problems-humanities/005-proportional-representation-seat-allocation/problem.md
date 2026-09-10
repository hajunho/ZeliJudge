# #005 [민주주의와 수학의 만남: 비례대표제 선거 의석 배분 알고리즘 (헤어-니마이어 최대잔여법 vs 동트 최고평균법과 갤러거 불비례성 지수) (Political Science: Proportional Representation Seat Allocation Engine - Hare-Niemeyer vs d'Hondt & Gallagher Disproportionality Index)]

## 1. 장애 및 실무 시나리오

중앙선거관리위원회 선거정보시스템 및 정치 데이터 분석 센터는 총선 개표 당일 밤, 전국 254개 지역구 개표가 완료되는 즉시 **정당별 득표율에 따라 비례대표 국회의원 의석을 법률에 규정된 수리적 알고리즘에 따라 오차 없이 배분하는 실시간 연산 시스템**을 운영하고 있습니다.

선거제도는 민주주의의 근간이지만, 의석수는 **이산적인 정수(Integer)**로만 나눌 수 있기 때문에 "어떤 수학적 알고리즘을 채택하느냐"에 따라 원내 제1당이 바뀌거나 정권의 향방이 갈리는 엄청난 정치적 파장을 낳습니다:
1. **봉쇄조항(Electoral Threshold) 필터링**: 정당 득표율 3% 미만이면서 지역구 5석 미만인 군소 정당을 의석 배분 대상에서 정확히 걸러내지 못하면 위헌 및 당선 무효 소송이 제기됨.
2. **최고평균법(d'Hondt)의 거대 정당 편향**: 벨기에 수학자 빅토르 동트가 제안한 동트 방식은 나눗셈 몫($V / s$)을 사용하므로 거대 양당에게 유리하게 잔여 의석이 쏠리는 수학적 편향이 존재함.
3. **최대잔여법(Hare-Niemeyer)과 알라바마 패러독스(Alabama Paradox)**: 소수 정당에 유리한 헤어 쿼터 최대잔여법은 의회 전체 의석을 1석 증원했는데 오히려 특정 정당의 의석이 1석 줄어드는 기괴한 인구 역설(Paradox)을 유발할 수 있음.
4. **민심 왜곡도 측정의 부재**: 선거 결과가 유권자의 정당 지지율과 얼마나 일치하는지를 나타내는 국제 표준 통계 지표인 **갤러거 지수(Gallagher Disproportionality Index)**를 실시간으로 비교 산출해야 함.

선거관리위원회 IT국은 각 정당의 득표수와 지역구 당선자 수가 주어졌을 때, 봉쇄조항 필터링부터 헤어-니마이어 및 동트 의석 배분, 갤러거 불비례성 지수, 그리고 알라바마 패러독스 발생 여부를 전수 시뮬레이션하는 공식 비례대표 의석 배분 룰 엔진을 구축하기로 했습니다.

---

## 2. 정치학·헌법학 및 이산수학 원리

### 2.1 봉쇄조항 (공직선거법 제189조)
군소 정당의 난립으로 인한 의회 마비를 방지하기 위해 다음 조건 중 하나 이상을 충족한 정당에만 비례대표 의석을 배분합니다:
- 전국 유효 투표 총수의 **$3.0\%$ 이상**을 득표한 정당
- 지역구 국회의원 총선거에서 **5석 이상**의 의석을 획득한 정당

의석 배분은 봉쇄조항을 통과한 적격 정당(Eligible Parties)들의 유효 득표수 합계($V_{elig}$)만을 분모로 하여 수행됩니다.

### 2.2 헤어-니마이어 방식 (Hare-Niemeyer / Largest Remainder Method)
1. **헤어 쿼터(Hare Quota)**: $Q = \frac{V_{elig}}{\text{total_seats}}$
2. **기본 의석 배분**: 각 적격 정당의 몫의 정수 부분($\lfloor \text{votes}_i / Q \rfloor$)만큼 의석 배분.
3. **잔여 의석 배분**: 정수 배분 후 남은 의석($\text{total_seats} - \sum \text{base}_i$)을 소수점 이하 잔여값($R_i = \text{votes}_i / Q - \lfloor \text{votes}_i / Q \rfloor$)이 큰 정당 순으로 1석씩 배분.
   - 잔여값 동률 시: 총 득표수가 많은 정당 우선, 득표수도 같으면 입력 순서 우선.

### 2.3 동트 방식 (d'Hondt / Highest Averages Method)
각 적격 정당의 득표수를 $1, 2, 3, \dots, \text{total_seats}$로 나눈 몫(Quotient)들을 전수 계산한 뒤, 전체 몫 중 상위 $\text{total_seats}$개를 획득한 정당에 의석을 1석씩 부여합니다.

### 2.4 갤러거 불비례성 지수 (Gallagher Index / Least Squares Index)
정당 득표율($v_i\%$)과 최종 의석 점유율($s_i\%$) 간의 왜곡도를 측정하는 표준 계량 지표:

$$G = \sqrt{\frac{1}{2} \sum_{i=1}^{M} (v_i - s_i)^2}$$

$G$가 0에 가까울수록 민심(득표율)에 완벽히 비례하며, 값이 클수록 불비례성이 심각함을 의미합니다.

### 2.5 알라바마 패러독스 (Alabama Paradox)
전체 의석수 $S$에서 $S + 1$로 1석을 증원하여 헤어-니마이어 배분을 다시 계산했을 때, **어떤 정당의 의석이 이전보다 오히려 감소하는 기현상**($S_{new} < S_{old}$)을 의미합니다.

---

## 3. 입력 사양 (Input Specification)

표준 입력(stdin)으로 선거 데이터 JSON 객체가 주어집니다:

```json
{
  "election_name": "제22대 국회의원 선거 비례대표",
  "total_seats": 47,
  "threshold_percent": 3.0,
  "min_district_seats_threshold": 5,
  "parties": [
    { "party_name": "더불어민주당", "votes": 10000000, "district_seats": 130 },
    { "party_name": "국민의힘", "votes": 9000000, "district_seats": 120 },
    { "party_name": "조국혁신당", "votes": 2500000, "district_seats": 2 },
    { "party_name": "개혁신당", "votes": 800000, "district_seats": 1 },
    { "party_name": "녹색정의당", "votes": 400000, "district_seats": 0 }
  ]
}
```

---

## 4. 출력 사양 (Output Specification)

표준 출력(stdout)으로 다음 스키마의 JSON을 한 줄로 출력합니다:

```json
{
  "election_name": "제22대 국회의원 선거 비례대표",
  "total_seats": 47,
  "total_votes": 22700000,
  "eligible_parties_count": 4,
  "ineligible_parties_count": 1,
  "hare_niemeyer_allocation": [
    {
      "party_name": "더불어민주당",
      "votes": 10000000,
      "vote_percent": 44.05,
      "base_seats": 21,
      "remainder": 0.0762,
      "final_seats": 21,
      "seat_percent": 44.68
    }
  ],
  "dhondt_allocation": [
    {
      "party_name": "더불어민주당",
      "votes": 10000000,
      "vote_percent": 44.05,
      "final_seats": 22,
      "seat_percent": 46.81
    }
  ],
  "disproportionality": {
    "hare_gallagher_index": 1.55,
    "dhondt_gallagher_index": 2.59,
    "more_proportional_method": "HARE_NIEMEYER"
  },
  "alabama_paradox": {
    "detected": false,
    "details": "총 의석 1석 증원(48석) 시뮬레이션에서 의석 감소 역설(알라바마 패러독스)이 발생하지 않았습니다."
  },
  "diagnostics": [
    "유효 투표수 22,700,000표 중 4개 정당이 봉쇄조항(득표율 3.0% 또는 지역구 5석)을 충족하여 의석 배분 자격을 획득했습니다.",
    "갤러거 불비례성 지수: 헤어-니마이어 1.55 vs 동트 2.59. HARE_NIEMEYER 방식이 유권자의 표심을 더 충실하게 반영합니다."
  ]
}
```
