# Problem 068: 분산 시스템의 타임존(Timezone) 혼란과 ISO-8601 UTC 단일 원천 원칙 (Timezone Chaos & UTC Single Source of Truth)

## 문제 설명

글로벌 서비스를 운영하는 전자상거래 핀테크 팀에서 배포 직후 고객 불만과 회계 마비 사태가 터졌습니다:
> "분명히 개발용 로컬 맥북에서는 결제 시간도 잘 나오고 환불 기한도 완벽했는데, AWS EKS 클라우드에 Docker 리눅스 컨테이너로 배포하자마자 주문 시각이 9시간 전으로 찍힙니다!  
> 게다가 한국 고객이 밤 11시 30분에 결제했는데 어제 날짜로 정산되어 일일 매출 장부가 수억 원 어긋났고, '24시간 이내 무료 취소' 버튼은 15시간 만에 만료되었다고 사라져 소비자 고발이 폭주하고 있습니다!"

원인은 데이터베이스와 마이크로서비스 간에 타임존 오프셋(Timezone Offset)을 무시하고 로컬 시간 문자열을 나이브(Naive)하게 다룬 **Timezone Chaos 안티패턴**이었습니다:
- **도커 컨테이너의 시간 오인**: 개발자 PC는 `KST (UTC+09:00)`이지만, 리눅스 베이스 이미지는 기본 시스템 타임존이 `UTC (+00:00)`로 설정되어 있어 `datetime.now()`를 찍었을 때 9시간 전 시간이 저장되었습니다.
- **문자열 단순 비교의 함정**: 결제 시각(`2026-09-09T23:30:00 KST`)과 미국 동부 검증 서버의 현재 시각(`2026-09-10T11:00:00 EDT`)을 타임존 고려 없이 문자열 시간차로 단순 뺄셈했더니, 실제로는 24.5시간이 지나 만료되었는데도 11.5시간밖에 안 지난 것으로 오판하거나, 반대로 9시간밖에 안 지났는데 26시간 지난 것으로 판정하는 대혼란이 발생했습니다.
- **일 마감 정산 누락**: 재무팀의 일일 마감 배치가 날짜 앞 10자리(`YYYY-MM-DD`)만 보고 필터링하는 바람에, 한국 본사 기준 9월 9일 매출이 미국 지사 서버나 UTC DB에서는 다른 날짜로 흩어져 버렸습니다.

런던 시간으로 인쇄된 항공권을 들고 서울 인천공항에 간 승객이 비행기를 놓치지 않으려면 전 세계 항공 관제망처럼 **협정 세계시(UTC)를 단일 원천(Single Source of Truth)**으로 삼아야 합니다:
1. **내부 저장과 통신은 100% UTC(또는 Unix Epoch Seconds)**로만 유지합니다.
2. **타임존 변환은 시스템의 가장 바깥 경계선(Presentation Layer)**에서 사용자 화면에 보여줄 때만 수행합니다.
3. **일일 정산 등 기간 쿼리는 특정 타임존의 시작과 끝을 UTC 절대 시간 범위로 변환**하여 조회합니다.

당신은 동일한 결제 스트림에 대해 레거시 **Naive Time 엔진**과 **UTC Standard 엔진**의 시간 처리, 만료 판정, 일일 정산 차액(Discrepancy)을 비교 시뮬레이션하는 글로벌 시간 엔지니어링 엔진을 작성해야 합니다.

---

## 시스템 요구사항 및 동작 규칙

### 1. 전역 설정
- `TIMEZONES`: 각 타임존 코드와 UTC 오프셋 (`+HH:MM`, `-HH:MM`, `+00:00`, `Z`).
  - 예: `KST +09:00`, `EDT -04:00`, `UTC +00:00`, `IST +05:30`
- `SERVER_CONFIG`:
  - `NAIVE_SERVER_TZ <tz_code>`: 레거시 나이브 서버가 가정하는 기본 시스템 타임존 (예: `UTC`).

---

### 2. 두 가지 시간 아키텍처

