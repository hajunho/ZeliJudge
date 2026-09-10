# 르네상스 기호학과 다중 치환 암호 분석의 정보 이론 (Renaissance Semiotics and Information Theory of Polyalphabetic Cryptanalysis)

## 1. 기호학(Semiotics)과 암호학: 의미의 보존과 인위적 은폐

기호학(Semiotics)은 기호(Signifier, 능동표상)와 기의(Signified, 수동의미)의 결합 관계를 탐구합니다. 자연어는 알파벳 26자의 빈도 불균형(예: 영어의 E는 12.7%, Z는 0.07%)이라는 내재적 통계 법칙을 지닙니다.

단일 치환 암호는 기호의 형태만 1:1로 바꾸었을 뿐(예: E $\to$ X), 빈도의 엔트로피 구조를 전혀 교란하지 못했기 때문에 알 킨디의 빈도 분석법에 의해 즉시 해독되었습니다. 레온 바티스타 알베르티(1467)가 창안한 다중 치환 암호는 **"단일 기호의 다의적 변조(Poly-symbolic transformation)"**를 통해 텍스트의 표면 빈도 분포를 인위적인 최대 엔트로피(Uniform Distribution) 상태로 위장한 최초의 시도였습니다.

---

## 2. 윌리엄 프리드먼의 일치지수(Index of Coincidence) 수학

1922년 윌리엄 F. 프리드먼은 텍스트의 확률적 일치도인 **일치지수(Index of Coincidence, $IC$)**를 수학적으로 정의했습니다. 길이 $N$의 텍스트에서 각 문자 $c$의 빈도를 $f_c$라 할 때:

$$IC = \frac{\sum_{c=A}^Z f_c (f_c - 1)}{N (N - 1)}$$

- **단일 언어(English Monoalphabetic)**:
  $$IC_{\text{mono}} = \sum_{c=A}^Z p_c^2 \approx 0.0667$$
- **완전 무작위 균등 분포(Uniform Random)**:
  $$IC_{\text{random}} = \sum_{c=A}^Z \left(\frac{1}{26}\right)^2 = \frac{1}{26} \approx 0.0385$$

다중 치환 암호문 전체의 $IC$는 $0.0385$ 부근으로 낮아지지만, 참된 키 길이 $L$로 텍스트를 슬라이싱하면 각 슬라이스 $S_k$는 단일 카이사르 암호로 환원되므로 슬라이스별 평균 $IC$가 $0.0667$로 급격히 도약합니다.

---

## 3. 카시스키 시험(Kasiski Examination)과 주기성 추출

카시스키는 반복되는 평문 $W$가 키 $K$의 주기 $L$의 배수 간격($k \cdot L$)에 위치할 때마다 정확히 동일한 암호문 조각으로 암호화된다는 사실을 증명했습니다:

$$\Delta d_i = |pos_{i, 2} - pos_{i, 1}| = q_i \cdot L$$

따라서 모든 반복 문자열 간격들의 최대공약수(GCD) 집합을 구하면 키 길이 $L$이 높은 확률로 최다 빈도 약수로 부상합니다. 현대 암호 분석 엔진은 카시스키 시험으로 후보 키 길이 집합을 도출하고, 프리드먼 일치지수로 확정한 뒤, 카이제곱 통계량으로 각 문자를 결정하는 3단계 파이프라인을 구축합니다.
