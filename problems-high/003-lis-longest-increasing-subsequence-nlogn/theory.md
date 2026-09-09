# LIS (Longest Increasing Subsequence) O(N log N)

## 1. O(N^2) DP의 한계
`D[i] = A[i]를 마지막 원소로 하는 LIS의 길이`로 두면 이중 루프로 인해 O(N^2)이 됩니다. N이 10만을 넘어가면 100억 연산으로 불가능합니다.

## 2. O(N log N) 인내 정렬(Patience Sorting) 원리
- 리스트 `tails`를 유지합니다. `tails[k]`는 길이 `k+1`인 증가 부분 수열이 가질 수 있는 **가장 작은 마지막 원소(tail)**를 의미합니다.
- 원소 x가 들어올 때, `tails`에서 x 이상의 원소가 처음 등장하는 위치를 이진 탐색(`bisect_left`)으로 찾습니다.
  - 위치가 `len(tails)`이면 x가 가장 크므로 `tails.append(x)` (LIS 길이 증가)
  - 그렇지 않다면 해당 위치의 원소를 x로 갱신하여 더 작은 tail로 교체합니다.
- 최종 `len(tails)`가 LIS의 최대 길이가 됩니다.