# 이론 및 해설: 구간의 최대 연속합을 실시간으로! 금광 세그먼트 트리 (Max Subarray Sum SegTree)

### 금광 세그먼트 트리 (Maximum Subarray Sum Segment Tree)

배열의 특정 원소가 동적으로 수정되는 상황에서, 임의의 구간 $[L, R]$의 연속 부분합 최댓값(Maximum Subarray Sum)을 $O(\log N)$에 구하는 대표적인 세그먼트 트리 응용입니다.

1. **노드에 유지해야 할 4가지 정보**:
   - `sum`: 구간 전체의 합 ($L.sum + R.sum$)
   - `pref`: 구간의 가장 왼쪽부터 시작하는 최대 접두사 합 ($\max(L.pref, L.sum + R.pref)$)
   - `suff`: 구간의 가장 오른쪽에서 끝나는 최대 접미사 합 ($\max(R.suff, R.sum + L.suff)$)
   - `ans`: 구간 내부에서 가능한 최대 연속 부분합 ($\max(L.ans, R.ans, L.suff + R.pref)$)
