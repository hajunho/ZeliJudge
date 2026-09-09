# Sum Over Subsets (SOS) DP

### 1. 기존 방식의 한계
모든 $mask$에 대해 서브비트마스크 루프(`sub = (sub - 1) & mask`)를 돌면:
$$\sum_{k=0}^N \binom{N}{k} 2^k = (1 + 2)^N = 3^N$$
$N=16$일 때 $3^{16} \approx 4.3 \times 10^7$로 계산량이 큽니다.

### 2. SOS DP의 상태 전이
`dp[i][mask]`를 "$i$번째 이하의 비트들만 자유롭게 꺼서 만든 $mask$의 부분집합들의 합"으로 정의합니다:
$$dp[i][mask] = \begin{cases} dp[i-1][mask] & \text{if } i\text{번째 비트가 0} \\ dp[i-1][mask] + dp[i-1][mask \oplus 2^i] & \text{if } i\text{번째 비트가 1} \end{cases}$$
1차원 배열로 인플레이스 갱신이 가능하며, 총 복잡도는 **$O(N 2^N)$**으로 $N=16$일 때 $16 \times 65536 \approx 10^6$번 만에 끝납니다!
