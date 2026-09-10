# [경제학/계량경제학] 소득 불평등도와 빈곤선 측정: 지니 계수·로렌츠 곡선 및 조세·복지 재분배 시뮬레이션 엔진

## 문제 설명

현대 경제학과 공공정책학(Public Policy)에서 소득 불평등(Income Inequality)과 빈곤(Poverty)을 정밀하게 측정하고, 조세(Taxation) 및 사회보장 복지 급여(Transfers)의 재분배 효과를 계량적으로 검증하는 것은 국가 예산 편성 및 복지 정책 설계의 핵심 과제입니다.
OECD, 세계은행(World Bank), 한국은행, 통계청 가계금융복지조사는 매년 국가 단위 소득 표본 데이터를 바탕으로 시장소득(세전·복지급여 전)과 처분가능소득(세후·복지급여 후)의 불평등도를 비교 분석합니다.

기획재정부 및 한국개발연구원(KDI)의 계량경제학 분석 플랫폼의 엔지니어가 되어, 가구별 인구 가중치와 가구원 수 제곱근 척도를 적용한 **균등화 소득(Equivalised Income)**을 산출하고, **지니 계수(Gini Coefficient)**, **로렌츠 곡선 10분위수 점유율(Decile Shares)**, **팔마 비율(Palma Ratio)**, **포스터-그리어-소로베케(FGT) 빈곤 지수 3종($P_0, P_1, P_2$)**, 그리고 정부 재분배 정책의 효과를 나타내는 **레이놀즈-스몰렌스키 지수(Reynolds-Smolensky Index)**를 원스톱으로 계산하는 **소득 불평등 및 재분배 시뮬레이션 엔진**을 구현하십시오.

---

## 계량경제학 수식 및 계산 규격

### 1. 가구 균등화 소득 (Equivalised Income) 및 가중치
가구 $h$의 가구원 수가 $S_h$일 때, OECD 표준 제곱근 척도(Square Root Scale)에 따른 가구원 1인당 균등화 소득:
$$y_h = \frac{Y_h}{\sqrt{S_h}}$$
- 시장 균등화 소득: $y_h^{\text{mkt}} = \frac{\max(0, \text{market\_income}_h)}{\sqrt{S_h}}$
- 처분가능 균등화 소득: $\text{disp\_inc}_h = \max(0, \text{market\_income}_h - \text{tax}_h + \text{transfer}_h)$
  $$y_h^{\text{disp}} = \frac{\text{disp\_inc}_h}{\sqrt{S_h}}$$
- 각 가구 $h$의 인구 가중치(Weight)는 해당 가구의 가구원 수 $w_h = S_h$입니다.
- 전체 인구: $N = \sum_{h} w_h$

### 2. 가중 중위 소득 (Weighted Median) 및 상대적 빈곤선 (Poverty Line)
- 소득 데이터를 오름차순 정렬: $y_{(1)} \le y_{(2)} \le \dots \le y_{(H)}$
- 누적 인구 가중치가 전체 인구의 50%($N / 2.0$)에 최초로 도달하거나 초과하는 지점의 소득을 **중위 소득(Median Income, $M$)**으로 정의합니다.
- **상대적 빈곤선(Poverty Line, $z$)**:
  $$z = \text{poverty\_line\_ratio} \times M$$
  (기본값 $\text{poverty\_line\_ratio} = 0.5$, 즉 중위 소득의 50%).

### 3. 로렌츠 곡선 (Lorenz Curve) 및 지니 계수 (Gini Coefficient)
- 정렬된 각 데이터 포인트 $k$에 대해:
  - 누적 인구 비율: $p_k = \frac{\sum_{i=1}^k w_i}{N}$ ($p_0 = 0.0$)
  - 누적 소득 비율: $L_k = \frac{\sum_{i=1}^k w_i y_i}{\sum_{i=1}^H w_i y_i}$ ($L_0 = 0.0$)
- 로렌츠 곡선 하부 면적(Area Under Curve, AUC)은 사다리꼴 공식(Trapezoidal Rule)으로 적분합니다:
  $$\text{AUC} = \sum_{k=1}^H \frac{L_{k-1} + L_k}{2} \cdot (p_k - p_{k-1})$$
- **지니 계수 (Gini Coefficient, $G$)**:
  $$G = \max(0.0, 1.0 - 2.0 \cdot \text{AUC})$$
  (소득 합이 0이거나 완전 균등 시 $G = 0.0$, 불평등이 극대화될수록 $G \to 1.0$).

### 4. 10분위수 점유율 (Decile Shares), 팔마 비율, 5분위 배율
- 전체 인구 $N$을 10등분한 각 분위(Decile)의 인구 용량은 $N / 10.0$입니다.
- 소득 하위 10%부터 상위 10%까지 각 분위가 가져가는 총소득을 합산하여, 전체 소득 대비 비중 $D_1, D_2, \dots, D_{10}$을 소수점 넷째 자리까지 반올림합니다.
- **팔마 비율 (Palma Ratio)**:
  $$\text{Palma} = \frac{D_{10}}{\sum_{k=1}^4 D_k} = \frac{\text{소득 상위 10\% 점유율}}{\text{소득 하위 40\% 점유율 합}}$$
