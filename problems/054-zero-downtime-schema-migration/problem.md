# #054 배포했더니 구버전 서버와 신버전 서버가 서로 데이터를 깨먹어요?!: 하위 호환성 없는 DB 마이그레이션과 Expand-and-Contract 패턴

---

## 1. 현실 세계 비유: 비행 중인 여객기의 엔진 교체하기

승객 300명을 태우고 태평양 상공을 비행 중인 보잉 777 여객기(24시간 365일 무중단 서비스)를 상상해 보세요.

```text
❌ 무지성 파괴적 마이그레이션 (NAIVE - 공중 추락 참사):
   정비팀이 "신형 친환경 엔진이 나왔으니 즉시 교체합시다!"라며,
   비행기가 날고 있는 도중에 왼쪽 날개의 구형 엔진(컬럼 'phone')을 볼트 풀고 바다로 냅다 던져버렸습니다(DROP COLUMN).
   그러자 아직 조종실에 앉아있는 1번 부조종사(구버전 v1 파드)는
   구형 엔진 레버를 당기려다 허공을 젓고 비행기가 한쪽으로 기울어 추락합니다(500 에러 폭발!).
   새로 탄 2번 기장(신버전 v2 파드)은 신형 엔진을 켜려 하지만,
   구형 연료 탱크의 기름을 새 엔진에 공급할 파이프가 연결되지 않아 엔진이 멈춰버립니다(Null 에러 폭발!).

✅ Expand-and-Contract 패턴 (확장 및 수축의 예술):
   1. [Expand - 보조 엔진 장착]:
      비행 날개에 신형 엔진(새 컬럼 'country_code', 'national_number')을 보조로 나란히 장착합니다.
      구형 엔진은 그대로 둡니다.
   2. [Dual Write & Fallback Read - 연료 동시 공급 및 전환]:
      연료 밸브를 개조하여 기름이 들어오면 구형 엔진과 신형 엔진 양쪽에 동시에 붓습니다(Dual Write).
      조종사는 신형 엔진을 우선 가동하되, 신형에 기름이 없으면 구형 엔진을 돌립니다(Fallback Read).
   3. [Backfill - 기존 연료 순환]:
      비행 중 조용히 보조 펌프로 구형 탱크의 잔여 연료를 신형 엔진으로 옮겨 채웁니다.
   4. [Contract - 구형 엔진 안전 분리]:
      모든 조종사가 신형 엔진으로 완벽히 비행하게 된 후, 착륙 직전에 안전하게 구형 엔진을 분리합니다(DROP).
      승객들은 커피 한 방울 쏟지 않고 편안하게 목적지에 도착합니다!
```

쿠버네티스(Kubernetes)나 AWS ECS를 통해 **무중단 롤링 배포(Rolling Deployment)**를 할 때  
수많은 주니어 개발자와 AI 바이브 코더들이 저지르는 최악의 실수가 바로  
**"하위 호환성을 무시한 DB DDL 변경"**입니다.

롤링 배포가 진행되는 몇 분 동안은 **구버전 애플리케이션($v1$)과 신버전 애플리케이션($v2$)이 동일한 DB를 동시에 바라보며 요청을 처리**합니다.  
이때 DB 컬럼을 함부로 바꾸거나 삭제하면, 구버전과 신버전이 서로 500 에러를 뿜어내며 전사 서비스가 마비됩니다.

마틴 파울러(Martin Fowler)가 정립하고 글로벌 테크 기업들이 표준으로 사용하는  
**Expand-and-Contract (확장 및 수축) 패턴**을 시뮬레이션을 통해 마스터해 봅시다.

---

## 2. 문제 개요

당신은 글로벌 핀테크 서비스의 데이터베이스 아키텍트입니다.  
전화번호 단일 컬럼(`phone`, 예: `+82-01012345678`)을 국가코드와 번호(`country_code="+82"`, `national_number="01012345678"`)로 분리하는 스키마 개편을 무중단 롤링 배포 중에 진행해야 합니다.

기존의 **파괴적 마이그레이션 모델(NAIVE)**과 **Expand-and-Contract 모델(EXPAND)**을 시뮬레이션하고,  
롤링 배포 기간 동안의 500 에러 발생률과 무중단 전환 우위(`ZERO_DOWNTIME_ADVANTAGE`)를 정밀 계측하세요.

