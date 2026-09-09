import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    
    w = []
    idx = 1
    for _ in range(n):
        row = [int(x) for x in input_data[idx:idx+n]]
        idx += n
        w.append(row)
        
    INF = 10**15
    memo = [[-1] * (1 << n) for _ in range(n)]
    
    def tsp(cur, visited):
        if visited == (1 << n) - 1:
            if w[cur][0] != 0:
                return w[cur][0]
            return INF
            
        if memo[cur][visited] != -1:
            return memo[cur][visited]
            
        min_cost = INF
        for nxt in range(n):
            if not (visited & (1 << nxt)) and w[cur][nxt] != 0:
                cost = tsp(nxt, visited | (1 << nxt)) + w[cur][nxt]
                if cost < min_cost:
                    min_cost = cost
                    
        memo[cur][visited] = min_cost
        return min_cost

    print(tsp(0, 1))

if __name__ == "__main__":
    solve()
