import sys
import math

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    points = []
    idx = 1
    for _ in range(n):
        x = float(input_data[idx])
        y = float(input_data[idx+1])
        idx += 2
        points.append((x, y))
        
    # Precompute distances
    dist = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            dist[i][j] = math.hypot(points[i][0] - points[j][0], points[i][1] - points[j][1])
            
    # dp[i][j]: min perimeter sum for subpolygon i..j
    dp = [[0.0] * n for _ in range(n)]
    
    for length in range(3, n + 1):
        for i in range(n - length + 1):
            j = i + length - 1
            min_val = float('inf')
            for k in range(i + 1, j):
                cost = dp[i][k] + dp[k][j] + dist[i][k] + dist[k][j] + dist[j][i]
                if cost < min_val:
                    min_val = cost
            dp[i][j] = min_val
            
    print(f"{dp[0][n-1]:.4f}")

if __name__ == '__main__':
    solve()