### 시뮬레이션 상세 규칙

#### 1. 공통 환경 및 데이터 포맷
- 전화번호 데이터 입력 형식: `<country_code>:<national_number>` (예: `+82:01012345678`).
- 구버전 단일 문자열 포맷: `<country_code>-<national_number>` (예: `+82-01012345678`).
- 신버전 분리 컬럼: `country_code` (예: `+82`), `national_number` (예: `01012345678`).
- `INIT_USERS <U>`: 배포 시작 전 구버전 시스템에 이미 저장되어 있던 기존 사용자 수.

#### 2. 모델 A: 파괴적 마이그레이션 (NAIVE)
배포 시작과 동시에 DDL을 실행하여 `phone` 컬럼을 삭제하고 신규 컬럼을 추가했습니다. (기존 데이터의 신규 컬럼 값은 `NULL`):
- **$V1$ 파드로 라우팅된 요청**:
  - $V1$ 코드는 무조건 `phone` 컬럼을 읽거나 쓰려고 시도합니다.
  - 하지만 DB에 `phone` 컬럼이 존재하지 않으므로 즉시 **`ERROR_SCHEMA_MISMATCH`** (500 SQL 에러)가 발생합니다.
- **$V2$ 파드로 라우팅된 요청**:
  - `WRITE`: 신규 컬럼(`country_code`, `national_number`)에 정상 기록 $\to$ `SUCCESS`.
  - `READ`: 해당 유저의 신규 컬럼을 조회합니다.
    - 유저가 존재하지 않으면 $\to$ `NOT_FOUND`.
    - 신규 컬럼이 `NULL`이면 (마이그레이션되지 않은 기존 유저) $\to$ **`ERROR_DATA_MISSING`** (500 데이터 결손 에러).
    - 신규 컬럼이 존재하면 $\to$ `SUCCESS`.

#### 3. 모델 B: Expand-and-Contract 패턴 (EXPAND)
배포 기간 동안 DB에 구버전 컬럼과 신버전 컬럼이 모두 공존하며 호환성을 유지합니다:
- **$V1$ 파드로 라우팅된 요청**:
  - `WRITE`: `phone` 컬럼에 `+82-01012345678` 기록 $\to$ `SUCCESS`.
  - `READ`: `phone` 컬럼이 존재하면 읽어서 반환 $\to$ `SUCCESS`. (없으면 `NOT_FOUND`).
- **$V2$ 파드로 라우팅된 요청**:
  - **Dual Write (동시 쓰기)**:
    - `WRITE` 시: `phone` 컬럼과 `country_code`, `national_number` 컬럼 **양쪽 모두에 동시에 기록**합니다 $\to$ `SUCCESS`.
    - 효과: 이후 $V1$ 파드가 읽든 $V2$ 파드가 읽든 양쪽 모두 최신 데이터를 완벽히 읽을 수 있습니다.
  - **Fallback Read (대체 읽기)**:
    - `READ` 시:
      1. 신규 컬럼(`country_code`, `national_number`)이 채워져 있으면 그것을 반환 $\to$ `SUCCESS`.
      2. 신규 컬럼이 비어있고 과거 `phone` 컬럼만 존재한다면, `phone` 컬럼에서 파싱하여 반환 $\to$ `SUCCESS`.
      3. 둘 다 없으면 $\to$ `NOT_FOUND`.

---

## 3. 입력 형식

```text
INIT_USERS <U>
<user_id> <phone_data>
... (총 U개의 기존 유저 줄)
EVENTS <E>
REQ <client_id> <POD: V1 | V2> <OP: READ | WRITE> <user_id> [phone_data]
... (총 E개의 롤링 배포 트래픽 줄)
```

- `phone_data`: `+82:01012345678` 형태의 문자열 (READ 요청 시에는 주어지지 않음)
- `E`: 롤링 배포 중 유입된 요청 수 ($1 \le E \le 30,000$)

---

## 4. 출력 형식

각 `REQ`마다 한 줄씩 두 모델의 처리 상태를 출력합니다:
```text
REQ <client_id> POD:<pod> OP:<op> USER:<uid> NAIVE:<n_status> EXPAND:<e_status>
```

