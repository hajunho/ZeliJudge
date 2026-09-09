# CCW 선분 교차 판정

## 1. 기본 교차 조건
- $C_1 = \text{ccw}(A, B, C) \times \text{ccw}(A, B, D)$
- $C_2 = \text{ccw}(C, D, A) \times \text{ccw}(C, D, B)$
- 두 값이 모두 $\le 0$이면 교차할 가능성이 높습니다.

## 2. 네 점이 일직선상에 있는 경우 ($C_1 == 0$ and $C_2 == 0$)
네 점의 좌표가 일직선상에 위치할 때는 외적만으로는 판정할 수 없습니다.
두 선분의 $x$좌표 구간과 $y$좌표 구간이 서로 겹치는지(Overlapping Bounding Box) 검사해야 합니다:
$$\max(A, B) \ge \min(C, D) \quad \text{and} \quad \max(C, D) \ge \min(A, B)$$