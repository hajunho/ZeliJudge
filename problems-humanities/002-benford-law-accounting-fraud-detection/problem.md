# #002 [숫자는 거짓말을 하지 않는다: 벤포드의 법칙과 카이제곱($\chi^2$) 적합도 검정을 이용한 분식회계·부정 거래 탐지기 (Benford's Law Accounting Fraud Detection & Chi-Square Goodness-of-Fit Test)]

## 1. 장애 및 실무 시나리오

금융감독원 회계감리국 및 대형 회계법인 포렌식 감사팀(Forensic Audit Team)은 최근 익명의 내부고발자로부터 모 상장 그룹 계열사들의 대규모 **허위 세금계산서 발행 및 비자금 조성(Kickback), 분식회계(Accounting Fraud)** 의혹 제보를 접수했습니다.

제보에 따르면 피감 기업들은 다음과 같은 수법으로 회계 장부를 조작했습니다:
1. **임의 난수 조작**: 경리 담당자가 감사 추적을 피하기 위해 엑셀의 `RANDBETWEEN()` 함수를 이용해 수백 건의 소액 경비 전표를 임의로 생성함.
2. **결재 전결 규정 회피(Threshold Evasion)**: 500만 원 이상 결재 시 이사회 또는 대표이사 결재가 필수인 규정을 피하기 위해, 480만 원~499만 원 대의 쪼개기 전표(첫 자리 숫자 '4')를 대량으로 위조함.
3. **특정 리베이트 거래선 집중**: 비자금 조성용 페이퍼컴퍼니로 75만 원, 77만 원 등 특정 금액대(첫 자리 숫자 '7')의 자금을 주기적으로 송금함.

