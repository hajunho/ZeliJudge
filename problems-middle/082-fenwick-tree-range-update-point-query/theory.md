# 차분 배열과 펜윅 트리의 결합 (Range Update Point Query)

### 1. 차분 배열(Difference Array)의 기적
구간 $[L, R]$의 모든 원소에 $v$를 더하는 연산은, 차분 배열 $D_k = A_k - A_{k-1}$ 관점에서는:
- $D_L \leftarrow D_L + v$
- $D_{R+1} \leftarrow D_{R+1} - v$
단 두 지점의 값만 변경하는 연산으로 변환됩니다!

### 2. 점 질의(Point Query)의 복원
차분 배열의 정의에 의해, 임의의 위치 $i$의 원소 값은:
$$A_i = A_i^{(초기)} + \sum_{k=1}^i D_k$$
즉, 차분 배열의 누적 합을 구하는 연산이 됩니다.
따라서 펜윅 트리에 $D$를 관리하면:
- 구간 갱신 $[L, R] + v$: 펜윅 트리에 `add(L, v)`, `add(R+1, -v)` 2회 ($O(\log N)$)
- 점 질의 $A_i$: 펜윅 트리의 `query(i)` ($O(\log N)$)
두 연산 모두 $O(\log N)$으로 완벽하게 해결됩니다.