#### 1) Naive Time Architecture (안티패턴)
- **저장**: 클라이언트 타임존 오프셋을 제거하고 입력된 문자열 그대로(`YYYY-MM-DDTHH:MM:SS`) 저장.
- **표출**: 저장된 나이브 문자열을 타임존 변환 없이 그대로 반환.
- **만료 판정**: 검사 시점의 로컬 시간 문자열과 저장된 문자열 간의 단순 시간차(`(curr - stored).total_seconds() / 3600.0`)로 판정.
- **일일 정산**: 저장된 문자열의 앞 10자리(`YYYY-MM-DD`)가 정산 대상 날짜와 일치하는 레코드 단순 합산.

#### 2) UTC Standard Architecture (모범 설계)
- **저장**: 클라이언트 타임존 오프셋을 반영하여 **UTC 에포크 초(Epoch Seconds)** 및 **ISO-8601 UTC 문자열(`YYYY-MM-DDTHH:MM:SSZ`)**로 정규화하여 저장.
  $$\text{Epoch}_{\text{UTC}} = \text{LocalEpoch} - \text{OffsetSeconds}$$
- **표출**: 저장된 UTC 에포크 초에 요청자의 `TARGET_TZ` 오프셋을 가산하여 `YYYY-MM-DDTHH:MM:SS+HH:MM` 포맷으로 변환.
- **만료 판정**: 검사 시각을 UTC 에포크 초로 변환한 뒤 결제 시의 UTC 에포크 초와의 절대 경과 시간(`(curr_utc - stored_utc) / 3600.0`)으로 정확히 판정.
- **일일 정산**: `business_tz` 기준 대상 날짜의 하루(`00:00:00` ~ `23:59:59`)를 UTC 에포크 구간 `[start_utc, end_utc]`로 변환하여 그 사이에 속한 결제 건수와 금액 합계 산출.

---

### 3. 4대 액션 명세

#### 1) `CREATE_PAYMENT <pay_id> <amount> <local_iso> <client_tz>`
- 결제 등록 이벤트.
- 출력 (3줄):
  ```text
  ACT <idx> CREATE_PAYMENT <pay_id>
    NAIVE_STORED: <local_iso> (ASSUMED_TZ:<naive_server_tz>)
    UTC_STORED: <utc_iso_str> (EPOCH:<epoch_sec>)
  ```

#### 2) `DISPLAY_PAYMENT <pay_id> <target_tz>`
- 결제 내역 조회 이벤트.
- 출력 (3줄):
  ```text
  ACT <idx> DISPLAY_PAYMENT <pay_id> TARGET_TZ:<target_tz>
    NAIVE_DISPLAY: <naive_raw_str>
    UTC_DISPLAY: <formatted_target_iso_str>
  ```

#### 3) `CHECK_EXPIRATION <pay_id> <current_iso> <check_tz> <valid_hours>`
- 결제 취소/환불 유효기간 검증 이벤트. 경과 시간이 `valid_hours` 이하이면 `VALID`, 초과하면 `EXPIRED`.
- 출력 (3줄):
  ```text
  ACT <idx> CHECK_EXPIRATION <pay_id> LIMIT:<valid_hours>h CHECK_TZ:<check_tz>
    NAIVE: ELAPSED:<naive_hours:.2f>h STATUS:<naive_status>
    UTC: ELAPSED:<exact_hours:.2f>h STATUS:<exact_status>
  ```
  - 단, `valid_hours`가 정수이면 정수 형태(예: `24h`)로 출력.

#### 4) `SETTLE_DAILY_SALES <target_date> <business_tz>`
- 특정 비즈니스 타임존 기준 일일 매출 정산.
- `DISCREPANCY`: `|naive_sum - utc_sum|` (절대 오차 금액).
- 출력 (3줄):
  ```text
  ACT <idx> SETTLE_DAILY_SALES DATE:<target_date> BIZ_TZ:<business_tz>
    NAIVE: COUNT:<naive_cnt> TOTAL:<naive_sum>
    UTC: COUNT:<utc_cnt> TOTAL:<utc_sum> DISCREPANCY:<diff>
  ```

---

## 입력 형식