- 상태 코드:
  - NAIVE: `SUCCESS`, `ERROR_SCHEMA_MISMATCH`, `ERROR_DATA_MISSING`, `NOT_FOUND`
  - EXPAND: `SUCCESS`, `NOT_FOUND`

모든 요청 처리 후 최종 종합 성능 통계를 출력합니다:
```text
SUMMARY TOTAL_REQS:<total>
NAIVE SUCCESS:<n_succ> ERRORS:<n_err> SUCCESS_RATE:<n_rate>%
EXPAND SUCCESS:<e_succ> ERRORS:<e_err> SUCCESS_RATE:<e_rate>%
SUMMARY ZERO_DOWNTIME_ADVANTAGE:<adv>%
```

- `ERRORS`: `ERROR_SCHEMA_MISMATCH` + `ERROR_DATA_MISSING`의 합계
- `SUCCESS_RATE`: `(SUCCESS / TOTAL_REQS) * 100.0` (소수점 둘째 자리까지 반올림, 예: `60.00%`)
- `ZERO_DOWNTIME_ADVANTAGE`: `EXPAND_SUCCESS_RATE - NAIVE_SUCCESS_RATE` (소수점 둘째 자리까지 반올림, 예: `40.00%`)

---

## 5. 입출력 예시

### 입력
```text
INIT_USERS 1
user_1 +82:01012345678
EVENTS 5
REQ C1 V1 READ user_1
REQ C2 V1 WRITE user_2 +82:01099998888
REQ C3 V2 READ user_1
REQ C4 V2 WRITE user_3 +1:4155551234
REQ C5 V1 READ user_3
```

### 출력
```text
REQ C1 POD:V1 OP:READ USER:user_1 NAIVE:ERROR_SCHEMA_MISMATCH EXPAND:SUCCESS
REQ C2 POD:V1 OP:WRITE USER:user_2 NAIVE:ERROR_SCHEMA_MISMATCH EXPAND:SUCCESS
REQ C3 POD:V2 OP:READ USER:user_1 NAIVE:ERROR_DATA_MISSING EXPAND:SUCCESS
REQ C4 POD:V2 OP:WRITE USER:user_3 NAIVE:SUCCESS EXPAND:SUCCESS
REQ C5 POD:V1 OP:READ USER:user_3 NAIVE:ERROR_SCHEMA_MISMATCH EXPAND:SUCCESS
SUMMARY TOTAL_REQS:5
NAIVE SUCCESS:1 ERRORS:4 SUCCESS_RATE:20.00%
EXPAND SUCCESS:5 ERRORS:0 SUCCESS_RATE:100.00%
SUMMARY ZERO_DOWNTIME_ADVANTAGE:80.00%
```

#### 해설
- **C1 (V1 READ user_1)**:
  - NAIVE: DDL로 `phone` 컬럼이 DROP되어 V1이 500 에러 발생.
  - EXPAND: `phone` 컬럼이 유지되어 정상 조회 성공.
- **C2 (V1 WRITE user_2)**:
  - NAIVE: V1이 `phone` 컬럼에 쓰려 하나 스키마 불일치 에러.
  - EXPAND: `phone` 컬럼에 안전하게 기록 성공.
- **C3 (V2 READ user_1)**:
  - NAIVE: V2가 신규 컬럼을 보지만 초기 데이터 마이그레이션이 안 되어 NULL 결손 에러 발생.
  - EXPAND: V2가 신규 컬럼이 없음을 감지하고 구버전 `phone` 컬럼에서 Fallback으로 읽어 성공!
- **C4, C5 (V2 WRITE 후 V1 READ user_3)**:
  - NAIVE: V2는 성공하지만, V1은 여전히 스키마 에러로 읽기 불가.
  - EXPAND: V2가 **Dual Write**로 구버전 `phone` 컬럼에도 함께 써주었기 때문에, 뒤이어 들어온 구버전 V1 파드도 완벽하게 읽기 성공!
- 결과: NAIVE는 성공률 20%로 폭망했으나, EXPAND는 500 에러 0건(성공률 100%)의 무중단 배포를 달성했습니다.
