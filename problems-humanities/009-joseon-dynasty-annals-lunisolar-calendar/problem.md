# [인문학/디지털인문학] 조선왕조실록 사료 연대기 및 60갑자·태음태양력 역법 동기화 엔진

## 문제 설명

조선왕조실록(朝鮮王朝實錄)은 472년간(태조~철종)의 국정 전반을 일자별로 기록한 편년체(編年體) 역사 기록물로서 유네스코 세계기록유산에 등재된 인류의 위대한 문화유산입니다.
실록의 모든 기사는 전통 동양 역법에 따라 **"국왕 묘호 + 재위 연수 + 음력 월(윤달 여부) + 일진(日辰, 60갑자) + 천문 현상"** 형태로 기록되어 있습니다:

> *"세종 25년 계해년(1443) 윤7월 15일 기축, 친히 언문 28자를 창제하시니라..."*

그러나 500여 년의 역사 속에서 사관(史官)의 필사 오류, 전란으로 인한 사초 손상, 왕위 계승기 연호 계산의 착오, 인쇄 목판 오탈자 등으로 인해 다양한 사료적 이상(Anomaly)과 오류가 존재합니다:
1. **왕조 연호와 연간지(年干支) 불일치**: 선왕의 승하 후 즉위한 해(즉위년)와 정식 원년(元年, 1년)을 혼동하여 서력 연도 및 60갑자 간지가 1년씩 어긋나는 현상
2. **일진(日辰, 60갑자) 필사 오기**: 음력 날짜와 실제 물리적 연속일(율리우스일)의 60갑자 순환 순번이 $\pm 1$일 또는 오탈자로 불일치하는 현상
3. **태음태양력(Lunisolar Calendar) 윤달 및 대소월 오류**: 윤달이 존재하지 않는 해에 윤달 기사를 배치하거나, 29일 소월(小月)인데 30일 자 기사가 작성된 사료적 결함
4. **천문 현상(일식/월식) 역법 위반**: 달의 삭망(朔望) 주기상 일식(태양-달-지구)은 반드시 **음력 1일(합삭, New Moon)**에만 발생 가능하고, 월식(태양-지구-달)은 반드시 **음력 15~16일(망, Full Moon)**에만 관측 가능한데, 사관이 날짜를 잘못 적어 보름날에 일식을 기록하거나 초하루에 월식을 기록한 천문학적 이상

국사편찬위원회 및 한국학중앙연구원의 디지털 인문학(Digital Humanities) 연구팀의 일원이 되어, 입력된 조선왕조 사료 단편들을 역법 데이터베이스와 대조하여 **서력(Common Era) 양력 날짜 및 요일, 단기(檀紀), 검증된 60갑자 일진을 동기화**하고, 사료 내의 **모든 연대기적/천문학적 이상 및 구조적 에러를 자동 식별**하는 **사료 연대기 정밀 동기화 엔진**을 구현하십시오.

---

## 역법 및 계산 규칙

### 1. 조선 왕조 묘호 및 재위 연수 레퍼런스
사료 분석의 기준이 되는 주요 국왕의 [원년 서력 연도(`start_year`)]와 [최대 재위 연수(`max_year`)]는 다음과 같습니다:
- **태조**: 1392 (max 7)
- **정종**: 1399 (max 2)
- **태종**: 1401 (max 18)
- **세종**: 1419 (max 32)
- **문종**: 1451 (max 2)
- **단종**: 1453 (max 3)
- **세조**: 1455 (max 14)
- **예종**: 1469 (max 1)
- **성종**: 1470 (max 25)
- **연산군**: 1495 (max 12)
- **중종**: 1506 (max 39)
- **인종**: 1545 (max 1)
- **명종**: 1546 (max 22)
- **선조**: 1568 (max 41)
- **광해군**: 1609 (max 15)
- **인조**: 1623 (max 27)
- **효종**: 1650 (max 10)
- **현종**: 1660 (max 15)
- **숙종**: 1675 (max 46)
- **경종**: 1721 (max 4)
- **영조**: 1725 (max 52)
- **정조**: 1777 (max 24)
- **순조**: 1801 (max 34)
- **헌종**: 1835 (max 15)
- **철종**: 1850 (max 14)
- **고종**: 1864 (max 44)
- **순종**: 1907 (max 4)

*(참고: 입력 JSON에 `"kings"` 객체가 별도로 주어질 경우 해당 설정을 우선 적용하고, 없을 경우 위 기본 설정을 사용합니다.)*