```text
TIMEZONES
<tz_name> <offset_str>
...
SERVER_CONFIG
NAIVE_SERVER_TZ <tz_name>
ACTIONS
<action_cmd> <args...>
...
```

---

## 출력 형식

1. 각 액션별 출력 (위의 액션 명세 참조)
2. 모든 액션 종료 후 최종 통계 요약 (4줄):
```text
SUMMARY TOTAL_PAYMENTS_PROCESSED:<total_payments>
SUMMARY EXPIRATION_CHECKS:<cnt> NAIVE_ERRORS:<cnt> (MISJUDGMENT_RATE:<err_rate:.2f>%)
SUMMARY SETTLEMENTS:<cnt> TOTAL_DISCREPANCY_AMOUNT:<total_diff>
SUMMARY UTC_CONSISTENCY: 100% AUDIT_READY
```

---

## 입출력 예시

### 예시 1

**입력:**
```text
TIMEZONES
UTC +00:00
KST +09:00
EDT -04:00
SERVER_CONFIG
NAIVE_SERVER_TZ UTC
ACTIONS
CREATE_PAYMENT PAY-101 50000 2026-09-09T23:30:00 KST
CREATE_PAYMENT PAY-102 80000 2026-09-09T21:00:00 EDT
DISPLAY_PAYMENT PAY-101 EDT
DISPLAY_PAYMENT PAY-102 KST
CHECK_EXPIRATION PAY-101 2026-09-10T11:00:00 EDT 24
CHECK_EXPIRATION PAY-102 2026-09-10T23:00:00 KST 24
SETTLE_DAILY_SALES 2026-09-09 KST
SETTLE_DAILY_SALES 2026-09-09 EDT
```

**출력:**
```text
ACT 1 CREATE_PAYMENT PAY-101
  NAIVE_STORED: 2026-09-09T23:30:00 (ASSUMED_TZ:UTC)
  UTC_STORED: 2026-09-09T14:30:00Z (EPOCH:1788964200)
ACT 2 CREATE_PAYMENT PAY-102
  NAIVE_STORED: 2026-09-09T21:00:00 (ASSUMED_TZ:UTC)
  UTC_STORED: 2026-09-10T01:00:00Z (EPOCH:1789002000)
ACT 3 DISPLAY_PAYMENT PAY-101 TARGET_TZ:EDT
  NAIVE_DISPLAY: 2026-09-09T23:30:00
  UTC_DISPLAY: 2026-09-09T10:30:00-04:00
ACT 4 DISPLAY_PAYMENT PAY-102 TARGET_TZ:KST
  NAIVE_DISPLAY: 2026-09-09T21:00:00
  UTC_DISPLAY: 2026-09-10T10:00:00+09:00
ACT 5 CHECK_EXPIRATION PAY-101 LIMIT:24h CHECK_TZ:EDT
  NAIVE: ELAPSED:11.50h STATUS:VALID
  UTC: ELAPSED:24.50h STATUS:EXPIRED
ACT 6 CHECK_EXPIRATION PAY-102 LIMIT:24h CHECK_TZ:KST
  NAIVE: ELAPSED:26.00h STATUS:EXPIRED
  UTC: ELAPSED:22.00h STATUS:VALID
ACT 7 SETTLE_DAILY_SALES DATE:2026-09-09 BIZ_TZ:KST
  NAIVE: COUNT:2 TOTAL:130000
  UTC: COUNT:1 TOTAL:50000 DISCREPANCY:80000
ACT 8 SETTLE_DAILY_SALES DATE:2026-09-09 BIZ_TZ:EDT
  NAIVE: COUNT:2 TOTAL:130000
  UTC: COUNT:2 TOTAL:130000 DISCREPANCY:0
SUMMARY TOTAL_PAYMENTS_PROCESSED:2
SUMMARY EXPIRATION_CHECKS:2 NAIVE_ERRORS:2 (MISJUDGMENT_RATE:100.00%)
SUMMARY SETTLEMENTS:2 TOTAL_DISCREPANCY_AMOUNT:80000
SUMMARY UTC_CONSISTENCY: 100% AUDIT_READY
```
