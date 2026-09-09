# 투 포인터 (Two Pointers) 알고리즘

모든 원소가 **양의 정수**일 때, 구간의 오른쪽 끝을 늘리면 합이 커지고, 왼쪽 끝을 당기면 합이 작아지는 **단조성(Monotonicity)**이 성립합니다.

## 1. 알고리즘 흐름
1. `left = 0`, `current_sum = 0`, `count = 0` 으로 시작합니다.
2. `right` 포인터를 0부터 $N-1$까지 한 칸씩 오른쪽으로 이동하며 `current_sum += arr[right]` 합니다.
3. 만약 `current_sum > S` 라면, 합이 $S$ 이하가 될 때까지 `current_sum -= arr[left]` 하며 `left`를 오른쪽으로 당깁니다.
4. 만약 `current_sum == S` 라면, 목표를 달성했으므로 `count += 1`을 기록합니다!

## 2. 시간 복잡도
`left`와 `right` 포인터 모두 0에서 $N-1$까지 최대 한 번씩만 전진하므로, 전체 시간 복잡도는 놀랍게도 $O(N)$입니다!