- 서력 연도: $Y = 	ext{start\_year} + (	ext{regnal\_year} - 1)$
- 단기 연도: $	ext{Dangi} = Y + 2333$
- 왕 묘호가 등록되지 않은 경우: `INVALID_KING_NAME: {king}`
- 재위 연수 `regnal_year`가 정수가 아니거나 $1 \le 	ext{regnal\_year} \le 	ext{max\_year}$ 범위를 벗어난 경우: `INVALID_REGNAL_YEAR: {regnal_year} (max: {max_year})`

### 2. 60갑자 (육십간지) 산출
- 10천간(天干): `["갑", "을", "병", "정", "무", "기", "경", "신", "임", "계"]` (0~9)
- 12지지(地支): `["자", "축", "인", "묘", "진", "사", "오", "미", "신", "유", "술", "해"]` (0~11)
- 60간지 배열 $	ext{GANJI\_60}[i] = 	ext{STEMS}[i mod 10] + 	ext{BRANCHES}[i mod 12]$ ($0 \le i < 60$)
- **연간지 (Year Ganji)**:
  - $	ext{stem} = (Y - 4) mod 10$
  - $	ext{branch} = (Y - 4) mod 12$
  - $	ext{calculated\_year\_ganji} = 	ext{STEMS}[	ext{stem}] + 	ext{BRANCHES}[	ext{branch}]$
  - 사료에 기록된 `recorded_year_ganji`가 존재하고 계산된 연간지와 다를 경우:
    `YEAR_GANJI_MISMATCH: recorded={rec}, calculated={calc}`

### 3. 태음태양력(음력) $	o$ 양력 변환
- 입력 데이터의 `calendar_db[str(Y)]`에서 해당 연도의 설날 양력 날짜(`lunar_new_year`)와 월별 정보(`months`)를 조회합니다.
  - 연도 정보가 누락된 경우: `CALENDAR_DATA_MISSING: {Y}`
- `months` 목록에서 `month == lunar_month` 및 `is_leap == rec_is_leap`을 만족하는 달을 탐색합니다.
  - 해당하는 달이 존재하지 않는 경우: `INVALID_LUNAR_MONTH: month={m}, is_leap={is_leap}`
- 해당 달의 최대 일수 `max_days`에 대해 $1 \le 	ext{lunar\_day} \le 	ext{max\_days}$ 여부를 검증합니다.
  - 범위를 벗어난 경우: `INVALID_LUNAR_DAY: day={d}, max_days={max_days}`
- 유효한 경우, 해당 음력 연도의 첫날(1월 1일)부터의 경과 일수 $\Delta D$를 계산합니다:
  $$\Delta D = \sum (	ext{목표 달 이전의 모든 달의 days}) + (	ext{lunar\_day} - 1)$$
  $$	ext{solar\_date} = 	ext{lunar\_new\_year} + \Delta D	ext{ 일}$$
- 양력 날짜 문자열: `"YYYY-MM-DD"` (ISO 8601)
- 요일(`day_of_week`): `"MON"`, `"TUE"`, `"WED"`, `"THU"`, `"FRI"`, `"SAT"`, `"SUN"`

### 4. 60갑자 일진(日辰, Day Ganji) 산출 및 오차 검증
- 일진은 역사상 단 하루도 끊기지 않고 60일 주기로 연속 순환합니다.
- 프로렙틱 그레고리력 연속 서수(Python `date.toordinal()`) 기준:
  - 2024년 1월 1일은 갑자(甲子, index 0)일이며, ordinal은 738886입니다.
  - 임의의 양력 일자 $D$의 60갑자 순번:
    $$	ext{idx} = (	ext{toordinal}(D) + 14) mod 60$$
    $$	ext{calculated\_day\_ganji} = 	ext{GANJI\_60}[	ext{idx}]$$
- 사료에 기록된 `recorded_day_ganji`가 존재하고 계산된 일진과 다를 경우:
  - 두 간지의 순번 차이 $	ext{diff} = (	ext{rec\_idx} - 	ext{calc\_idx}) mod 60$
  - 만약 $	ext{diff} > 30$ 이면 $	ext{diff} = 	ext{diff} - 60$ (범위: $-29 \sim +30$)
  - 기록된 간지가 유효한 60간지가 아닌 경우 $	ext{diff} = 	ext{"UNKNOWN"}$
  - 이상 등록: `DAY_GANJI_MISMATCH: recorded={rec}, calculated={calc}, diff={diff:+d}`

