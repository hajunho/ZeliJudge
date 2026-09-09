# 동전 교환 DP: 순열(Permutation) vs 조합(Combination)

### 1. 바깥 루프의 위치가 결과를 결정한다!
DP에서 루프의 순서는 **순서를 고려하느냐(순열), 구성만 보느냐(조합)**를 완전히 가르는 마법의 열쇠입니다:

1. **조합 (Combination: 동전 바깥, 금액 안쪽)**:
   ```python
   for c in coins:
       for x in range(c, K + 1):
           dp[x] = (dp[x] + dp[x - c]) % MOD
   ```
   동전을 하나씩 차례대로 소진하므로, 이전에 쓴 동전보다 앞선 동전을 다시 쓰지 않아 **순서가 고정된 순수한 조합**만 카운트됩니다!

2. **순열 (Permutation: 금액 바깥, 동전 안쪽)**:
   ```python
   for x in range(1, K + 1):
       for c in coins:
           if x >= c: dp[x] += dp[x - c]
   ```
   이러면 (1, 2)와 (2, 1)이 서로 다른 경우로 세어집니다.

---

### 2. 시간 및 공간 복잡도
- **시간 복잡도**: $O(N \times K)$ (단 $100 \times 10,000 = 100$만 번 연산)
- **공간 복잡도**: $O(K)$ 1차원 배열로 완벽 압축
