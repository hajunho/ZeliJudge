# 이론 및 해설: 거대한 조합도 소수 진법으로 정복하라! 뤼카의 정리 (Lucas' Theorem)

### 뤼카의 정리 (Lucas' Theorem)

소수 $P$에 대해, 음이 아닌 두 정수 $N, K$를 $P$진법으로 전개했을 때
$$N = n_k P^k + \dots + n_0, \quad K = k_k P^k + \dots + k_0$$
이면, 다음 합동식이 성립합니다:
$$\binom{N}{K} \equiv \prod_{i=0}^k \binom{n_i}{k_i} \pmod P$$
(단, $n_i < k_i$이면 $\binom{n_i}{k_i} = 0$)