- **5분위 배율 (S80/S20 Quintile Share Ratio)**:
  $$\text{S80/S20} = \frac{D_9 + D_{10}}{D_1 + D_2} = \frac{\text{소득 상위 20\% 소득 합}}{\text{소득 하위 20\% 소득 합}}$$

### 5. FGT (Foster-Greer-Thorbecke) 빈곤 지수 3종
빈곤선 $z$ 미만의 소득을 가진 빈곤 인구에 대해:
$$P_\alpha = \frac{1}{N} \sum_{i: y_i < z} w_i \left(\frac{z - y_i}{z}\right)^\alpha$$
- **$P_0$ (Headcount Ratio, 빈곤율)**: 전체 인구 중 빈곤층 인구 비율 ($z$ 미만 인구 / $N$)
- **$P_1$ (Poverty Gap Ratio, 빈곤 갭)**: 빈곤선 도달에 필요한 평균 소득 결손비율 (빈곤의 깊이)
- **$P_2$ (Squared Poverty Gap, 빈곤 심도)**: 소득 결손율의 제곱 평균으로 극빈층에 가중치를 둔 지표 (빈곤의 가혹도)

### 6. 조세·재정 재분배 효과 평가 (Reynolds-Smolensky Index)
- 시장소득 세전 지니 계수: $G_{\text{pre}}$
- 처분가능소득 세후 지니 계수: $G_{\text{post}}$
- **레이놀즈-스몰렌스키 지수 (Reynolds-Smolensky Index, $RS$)**:
  $$RS = \text{round}(G_{\text{pre}} - G_{\text{post}}, 4)$$
- **지니 개선율 (Gini Reduction %)**:
  $$\Delta G(\%) = \text{round}\left(\frac{RS}{G_{\text{pre}}} \times 100, 2\right)$$
- **빈곤율 개선율 (Poverty Reduction %)**:
  $$\Delta P_0(\%) = \text{round}\left(\frac{P_{0,\text{pre}} - P_{0,\text{post}}}{P_{0,\text{pre}}} \times 100, 2\right)$$
- **정책 평가 등급 (`evaluation`)**:
  - $RS \ge 0.08$: `"SIGNIFICANT_PROGRESSIVE_REDISTRIBUTION"`
  - $0.03 \le RS < 0.08$: `"MODERATE_PROGRESSIVE_REDISTRIBUTION"`
  - $0.0 < RS < 0.03$: `"SLIGHT_PROGRESSIVE_REDISTRIBUTION"`
  - $RS == 0.0$: `"NEUTRAL_REDISTRIBUTION"`
  - $RS < 0.0$: `"REGRESSIVE_REDISTRIBUTION"`

---

## 입력 형식

표준 입력(`sys.stdin`)으로 단일 JSON 객체가 주어집니다:
```json
{
  "simulation_id": "SIM_OECD_KOREA_2024",
  "poverty_line_ratio": 0.5,
  "households": [
    {
      "id": "H1",
      "members": 1,
      "market_income": 10000000,
      "tax": 500000,
      "transfer": 4000000
    },
    {
      "id": "H2",
      "members": 2,
      "market_income": 20000000,
      "tax": 1500000,
      "transfer": 5000000
    }
  ]
}
```

---

## 출력 형식

표준 출력(`sys.stdout`)으로 계산된 결과를 JSON 문자열(단일 라인)로 출력합니다:
```json
{
  "simulation_id": "SIM_OECD_KOREA_2024",
  "total_households": 2,
  "total_population": 3,
  "pre_redistribution": {
    "median_income": 14142135.62,
    "poverty_line": 7071067.81,
    "gini": 0.1245,
    "palma_ratio": 0.3521,
    "s80_s20_ratio": 1.4521,
    "fgt_p0_headcount": 0.0,
    "fgt_p1_gap": 0.0,
    "fgt_p2_severity": 0.0,
    "decile_shares": [0.08, 0.08, ...]
  },
  "post_redistribution": {
    "median_income": 16616783.69,
    "poverty_line": 8308391.85,
    "gini": 0.0812,
    "palma_ratio": 0.2145,
    "s80_s20_ratio": 1.2105,
    "fgt_p0_headcount": 0.0,
    "fgt_p1_gap": 0.0,
    "fgt_p2_severity": 0.0,
    "decile_shares": [0.09, 0.09, ...]
  },
  "redistribution_effect": {
    "reynolds_smolensky": 0.0433,
    "gini_reduction_percent": 34.78,
    "poverty_reduction_percent": 0.0,
    "evaluation": "MODERATE_PROGRESSIVE_REDISTRIBUTION"
  }
}
```
