# 백트래킹(Backtracking)과 순열 생성

### 1. 순열($_N P_R$)의 수학적 정의
서로 다른 $N$개 중에서 순서를 고려하여 $R$개를 택해 나열하는 경우의 수입니다:
$$_N P_R = \frac{N!}{(N-R)!} = N \times (N-1) \times \dots \times (N-R+1)$$

---

### 2. 백트래킹(퇴각 검색)이란?
모든 가능한 경우의 수를 상태 공간 트리(State Space Tree)로 모델링하여 탐색하되,  
조건에 맞지 않거나 탐색이 끝나면 **이전 상태로 되돌아가서(Backtrack)** 다른 길을 찾는 기법입니다.

순열을 만들 때는 이미 선택한 숫자를 다시 고르면 안 되므로,  
`visited[i]` 불리언 배열을 사용하여 방문 여부를 관리합니다:

```python
visited[i] = True     # 1. 숫자 i 선택 (상태 전진)
path.append(i)
dfs(depth + 1)        # 2. 다음 자릿수 재귀 탐색
path.pop()            # 3. 되돌아오기 (Backtrack)
visited[i] = False    # 4. 선택 해제 (원상 복구)
```

이 패턴은 모든 완전 탐색(Brute Force)과 조합 최적화 문제의 가장 강력한 기본 뼈대가 됩니다.
