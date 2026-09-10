# 문제 #027: 수백 년 전 중세 교황과 황제의 양피지 문서에 적힌 날짜를 어떻게 전산 검증할까요?!: 고문서학(Diplomatics)과 중세 편년학: 15년 비잔틴·로마 인딕티오(Indiction) 주기 계산, 국왕 재위연(Regnal Years) 및 부활절 기준 역법(Anno Domini) 상호 정밀 환산 엔진

## 1. 개요 (Story & Context)
유럽의 국립기록원, 바티칸 비밀문서고, 옥스퍼드 보들리언 도서관에는 수천 년 전부터 중세 전역에 걸쳐 작성된 방대한 국왕 특허장(Royal Charters), 교황 칙서(Papal Bulls), 수도원 기증 문서(Monastic Deeds)들이 보존되어 있습니다. 그러나 이 양피지 문서들 중 적지 않은 수는 중세 수도사나 영주들이 토지 소유권과 면세 특권을 날조하기 위해 사후에 정교하게 위조한 **‘가짜 문서(Pseudo-Charters)’**입니다.

인문학의 여왕이자 역사학의 핵심 분과인 **고문서학(Diplomatics, 古文書學)**과 **편년학/연대학(Chronology, 編年學)**은 문서의 진위(Authenticity)를 과학적으로 입증하기 위해 문서 말미에 기록된 **연대 서술구(Eschatocol / Dating Clause)**의 수학적 정합성을 검증합니다.

중세 서기관들은 오늘날처럼 단순히 `"2026-09-10"`과 같이 서기를 적지 않았습니다! 당대에는 위조 방지와 종교적 권위를 위해 다음의 4중 연대학 시스템을 함께 병기했습니다:
1. **15년 주기 인딕티오(Indiction, 15-Year Cycle)**:
   고대 로마 디오클레티아누스 황제의 조세 사정 주기에서 유래한 15년 단위 순환 번호($1 \sim 15$). 서기 $Y$년에 대해 4대 관청 양식(비잔틴/콘스탄티노플 9월 1일, 베다/영국-독일 9월 24일, 로마 교황청 12월 25일, 할례축일 1월 1일)에 따라 기산일이 상이합니다.
2. **새해 기산 양식(Styles of the Beginning of the Year)**:
   중세 율리우스력에서는 1월 1일(할례축일 양식) 외에도, 12월 25일(성탄 양식), 3월 25일(성모영보 양식 - 피렌체식 vs 피사식), 심지어 부활절 일요일(프랑스 카페 왕조 양식)에 새해가 시작되었습니다!
3. **국왕 및 교황 재위연(Regnal Years / Pontifical Years)**:
   "우리 즉위 제14년에...(Anno regni nostri quarto decimo)"와 같이 군주의 즉위일(Accession Date)을 기준으로 계산된 재위 연도.
4. **부활절 계산(Computus) 및 요일(Day of the Week)**:
   달의 위상과 춘분을 결합한 부활절 일요일 계산과 율리우스 적일(JDN) 기반 요일 일치 여부.

여러분은 디지털 인문학(Digital Humanities) 고문서학 연구원으로서, 중세 양피지 문서의 연대 표기를 수학적으로 환산하고 위조 여부를 100% 무결하게 감별하는 **중세 편년학 정밀 검증 엔진**을 구축해야 합니다!

---

## 2. 입출력 규격 및 연산 규칙

### 2.1 율리우스력(Julian Calendar) 기본 규칙
- 모든 연대는 **율리우스력(Julian Calendar)**을 기준으로 계산합니다.
- 윤년 조건: 4로 나누어떨어지는 모든 연도는 윤년입니다 ($Y mod 4 == 0$). (중세에는 그레고리력 400년 윤년 제외 규칙이 없었습니다).
- 2월은 윤년 시 29일, 평년 시 28일입니다.

### 2.2 인딕티오(Indiction) 계산 공식
율리우스 서기 연도 $Y$의 인딕티오 기준 공식:
$$	ext{Indiction} = ((Y_{	ext{eff}} + 2) mod 15) + 1 \quad (1 \le 	ext{Indiction} \le 15)$$
각 지역 문서국의 기산일(Epoch)에 따른 유효 연도 $Y_{	ext{eff}}$:
- **`"byzantine"` (비잔틴 양식)**: 9월 1일 시작.
  - 해당 일자가 9월 1일 이상(9월 1일 ~ 12월 31일)이면 $Y_{	ext{eff}} = Y + 1$, 1월 1일 ~ 8월 31일이면 $Y_{	ext{eff}} = Y$.
- **`"bedan"` (베다/서구 황제 양식)**: 9월 24일 시작.
  - 해당 일자가 9월 24일 이상이면 $Y_{	ext{eff}} = Y + 1$, 그 전이면 $Y_{	ext{eff}} = Y$.
- **`"roman"` (로마 교황청 양식)**: 12월 25일 시작.
  - 해당 일자가 12월 25일 이상이면 $Y_{	ext{eff}} = Y + 1$, 그 전이면 $Y_{	ext{eff}} = Y$.
- **`"circumcision"` (할례축일/현대 양식)**: 1월 1일 시작.
  - 항상 $Y_{	ext{eff}} = Y$.

