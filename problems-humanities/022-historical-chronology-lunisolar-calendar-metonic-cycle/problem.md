# 역사정보학과 동양 역법: 태음태양력 24절기 무중치윤법(無中置閏法), 60간지 세차·월건·일진 및 율리우스일(JDN) 환산 엔진

## 문제 설명

《조선왕조실록》, 《삼국사기》, 《승정원일기》 등 한국과 동아시아의 고문헌 역사 사료는 사건의 발생 시점을 오늘날의 서력(그레고리력) 연월일이 아니라, **세차(歲次, 연간지)·월건(月建, 월간지)·일진(日辰, 일간지)**이라는 정밀한 육십간지(60간지)와 태음태양력(Lunisolar Calendar) 일자로 기록하였습니다. 예를 들어 임진왜란 발발은 *"선조 25년 임진(壬辰)년 4월 13일"*, 훈민정음 반포는 *"세종 28년 병인(丙寅)년 9월 상한"*으로 기록되어 있습니다.

태음태양력은 달의 삭망월(Synodic Month, 약 $29.5306$일)을 기초로 날짜(1일=합삭일, 15일=보름)를 정하되, 1년($12 \times 29.5306 \approx 354.37$일)이 태양년(Tropical Year, 약 $365.2422$일)보다 약 $10.875$일 부족하여 계절이 어긋나는 문제를 해결하기 위해 **24절기(Solar Terms)**와 **윤달(Leap Month)**을 도입했습니다:

1. **19년 7윤법 (장법 章法, Metonic Cycle)**:
   - 19 태양년($19 \times 365.2422 = 6939.60$일)과 235 삭망월($(19 \times 12 + 7) \times 29.5306 = 6939.69$일)은 불과 2시간(0.09일) 차이로 거의 완벽하게 일치합니다. 따라서 19년 동안 정확히 7번의 윤달을 배치하면 계절과 달의 위상이 유지됩니다.
2. **24절기와 무중치윤법 (無中置閏法, Rule of No Mid-Climate Leap Month)**:
   - 태양의 황경($0^\circ \sim 360^\circ$)을 $15^\circ$ 간격으로 나눈 24절기는 홀수 번째의 **절기(節氣, Jieqi)**와 짝수 번째의 **중기(中氣, Zhongqi)**로 교대 배열됩니다:
     - 12 중기: 우수(1월 중기), 춘분(2월 중기), 곡우(3월 중기), 소만(4월 중기), 하지(5월 중기), 대서(6월 중기), 처서(7월 중기), 추분(8월 중기), 상강(9월 중기), 소설(10월 중기), 동지(11월 중기/자월), 대한(12월 중기/축월).
   - 합삭(New Moon)에서 다음 합삭 직전까지의 한 음력 달 안에 **중기(中氣)가 전혀 들어있지 않은 달(무중월, 無中月)**이 발생하면, 그 달을 **직전 달의 윤달(閏月, Leap Month)**로 지정합니다.
3. **육십간지(60간지)와 율리우스일(Julian Day Number, JDN) 역산**:
   - **일진(Day Ganzi)**: 천문학의 연속 일수 계량 단위인 율리우스일(JDN)을 기준으로 계산합니다. 서력 2000년 1월 1일(JDN = 2451545)은 54번째 간지인 **무오(戊午)일**이므로, 임의의 날짜에 대해 다음과 같이 일진 간지 인덱스($0 \sim 59$)가 결정됩니다:
     $$\text{Day Ganzi Index} = (\text{JDN} + 49) \pmod{60}$$
   - **세차(Year Ganzi)**: 서기 4년이 갑자(甲子, 0)년이므로:
     $$\text{Year Ganzi Index} = (Y - 4) \pmod{60}$$
   - **월건(Month Ganzi, 오호돈월법 五虎遁月法)**:
     음력 월의 지지(Branch)는 11월(자월, 子)부터 1월(인월, 寅, 정월)을 거쳐 10월(해월, 亥)까지 고정됩니다. 정월(1월, 인월)의 천간(Stem)은 연간(Year Stem, $s_Y = (Y - 4) \pmod{10}$)에 따라 다음과 같이 시작합니다:
     $$s_{\text{month1}} = (s_Y \times 2 + 2) \pmod{10}$$
     이후 매월 천간이 1씩 순환 증가합니다.

본 문제에서는 합삭 일자 목록과 절기/중기 정보가 주어졌을 때, 무중치윤법을 적용하여 음력 달과 윤달 여부를 판별하고, 질의 일자의 율리우스일(JDN), 음력 일자, 세차, 월건, 일진을 정확하게 계산하는 **역사정보학 동양 역법 환산 엔진**을 구현해야 합니다.

---

## 입력 형식

표준 입력(`sys.stdin`)을 통해 단일 JSON 객체가 전달됩니다:

```json
{
  "calendar_definition": {
    "new_moons": [
      { "date": "2023-01-22" },
      { "date": "2023-02-20" },
      { "date": "2023-03-22" },
      { "date": "2023-04-20" }
    ],
    "solar_terms": [
      { "name": "우수", "date": "2023-02-19", "is_zhongqi": true },
      { "name": "경칩", "date": "2023-03-06", "is_zhongqi": false },
      { "name": "춘분", "date": "2023-03-21", "is_zhongqi": true },
      { "name": "청명", "date": "2023-04-05", "is_zhongqi": false },
      { "name": "곡우", "date": "2023-04-20", "is_zhongqi": true }
    ]
  },
  "queries": [
    {
      "id": "q1",
      "date": "2023-03-25"
    }
  ]
}
```

---

## 출력 형식

표준 출력(`sys.stdout`)으로 compact한 단일 행 JSON 문자열을 출력합니다:

```json
{
  "calendar_summary": {
    "total_lunar_months": 3,
    "leap_month_found": true,
    "leap_month_number": 2,
    "months": [
      {
        "month_number": 1,
        "is_leap": false,
        "days": 29,
        "solar_terms": ["우수"]
      },
      {
        "month_number": 2,
        "is_leap": false,
        "days": 30,
        "solar_terms": ["경칩", "춘분"]
      },
      {
        "month_number": 2,
        "is_leap": true,
        "days": 29,
        "solar_terms": ["청명"]
      }
    ]
  },
  "query_results": [
    {
      "id": "q1",
      "gregorian_date": "2023-03-25",
      "julian_day_number": 2460029,
      "lunar_date": {
        "year": 2023,
        "month": 2,
        "day": 4,
        "is_leap": true,
        "days_in_month": 29
      },
      "year_ganzi": {
        "index": 39,
        "name_ko": "계묘",
        "name_hanja": "癸卯",
        "stem_ko": "계",
        "stem_hanja": "癸",
        "branch_ko": "묘",
        "branch_hanja": "卯",
        "zodiac": "토끼"
      },
      "month_ganzi": {
        "index": 39,
        "name_ko": "을묘",
        "name_hanja": "乙卯",
        "stem_ko": "을",
        "stem_hanja": "乙",
        "branch_ko": "묘",
        "branch_hanja": "卯",
        "zodiac": "토끼"
      },
      "day_ganzi": {
        "index": 54,
        "name_ko": "임오",
        "name_hanja": "壬午",
        "stem_ko": "임",
        "stem_hanja": "壬",
        "branch_ko": "오",
        "branch_hanja": "午",
        "zodiac": "말"
      }
    }
  ]
}
```
