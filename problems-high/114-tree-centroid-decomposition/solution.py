import sys
sys.setrecursionlimit(200000)

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    k_dist = int(input_data[1])
    
    adj = [[] for _ in range(n + 1)]
    idx = 2
    for _ in range(n - 1):
        u = int(input_data[idx])
        v = int(input_data[idx+1])
        idx += 2
        adj[u].append(v)
        adj[v].append(u)
        
    sz = [0] * (n + 1)
    deleted = [False] * (n + 1)
    
    def get_sz(u, p):
        sz[u] = 1
        for v in adj[u]:
            if v != p and not deleted[v]:
                get_sz(v, u)
                sz[u] += sz[v]
                
    def get_centroid(u, p, total):
        for v in adj[u]:
            if v != p and not deleted[v] and sz[v] > total // 2:
                return get_centroid(v, u, total)
        return u

    def get_dists(u, p, d, dist_list):
        if d > k_dist:
            return
        dist_list.append(d)
        for v in adj[u]:
            if v != p and not deleted[v]:
                get_dists(v, u, d + 1, dist_list)

    def count_pairs(dist_list):
        # Count pairs (a, b) with a + b <= k_dist
        dist_list.sort()
        res = 0
        l = 0
        r = len(dist_list) - 1
        while l < r:
            if dist_list[l] + dist_list[r] <= k_dist:
                res += (r - l)
                l += 1
            else:
                r -= 1
        return res

    total_pairs = 0

    def decompose(entry):
        nonlocal total_pairs
        get_sz(entry, 0)
        c = get_centroid(entry, 0, sz[entry])
        deleted[c] = True
        
        # Collect distances from c
        all_dists = [0]
        for v in adj[c]:
            if not deleted[v]:
                sub_dists = []
                get_dists(v, c, 1, sub_dists)
                # Subtract internal pairs from same subtree
                total_pairs -= count_pairs(sub_dists)
                all_dists.extend(sub_dists)
                
        total_pairs += count_pairs(all_dists)
        
        for v in adj[c]:
            if not deleted[v]:
                decompose(v)

    decompose(1)
    print(total_pairs)

if __name__ == '__main__':
    solve()