### 2.3 새해 기산 양식(Calendar Styles)
현대 서기 연도 $Y$와 각 양식에 따른 문서 표기 연도 $Y_{	ext{doc}}$의 관계:
- **`"circumcision"` (할례축일 양식)**: 1월 1일 새해 시작. $Y_{	ext{doc}} = Y$.
- **`"nativity"` (성탄 양식)**: 12월 25일 새해 시작.
  - 12월 25일 ~ 12월 31일은 $Y_{	ext{doc}} = Y + 1$. (역변환 시 문서 표기 연도에서 1을 뺌).
  - 1월 1일 ~ 12월 24일은 $Y_{	ext{doc}} = Y$.
- **`"florentine"` (피렌체 성모영보 양식)**: 3월 25일 새해 시작 (1월 1일보다 늦음).
  - 1월 1일 ~ 3월 24일은 $Y_{	ext{doc}} = Y - 1$. (역변환 시 문서 표기 연도에 1을 더함).
  - 3월 25일 ~ 12월 31일은 $Y_{	ext{doc}} = Y$.
- **`"pisan"` (피사 성모영보 양식)**: 3월 25일 새해 시작 (1월 1일보다 9개월 앞섬).
  - 3월 25일 ~ 12월 31일은 $Y_{	ext{doc}} = Y + 1$. (역변환 시 문서 표기 연도에서 1을 뺌).
  - 1월 1일 ~ 3월 24일은 $Y_{	ext{doc}} = Y$.
- **`"easter"` (부활절 양식, 프랑스 왕실)**: 해당 연도 부활절 일요일에 새해 시작.
  - 1월 1일 ~ 부활절 전날까지는 $Y_{	ext{doc}} = Y - 1$. (역변환 시 부활절 이전 날짜는 표기 연도에 1을 더함).
  - 부활절 일요일 ~ 12월 31일은 $Y_{	ext{doc}} = Y$.

### 2.4 율리우스 부활절 및 황금수(Computus)
- 황금수(Golden Number): $G = (Y mod 19) + 1$
- 율리우스 부활절(Meeus/Jones Julian 알고리즘):
  - $a = Y mod 4$
  - $b = Y mod 7$
  - $c = Y mod 19$
  - $d = (19c + 15) mod 30$
  - $e = (2a + 4b - d + 34) mod 7$
  - $	ext{month} = \lfloor (d + e + 114) / 31 floor$
  - $	ext{day} = ((d + e + 114) mod 31) + 1$

### 2.5 국왕 재위연(Regnal Years)
군주 즉위일이 $(AY, AM, AD)$이고 대상 날짜가 $(Y, M, D)$일 때:
- $(M, D) \ge (AM, AD)$ 이면 재위연 $R = Y - AY + 1$
- $(M, D) < (AM, AD)$ 이면 재위연 $R = Y - AY$
- 반대로 군주 즉위일 $(AY, AM, AD)$, 재위연 $R$, 날짜 $(M, D)$가 주어졌을 때 서기 연도 $Y$:
  - $(M, D) \ge (AM, AD)$ 이면 $Y = AY + R - 1$
  - $(M, D) < (AM, AD)$ 이면 $Y = AY + R$

---

## 3. 지원 모드(Modes)

### Mode 1: `"calculate_chronology"`
- **입력**: `{"mode": "calculate_chronology", "year": Y, "month": M, "day": D}`
- **출력**:
  - `julian_date`: `"YYYY-MM-DD"`
  - `day_of_week`: `"Monday" ~ "Sunday"`
  - `golden_number`: $1 \sim 19$
  - `easter_sunday`: `"YYYY-MM-DD"`
  - `indictions`: `{"byzantine": B, "bedan": Be, "roman": R, "circumcision": C}`
  - `calendar_years`: `{"circumcision": Y, "nativity": N, "florentine": F, "pisan": P, "easter": E}`

### Mode 2: `"convert_regnal_to_julian"`
- **입력**: `{"mode": "convert_regnal_to_julian", "monarch": "...", "accession_date": "YYYY-MM-DD", "regnal_year": R, "month": M, "day": D}`
- **출력**:
  - `monarch`: 문자열
  - `regnal_year`: 정수
  - `julian_date`: `"YYYY-MM-DD"`
  - `day_of_week`: `"Monday" ~ "Sunday"`
  - `indiction_roman`: 로마 양식 인딕티오 ($1 \sim 15$)

### Mode 3: `"verify_charters"`
- **입력**:
  - `monarch_registry`: 군주별 즉위일 및 서거/퇴위일 사전 `{"군주명": {"accession_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"}}`
  - `charters`: 문서 목록. 각 문서는 `charter_id`, `stated_date` 객체(표기 서기, 양식, 월, 일, 요일, 인딕티오, 기산양식, 군주, 재위연 등)를 포함.
- **판정 규칙**:
  1. 날짜 유효성 검사: 존재하지 않는 율리우스력 날짜(예: 평년 2월 29일)이면 즉시 불일치 추가 후 판정.
  2. 양식 역변환을 통해 실제 율리우스 연도 `resolved_julian_date` 산출.
  3. 요일 일치 검사 (`DAY_OF_WEEK_MISMATCH: stated ..., calculated ...`).
  4. 인딕티오 일치 검사 (`INDICTION_MISMATCH: stated ..., calculated ... (style style)`).
  5. 군주 재위 기간 검사 (`PRE_REIGN_DATE`, `POST_REIGN_DATE`, `REGNAL_YEAR_MISMATCH`).
- **상태(`status`) 판정**:
  - 불일치 건수 0건: `"AUTHENTIC"`
  - 불일치 건수 1건 (단순 필사 오류 가능성): `"SUSPICIOUS"`
  - 불일치 건수 2건 이상 또는 유효하지 않은 날짜: `"ANACHRONISTIC_FORGERY"`
