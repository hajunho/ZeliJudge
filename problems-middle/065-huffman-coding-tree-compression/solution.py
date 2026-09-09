import sys
import heapq

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    freqs = [int(x) for x in lines[1:1+N]]
    if N == 1:
        print(freqs[0])
        return
        
    pq = freqs[:]
    heapq.heapify(pq)
    total_bits = 0
    while len(pq) > 1:
        a = heapq.heappop(pq)
        b = heapq.heappop(pq)
        s = a + b
        total_bits += s
        heapq.heappush(pq, s)
    print(total_bits)

if __name__ == "__main__":
    solve()
