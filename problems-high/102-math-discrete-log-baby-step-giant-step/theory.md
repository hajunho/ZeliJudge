# 거인의 보폭으로 지수를 맞춰라! 이산 로그와 아기걸음 거인걸음 (Baby-step Giant-step)

## 핵심 개념 및 알고리즘 개요
- **태그**: 수학, 정수론, 이산 로그(Discrete Logarithm), BSGS(Baby-step Giant-step), 모듈러 거듭제곱, $O(\sqrt{P})$
- **핵심 요약**: $A^x \equiv B \pmod P$를 만족하는 최소 음이 아닌 정수 $x$를 $O(\sqrt{P})$ 해시 맵 기법으로 빠르게 탐색합니다.

---

### 이산 로그(Discrete Logarithm)와 BSGS 알고리즘

소수 $P$와 서로소인 밑 $A$, 목표값 $B$에 대해 다음 합동식을 만족하는 $x$를 찾는 문제입니다:
$$A^x \equiv B \pmod P$$

오일러의 정리에 의해 $0 \le x < P - 1$ 범위에 해가 존재한다면 최소해가 있습니다.
단순 전수조사는 $O(P)$ 시간이 걸려 $P \approx 10^9$에서 시간 초과가 발생합니다.

**Baby-step Giant-step (BSGS) 원리**:
$m = \lceil \sqrt{P} \rceil$이라 두면, 임의의 $x$는 다음과 같이 유일하게 표현됩니다:
$$x = i \cdot m - j \quad (1 \le i \le m, \ 0 \le j < m)$$
이를 식에 대입하면:
$$A^{i \cdot m - j} \equiv B \pmod P \iff (A^m)^i \equiv B \cdot A^j \pmod P$$

1. **Baby-step (작은 보폭)**:
   - $j = 0, 1, \dots, m-1$에 대해 $B \cdot A^j \pmod P$의 값을 계산하여 해시 테이블 `table[val] = j`에 저장합니다. (동일한 값이 나오면 더 큰 $j$로 덮어써서 $i \cdot m - j$가 최소가 되도록 유도)
2. **Giant-step (거인의 보폭)**:
   - $base = A^m \pmod P$를 구합니다.
   - $i = 1, 2, \dots, m$에 대해 $cur = (A^m)^i \pmod P$를 순회하며 해시 테이블에 $cur$이 존재하는지 확인합니다.
   - 존재한다면 $x = i \cdot m - table[cur]$이 해가 되며, $i$를 $1$부터 증가시키므로 가장 먼저 발견되는 $x$가 최솟값이 됩니다.
- 전체 시간 복잡도는 $O(\sqrt{P} \log P)$ 또는 해시 사용 시 $O(\sqrt{P})$입니다.

---

## 복잡도 분석
- **시간 복잡도**: 본문 이론 및 구현 참조
- **공간 복잡도**: $O(N)$ 또는 $O(V + E)$

## 추천 연습 문제
- 관련 백준(BOJ) 및 Codeforces / ICPC 기출 고난도 문제
