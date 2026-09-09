# 펜윅 트리 (Fenwick Tree / Binary Indexed Tree)

## 1. 2의 보수와 LSB (Least Significant Bit)
`k & -k`는 정수 k의 가장 오른쪽에 있는 1 비트(LSB)만을 남깁니다.
- `tree[i]`는 구간 `(i - (i & -i), i]`의 부분합을 저장합니다.

## 2. 연산 원리
- **점 갱신 (`add(i, val)`)**: `i`에 `i & -i`를 더해가며 상위 포함 구간들을 $O(\log N)$에 갱신합니다.
- **누적합 질의 (`query(i)`)**: `i`에서 `i & -i`를 빼가며 $1$부터 $i$까지의 합을 $O(\log N)$에 누적합니다.
- **구간합 `[l, r]`**: `query(r) - query(l - 1)`