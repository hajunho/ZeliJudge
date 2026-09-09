import sys
import heapq

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    idx = 1
    meetings = []
    for _ in range(N):
        s = int(lines[idx])
        e = int(lines[idx+1])
        meetings.append((s, e))
        idx += 2
        
    meetings.sort(key=lambda x: x[0])
    
    heap = []
    for s, e in meetings:
        if heap and heap[0] <= s:
            heapq.heappop(heap)
        heapq.heappush(heap, e)
        
    print(len(heap))

if __name__ == "__main__":
    solve()