수십만 건에 달하는 거래 전표를 회계사가 일일이 수작업으로 검증하는 것은 불가능합니다. 하지만 인간의 뇌는 "진짜 자연스러운 숫자"를 흉내 낼 수 없습니다. 자연스럽게 발생하는 수많은 거래 데이터는 균등 분포(Uniform Distribution)가 아니라, 첫째 자리 숫자가 $1$부터 $9$까지 기하급수적으로 감소하는 **벤포드의 법칙(Benford's Law)**을 따르기 때문입니다.

감사팀은 대규모 원장(General Ledger) 데이터를 실시간으로 파싱하여, 첫 자리 숫자의 출현 빈도를 분석하고 **피어슨 카이제곱($\chi^2$) 적합도 검정(Goodness-of-Fit Test)**과 **평균 절대 편차(MAD, Mean Absolute Deviation)**를 수행해 분식회계 및 조작 장부를 즉각 적발하는 전산 감사 알고리즘을 구축하고자 합니다.

---

## 2. 경제학·통계학 이론: 벤포드의 법칙과 카이제곱 적합도 검정

### 2.1 벤포드의 법칙 (Benford's Law / First-Digit Law)
여러 자릿수(Order of Magnitude)에 걸쳐 자유롭게 형성되는 회계 거래액, 인구수, 주가, 하천 면적 등 자연적 수치 데이터의 **유효 첫 자리 숫자(Leading Non-zero Digit) $d \in \{1, 2, \dots, 9\}$**의 출현 확률 $P(d)$는 다음과 같이 로그 스케일로 정의됩니다:

$$P(d) = \log_{10}\left(1 + \frac{1}{d}\right)$$

```
+-------+-------------------+---------------------------------------------+
| 숫자 d | 이론적 확률 P(d)   | 직관적 의미                                  |
+-------+-------------------+---------------------------------------------+
|   1   |   30.10% (0.3010) | 가장 흔함. 자연 상태 거래의 약 1/3이 1로 시작 |
|   2   |   17.61% (0.1761) | 두 번째로 흔함                              |
|   3   |   12.49% (0.1249) | 점진적 감소                                 |
|   4   |    9.69% (0.0969) |                                             |
|   5   |    7.92% (0.0792) |                                             |
|   6   |    6.70% (0.0670) |                                             |
|   7   |    5.80% (0.0580) |                                             |
|   8   |    5.12% (0.0512) |                                             |
|   9   |    4.58% (0.0458) | 가장 드묾. 1에 비해 약 1/6 미만의 빈도       |
+-------+-------------------+---------------------------------------------+
```

### 2.2 피어슨 카이제곱($\chi^2$) 적합도 검정 (Goodness-of-Fit Test)
표본 크기 $N$개 중 각 숫자 $d$가 관측된 횟수를 $O_d$, 이론적 기대 빈도를 $E_d = N \times P(d)$라 할 때, 카이제곱 통계량 $\chi^2$는 다음과 같습니다:

$$\chi^2 = \sum_{d=1}^{9} \frac{(O_d - E_d)^2}{E_d}$$

자유도는 카테고리 수 9개에서 1을 뺀 **$df = 9 - 1 = 8$**입니다:
- 유의수준 $\alpha = 0.05$: 임계값 $\chi^2_{0.05, 8} = 15.507$
- 유의수준 $\alpha = 0.01$: 임계값 $\chi^2_{0.01, 8} = 20.090$

만약 계산된 $\chi^2 > \chi^2_{crit}$라면, "해당 거래 내역이 자연스러운 회계 데이터 분포를 따른다"는 귀무가설($H_0$)을 기각하고 **조작 및 이상 징후**로 판정합니다.

### 2.3 평균 절대 편차 (MAD, Mean Absolute Deviation)
표본 크기가 지나치게 커질 경우 미세한 편차에도 $\chi^2$가 과대평가되는 경향을 보완하기 위해 포렌식 감사 표준 지표인 MAD를 함께 산출합니다:

$$\text{MAD} = \frac{1}{9} \sum_{d=1}^{9} \left| \frac{O_d}{N} - P(d) \right|$$

---

## 3. 입력 사양 (Input Specification)

표준 입력(stdin)으로 하나의 JSON 객체가 주어집니다:

```json
{
  "company_name": "Acme Retail Co.",
  "significance_level": 0.05,
  "transactions": [
    { "tx_id": "tx-001", "amount": 125000.0 },
    { "tx_id": "tx-002", "amount": 48200.0 },
    { "tx_id": "tx-003", "amount": 0.0 },
    { "tx_id": "tx-004", "amount": -15000.0 }
  ]
}
```

### 처리 조건 및 데이터 정제:
1. **유효 거래 필터링**:
   - `amount`가 숫자(정수 또는 실수)이며 **양수($amount > 0$)인 거래만** 분석 대상 표본으로 삼습니다.
   - 0원 거래, 환불/취소 등 음수 거래는 분석에서 완전히 제외합니다.
2. **최소 표본 수 ($N < 50$)**:
   - 정제된 유효 거래 건수 $N < 50$이면 통계적 신뢰도가 부족하므로 즉시 `"INSUFFICIENT_DATA_SAMPLE"` 상태를 반환합니다.
3. **첫 자리 숫자 추출**:
   - 금액의 유효 숫자 중 0이 아닌 첫 번째 숫자($1 \sim 9$)를 추출합니다 (예: `125000` $\rightarrow$ `1`, `0.045` $\rightarrow$ `4`).
4. **유의수준 (significance_level)**:
   - `0.01`이 주어지면 임계값 `20.090`, 그 외(기본값 `0.05`)는 `15.507`을 적용합니다.

---

## 4. 출력 사양 (Output Specification)

표준 출력(stdout)으로 다음 스키마의 JSON을 한 줄로 출력합니다:

```json
{
  "status": "GENUINE_BENFORD_COMPLIANT",
  "company_name": "Acme Retail Co.",
  "sample_size": 601,
  "chi_square_stat": 0.018,
  "critical_value": 15.507,
  "mad_score": 0.0006,
  "digit_distributions": {
    "1": {
      "observed_count": 181,
      "expected_count": 180.9,
      "observed_ratio": 0.3012,
      "expected_ratio": 0.3010,
      "deviation": 0.0002
    }
  },
  "diagnostics": [
    "Transaction amounts conform strictly to Benford's Law (Chi-square: 0.018 <= 15.507, MAD: 0.0006). Natural business scale confirmed."
  ],
  "recommendation": "Standard audit clearance granted."
}
```

### 판정 상태 (`status`):
1. `"INSUFFICIENT_DATA_SAMPLE"`:
   - 유효 표본 수 $N < 50$인 경우.
2. `"FABRICATED_UNIFORM_RANDOM_NUMBERS"`:
   - $\chi^2 > \chi^2_{crit}$이고, 모든 숫자($1 \sim 9$)의 관측 비율이 $1/9 \approx 0.1111$과 차이가 $0.03$ 이내($|O_d/N - 1/9| < 0.03$)인 경우. 사람이 인위적으로 난수를 균등하게 꾸며냈음을 입증.
3. `"SUSPICIOUS_ACCOUNTING_ANOMALY"`:
   - $\chi^2 > \chi^2_{crit}$이며 균등 분포가 아닌 특정 자릿수 조작(전결 규정 회피, 리베이트 전표 집중 등)이 발생한 경우.
4. `"GENUINE_BENFORD_COMPLIANT"`:
   - $\chi^2 \le \chi^2_{crit}$인 정상적인 자연 회계 전표.
