# 희소 배열 (Sparse Table)과 $O(1)$ RMQ

### 1. 2의 거듭제곱 길이의 전처리 ($O(N \log N)$)
`ST[k][i]`는 $i$번째 원소부터 시작하는 길이 $2^k$인 구간의 최솟값을 저장합니다:
$$ST[k][i] = \min(ST[k-1][i], ST[k-1][i + 2^{k-1}])$$

### 2. $O(1)$ 질의와 멱등성 (Idempotency)
길이 $len = R - L + 1$에 대해 $2^k \le len < 2^{k+1}$을 만족하는 $k = \lfloor \log_2(len) \rfloor$를 잡습니다.
구간 $[L, L + 2^k - 1]$과 $[R - 2^k + 1, R]$은 서로 겹칠 수 있지만, $\min$ 연산은 중복 원소가 몇 번 포함되든 결과가 달라지지 않습니다!
$$\min_{L \le i \le R} A_i = \min\Big(ST[k][L], ST[k][R - 2^k + 1]\Big)$$
따라서 단 2번의 테이블 조회만으로 $O(1)$에 질의가 끝납니다.
