import sys
from collections import deque

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    k = int(input_data[1])
    arr = [int(x) for x in input_data[2:2+n]]
    
    q = deque()  # 인덱스를 저장
    result = []
    
    for i in range(n):
        # 1. 윈도우 범위 [i - k + 1, i]를 벗어난 인덱스 제거
        while q and q[0] <= i - k:
            q.popleft()
            
        # 2. 현재 원소보다 작거나 같은 원소들 뒤에서 제거
        while q and arr[q[-1]] <= arr[i]:
            q.pop()
            
        q.append(i)
        
        # 3. 윈도우 크기 K가 완성된 이후부터 최댓값 기록
        if i >= k - 1:
            result.append(str(arr[q[0]]))
            
    print(" ".join(result))

if __name__ == "__main__":
    main()
