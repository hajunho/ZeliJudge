import sys
sys.setrecursionlimit(100000)

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    k_limit = int(input_data[1])
    
    adj = [[] for _ in range(n + 1)]
    idx = 2
    for _ in range(n - 1):
        u = int(input_data[idx])
        v = int(input_data[idx+1])
        w = int(input_data[idx+2])
        idx += 3
        adj[u].append((v, w))
        adj[v].append((u, w))
        
    removed = [False] * (n + 1)
    sz = [0] * (n + 1)
    
    def get_sz(u, p):
        sz[u] = 1
        for v, _ in adj[u]:
            if v != p and not removed[v]:
                get_sz(v, u)
                sz[u] += sz[v]
        return sz[u]
        
    def get_centroid(u, p, total):
        for v, _ in adj[u]:
            if v != p and not removed[v] and sz[v] > total // 2:
                return get_centroid(v, u, total)
        return u

    total_pairs = 0
    
    def get_dists(u, p, d, dist_list):
        if d <= k_limit:
            dist_list.append(d)
        for v, w in adj[u]:
            if v != p and not removed[v]:
                get_dists(v, u, d + w, dist_list)

    def count_pairs(dists):
        dists.sort()
        cnt = 0
        l, r = 0, len(dists) - 1
        while l < r:
            if dists[l] + dists[r] <= k_limit:
                cnt += (r - l)
                l += 1
            else:
                r -= 1
        return cnt

    def decompose(u):
        nonlocal total_pairs
        total = get_sz(u, 0)
        c = get_centroid(u, 0, total)
        removed[c] = True
        
        all_dists = [0]
        for v, w in adj[c]:
            if not removed[v]:
                sub_dists = []
                get_dists(v, c, w, sub_dists)
                total_pairs -= count_pairs(sub_dists)
                all_dists.extend(sub_dists)
                
        total_pairs += count_pairs(all_dists)
        
        for v, _ in adj[c]:
            if not removed[v]:
                decompose(v)

    decompose(1)
    print(total_pairs)

if __name__ == "__main__":
    solve()
