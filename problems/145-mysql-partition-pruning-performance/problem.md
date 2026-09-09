# [1억 건 로그 테이블에 인덱스를 달았는데 왜 쿼리가 30초나 걸려요?!: RDBMS 테이블 파티셔닝(Range Partitioning)과 파티션 프루닝(Partition Pruning)]

## 1. 장애 시나리오: "인덱스가 50GB로 비대해져 DB가 뻗은 결제 로그 테이블과 DATE() 함수의 저주"

핀테크 결제 플랫폼의 `payment_logs`(결제 거래 로그) 테이블에 누적 데이터가 **1억 건(데이터 용량 80GB)**을 돌파했습니다.
특정 날짜의 결제 내역을 빠르게 찾기 위해 `created_at` 컬럼에 B-Tree 인덱스를 걸어두었지만, 인덱스 파일 크기만 **50GB**에 육박했습니다.
- 서버의 InnoDB 버퍼 풀(Buffer Pool) 크기는 32GB였기 때문에, 인덱스 트리 블록조차 메모리에 다 올리지 못했습니다.
- 그 결과, 날짜 조회 쿼리가 들어올 때마다 심각한 디스크 랜덤 I/O 스와핑이 발생하여 쿼리 1건에 30초가 소요되며 전사 DB가 마비되었습니다.

DBA는 테이블을 월별로 물리적으로 쪼개는 **레인지 파티셔닝(Range Partitioning)**을 도입했습니다:
```sql
ALTER TABLE payment_logs PARTITION BY RANGE (UNIX_TIMESTAMP(created_at)) (
    PARTITION p2026_01 VALUES LESS THAN (UNIX_TIMESTAMP('2026-02-01 00:00:00')),
    PARTITION p2026_02 VALUES LESS THAN (UNIX_TIMESTAMP('2026-03-01 00:00:00')),
    ...
    PARTITION p_future VALUES LESS THAN MAXVALUE
);
```

파티셔닝 후, `WHERE created_at >= '2026-08-01' AND created_at < '2026-09-01'` 쿼리는 **옵티마이저가 12개 파티션 중 오직 `p2026_08` 파티션 1개만 물리적으로 열어보는 파티션 프루닝(Partition Pruning)** 덕분에 실행 시간이 30초에서 0.05초로 600배 빨라졌습니다!

하지만 며칠 뒤, 새로운 개발자가 작성한 정산 배치 쿼리가 돌자마자 **다시 DB가 30초 동안 멈추는 대형 참사**가 터졌습니다:
```sql
-- 대참사를 유발한 쿼리:
SELECT * FROM payment_logs WHERE DATE(created_at) = '2026-08-15';
```

이유는 무엇이었을까요?
컬럼에 `DATE()` 가공 함수를 씌우는 순간, 옵티마이저는 쿼리 컴파일 시점에 파티션 경계값을 계산할 수 없게 되어 **파티션 프루닝이 완전히 무력화(Pruning Failure)**되고, **전체 12개 파티션을 모조리 풀 스캔(Full Scan Across All Partitions)**해 버렸기 때문입니다!

---

## 2. 시뮬레이션 사양 및 규칙

본 문제에서는 관계형 데이터베이스(MySQL / Oracle)의 **레인지 파티셔닝(Range Partitioning)** 구조 하에서 다양한 형태의 쿼리가 들어왔을 때 **파티션 프루닝(Partition Pruning)**이 정상 동작하는지, 스캔되는 파티션과 절감되는 레코드 수를 시뮬레이션합니다.

### (1) 파티션 구조 정의
- $P$개의 연속적인 정수 범위 파티션이 주어집니다.
- 각 파티션은 `[low, high)` 구간을 담당하며, 해당 파티션에 저장된 행 수 `row_count`를 갖습니다. (`high`가 `INF`인 경우 무한대 $10^9$로 취급)
- 파티션 간의 구간은 서로 겹치지 않습니다.
- 전체 테이블 레코드 수 $TotalRows = \sum row\_count$

### (2) 쿼리 조건 유형과 프루닝 판정
1. **`POINT <val>` (단일 점 조회)**:
   - 파티션 키 컬럼에 대한 단순 동등 비교 (`val = X`).
   - `val`이 속하는 단 1개의 파티션만 물리적으로 접근합니다 ($low \le val < high$).
   - `PRUNED += 1`