### 5. 천문 현상(일식/월식) 검증
- `event == "SOLAR_ECLIPSE"`:
  - 일식은 반드시 합삭(New Moon, 음력 1일)에만 발생 가능합니다.
  - `lunar_day != 1` 인 경우:
    `ASTRONOMICAL_ANOMALY: SOLAR_ECLIPSE_NOT_ON_NEW_MOON (recorded_day={lunar_day})`
- `event == "LUNAR_ECLIPSE"`:
  - 월식은 반드시 망(Full Moon, 음력 15일 또는 16일)에만 발생 가능합니다.
  - `lunar_day not in (15, 16)` 인 경우:
    `ASTRONOMICAL_ANOMALY: LUNAR_ECLIPSE_NOT_ON_FULL_MOON (recorded_day={lunar_day})`

### 6. 레코드 상태(`status`) 판정
- `INVALID_KING_NAME`, `INVALID_REGNAL_YEAR`, `CALENDAR_DATA_MISSING`, `INVALID_LUNAR_MONTH`, `INVALID_LUNAR_DAY` 중 하나라도 발생한 경우:
  - `status`: `"ERROR"`
  - `solar_year`, `dangi_year`, `calculated_year_ganji`, `solar_date`, `day_of_week`, `calculated_day_ganji` 등 유도 불가능한 필드는 `null`
- 그 외 `YEAR_GANJI_MISMATCH`, `DAY_GANJI_MISMATCH`, `ASTRONOMICAL_ANOMALY` 등의 이상이 1개 이상 감지된 경우:
  - `status`: `"ANOMALY_DETECTED"`
- 어떠한 이상이나 에러도 없는 경우:
  - `status`: `"VALID"`

---

## 입력 형식

표준 입력(`sys.stdin`)으로 단일 JSON 객체가 주어집니다:
```json
{
  "kings": { ... },       // (선택) 국왕 정보 dict. 생략 시 기본 테이블 적용
  "calendar_db": {
    "1443": {
      "lunar_new_year": "1443-01-31",
      "months": [
        {"month": 1, "is_leap": false, "days": 30},
        ...
      ]
    }
  },
  "records": [
    {
      "record_id": "REC_001",
      "king": "세종",
      "regnal_year": 25,
      "lunar_month": 7,
      "is_leap": true,
      "lunar_day": 15,
      "recorded_year_ganji": "계해",
      "recorded_day_ganji": "기축",
      "event": null
    }
  ]
}
```

---

## 출력 형식

표준 출력(`sys.stdout`)으로 결과를 포맷팅된 JSON 문자열(`indent=2`, `ensure_ascii=False`)로 출력합니다:
```json
{
  "records": [
    {
      "record_id": "REC_001",
      "king": "세종",
      "regnal_year": 25,
      "solar_year": 1443,
      "dangi_year": 3776,
      "calculated_year_ganji": "계해",
      "solar_date": "1443-09-09",
      "day_of_week": "SAT",
      "calculated_day_ganji": "기축",
      "status": "VALID",
      "anomalies": []
    }
  ],
  "summary": {
    "total_records": 1,
    "valid_records": 1,
    "anomaly_records": 0,
    "error_records": 0,
    "anomaly_frequency": {}
  }
}
```

### 요약(`summary`) 필드 상세:
- `total_records`: 전체 사료 수
- `valid_records`: 이상/에러가 전혀 없는 정상 사료 수
- `anomaly_records`: 날짜는 유효하나 이상이 감지된 사료 수
- `error_records`: 날짜/왕조 계산이 불가능한 구조적 에러 사료 수
- `anomaly_frequency`: 감지된 이상/에러 유형별 카운트 dict (키 이름 오름차순 정렬).
  - 허용 키: `"INVALID_KING_NAME"`, `"INVALID_REGNAL_YEAR"`, `"CALENDAR_DATA_MISSING"`, `"INVALID_LUNAR_MONTH"`, `"INVALID_LUNAR_DAY"`, `"YEAR_GANJI_MISMATCH"`, `"DAY_GANJI_MISMATCH"`, `"SOLAR_ECLIPSE_NOT_ON_NEW_MOON"`, `"LUNAR_ECLIPSE_NOT_ON_FULL_MOON"`
