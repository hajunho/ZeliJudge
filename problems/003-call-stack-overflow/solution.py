"""
ZeliJudge Problem #003: 순진한 재귀함수의 최후: 콜 스택 오버플로우
Standard Solution (Python 3)

시간 복잡도: O(N)
공간 복잡도: O(N) (시스템 콜스택 대신 힙 메모리 스택 사용)
"""
import sys

def main():
    # 고속 I/O: 최대 30만 개 이상의 정수 토큰을 한 번에 읽기
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    
    n = int(input_data[0])
    
    # 가중치 배열 (1-based 인덱싱): O(N)
    # 0번 인덱스는 더미 0으로 채움
    weights = [0] + [int(x) for x in input_data[1 : 1 + n]]
    
    # 인접 리스트 생성: O(N)
    adj = [[] for _ in range(n + 1)]
    edge_idx = 1 + n
    for _ in range(n - 1):
        u = int(input_data[edge_idx])
        v = int(input_data[edge_idx + 1])
        edge_idx += 2
        adj[u].append(v)
        adj[v].append(u)
        
    # [핵심] 재귀 호출 대신 힙(Heap) 메모리를 활용한 명시적 스택(Explicit Stack) 반복문
    # 튜플 구성: (현재 노드, 부모 노드, 현재 깊이)
    stack = [(1, 0, 1)]
    total_cost = 0
    
    while stack:
        curr, parent, depth = stack.pop()
        total_cost += depth * weights[curr]
        
        for neighbor in adj[curr]:
            if neighbor != parent:
                stack.append((neighbor, curr, depth + 1))
                
    # 결과 출력
    print(total_cost)

if __name__ == "__main__":
    main()
