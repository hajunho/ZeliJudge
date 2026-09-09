# 최장 공통 부분 문자열 (Longest Common Substring) DP

### 1. 부분 수열(Subsequence) vs 부분 문자열(Substring)
- **Subsequence (LCS)**: 문자들이 건너뛰어 나타나도 인정 ($S_1[i-1] \neq S_2[j-1]$일 때 이전 최댓값 $\max(DP[i-1][j], DP[i][j-1])$ 계승).
- **Substring**: 반드시 연속되어야 함! 문자가 다르면 연속성이 끊어지므로 즉시 $DP[i][j] = 0$.

### 2. 점화식
$$DP[i][j] = \begin{cases} DP[i-1][j-1] + 1 & \text{if } S_1[i-1] == S_2[j-1] \\ 0 & \text{if } S_1[i-1] \neq S_2[j-1] \end{cases}$$
시간 복잡도는 $O(|S_1| \times |S_2|)$이며, 전체 $DP$ 테이블 중 최댓값과 그 위치를 추적하여 문자열을 슬라이싱합니다.
