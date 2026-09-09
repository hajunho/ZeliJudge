import sys
import heapq

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    idx = 1
    events = []
    for i in range(N):
        L = int(lines[idx])
        R = int(lines[idx+1])
        H = int(lines[idx+2])
        # Start event: (L, -H, R)
        events.append((L, -H, R))
        # End event: (R, 0, 0)
        events.append((R, 0, 0))
        idx += 3
        
    # Sort events by x coordinate.
    # Ties: higher H first (negative H is smaller), start before end
    events.sort()
    
    # Max-heap storing (-H, R)
    heap = [(0, 10**18)] # ground height 0 up to infinity
    skyline = []
    prev_h = 0
    
    for x, neg_h, r in events:
        if neg_h < 0:
            # Start of building: push (-neg_h, r)
            heapq.heappush(heap, (neg_h, r))
        # Remove expired buildings from heap top
        while heap and heap[0][1] <= x:
            heapq.heappop(heap)
            
        curr_h = -heap[0][0]
        if curr_h != prev_h:
            skyline.append((x, curr_h))
            prev_h = curr_h
            
    print(len(skyline))
    for x, h in skyline:
        print(f"{x} {h}")

if __name__ == "__main__":
    solve()