2. **`RANGE <low> <high>` (범위 조회)**:
   - 파티션 키 컬럼에 대한 SARGable 범위 조건 (`val >= low AND val < high`).
   - 쿼리 구간과 겹치는(Overlap) 파티션들만 물리적으로 접근합니다:
     $$\max(p.low, q.low) < \min(p.high, q.high)$$
   - `PRUNED += 1`
3. **`FUNCTION_EXPRESSION <low> <high>` (함수 가공 쿼리)**:
   - 파티션 키에 함수나 연산식이 적용된 경우 (예: `WHERE DATE(col) = ...`).
   - **파티션 프루닝 실패!** 옵티마이저는 모든 파티션($P$개 전체)을 스캔해야 합니다.
   - `FAILED += 1`
4. **`NO_PARTITION_KEY` (파티션 키 미지정 쿼리)**:
   - 조건절에 파티션 키 컬럼이 전혀 포함되지 않은 경우 (예: `WHERE status = 'PAID'`).
   - **파티션 프루닝 실패!** 모든 파티션($P$개 전체)을 스캔해야 합니다.
   - `FAILED += 1`

### (3) 통계 집계
- `TOTAL_QUERIES`: 처리한 총 쿼리 수
- `PRUNED`: 프루닝이 성공적으로 적용된 쿼리 수 (POINT, RANGE)
- `FAILED`: 프루닝에 실패하여 전체 파티션을 스캔한 쿼리 수 (FUNCTION_EXPRESSION, NO_PARTITION_KEY)
- `SCANNED_ROWS`: 쿼리들이 실제로 접근하여 읽어 들인 총 행 수 누적
- `SAVED_ROWS`: 프루닝 덕분에 읽지 않고 건너뛴(절감된) 총 행 수 누적 ($TotalRows - ScannedRows$)

---

## 3. 입력 형식

- 첫째 줄에 파티션 개수 $P$ ($1 \le P \le 100$)가 주어집니다.
- 둘째 줄부터 $P$개 줄에 걸쳐 각 파티션의 정보가 공백으로 구분되어 주어집니다:
  - `p_name low high row_count` (단, $high$가 `INF`이면 $10^9$로 처리)
- 다음 줄에 쿼리 개수 $Q$ ($1 \le Q \le 1,000$)가 주어집니다.
- 다음 $Q$개 줄에 걸쳐 각 쿼리가 주어집니다:
  - `POINT <val>`
  - `RANGE <low> <high>`
  - `FUNCTION_EXPRESSION <low> <high>`
  - `NO_PARTITION_KEY`

## 4. 출력 형식

- 모든 쿼리를 처리한 후 다음 형식으로 한 줄에 출력합니다:
  - `TOTAL_QUERIES: <n> PRUNED: <n> FAILED: <n> SCANNED_ROWS: <n> SAVED_ROWS: <n>`

---

## 5. 입출력 예제

### 예제 1
#### 입력
```text
4
p0 0 1000 10000
p1 1000 2000 20000
p2 2000 3000 30000
p3 3000 INF 40000
4
POINT 500
RANGE 1500 2500
FUNCTION_EXPRESSION 1500 2500
NO_PARTITION_KEY
```
#### 출력
```text
TOTAL_QUERIES: 4 PRUNED: 2 FAILED: 2 SCANNED_ROWS: 260000 SAVED_ROWS: 140000
```
**설명**:
- 총 행 수: 10,000 + 20,000 + 30,000 + 40,000 = 100,000건.
- `POINT 500`: p0만 스캔 (10,000건 스캔, 90,000건 절감).
- `RANGE 1500 2500`: p1과 p2 스캔 (20,000 + 30,000 = 50,000건 스캔, 50,000건 절감).
- `FUNCTION_EXPRESSION`: 함수 가공으로 프루닝 실패 $	o$ 전 파티션 스캔 (100,000건 스캔, 0건 절감).
- `NO_PARTITION_KEY`: 파티션 키 미포함으로 프루닝 실패 $	o$ 전 파티션 스캔 (100,000건 스캔, 0건 절감).
- 총 스캔 행 수 = 260,000건, 총 절감 행 수 = 140,000건.
