# CCW를 이용한 선분 교차 판별의 기하학

### 1. 교차의 기하학적 조건
두 선분 $AB$와 $CD$가 교차하려면 다음 두 조건이 **동시에** 만족되어야 합니다:

1. 선분 $AB$의 직선을 기준으로 점 $C$와 점 $D$가 **서로 반대편**에 위치해야 합니다.  
   $$\text{CCW}(A, B, C) \times \text{CCW}(A, B, D) \le 0$$
2. 선분 $CD$의 직선을 기준으로 점 $A$와 점 $B$가 **서로 반대편**에 위치해야 합니다.  
   $$\text{CCW}(C, D, A) \times \text{CCW}(C, D, B) \le 0$$

---

### 2. 일직선 상에 있는 예외 케이스 (Collinear)
만약 네 점이 모두 한 직선 위에 있다면 모든 CCW 값이 0이 되어 위 두 곱이 모두 0이 됩니다.  
이때는 두 선분이 실제로 겹쳐 있는지 $x$축과 $y$축의 구간 겹침(Bounding Box Overlap)을 확인해야 합니다:

$$\min(A_x, B_x) \le \max(C_x, D_x) \quad \text{and} \quad \min(C_x, D_x) \le \max(A_x, B_x)$$
(y축에 대해서도 동일하게 만족해야 교차)
