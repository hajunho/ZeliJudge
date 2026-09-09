# 이론 및 해설: 법들이 서로소가 아니어도 해를 찾아라! 일반화된 CRT (General CRT)

### 일반화된 중국인의 나머지 정리 (General Chinese Remainder Theorem)

연립 합동식
$$x \equiv r_1 \pmod{m_1}, \quad x \equiv r_2 \pmod{m_2}, \quad \dots, \quad x \equiv r_k \pmod{m_k}$$
에서 법 $m_i$들이 서로소가 아닌 경우의 최소 비음수 정수해를 구하는 알고리즘입니다.

1. **두 합동식의 병합**:
   - $x \equiv r_1 \pmod{m_1} \implies x = m_1 p + r_1$
   - 이를 두 번째 식에 대입: $m_1 p \equiv r_2 - r_1 \pmod{m_2}$
   - $g = \gcd(m_1, m_2)$일 때, $(r_2 - r_1)$이 $g$로 나누어떨어지지 않으면 **해가 존재하지 않습니다**.
   - 나누어떨어진다면 확장 유클리드로 $p$를 구하고, 새로운 합동식
     $$x \equiv r' \pmod{\text{lcm}(m_1, m_2)}$$
     으로 두 식을 하나의 동치 합동식으로 병합합니다.
2. **반복 적용**:
   - 총 $k$개의 식을 순차적으로 1개로 합치며, 최종 $x \bmod \text{lcm}(m_1, \dots, m_k)$를 반환합니다.
