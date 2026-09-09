import sys
sys.setrecursionlimit(200000)

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    m = int(input_data[1])
    idx = 2
    X = [int(x) for x in input_data[idx:idx+n]]
    idx += n
    Y = [int(x) for x in input_data[idx:idx+m]]
    idx += m
    C = [int(x) for x in input_data[idx:idx+m]]
    
    def get_val(i, j):
        d = X[i] - Y[j]
        return d * d + C[j]

    # SMAWK implementation
    def smawk(rows, cols):
        if not rows:
            return {}
        # 1. Reduce cols
        stack = []
        for c in cols:
            while stack:
                r = rows[len(stack) - 1]
                if get_val(r, c) < get_val(r, stack[-1]):
                    stack.pop()
                elif len(stack) < len(rows):
                    break
                else:
                    break
            if len(stack) < len(rows):
                stack.append(c)
        reduced_cols = stack

        # 2. Recurse on even rows
        even_rows = [rows[i] for i in range(1, len(rows), 2)]
        ans_even = smawk(even_rows, reduced_cols)

        # 3. Interpolate odd rows
        ans = dict(ans_even)
        c_idx = 0
        for i in range(0, len(rows), 2):
            r = rows[i]
            c_start = reduced_cols[0] if i == 0 else ans[rows[i - 1]]
            c_end = reduced_cols[-1] if i + 1 >= len(rows) else ans[rows[i + 1]]
            
            # search in reduced_cols between c_start and c_end
            best_c = c_start
            best_v = get_val(r, best_c)
            
            # Find range in reduced_cols
            start_idx = reduced_cols.index(c_start)
            end_idx = reduced_cols.index(c_end)
            for k in range(start_idx, end_idx + 1):
                col = reduced_cols[k]
                val = get_val(r, col)
                if val < best_v:
                    best_v = val
                    best_c = col
            ans[r] = best_c
            
        return ans

    ans_cols = smawk(list(range(n)), list(range(m)))
    results = [get_val(i, ans_cols[i]) for i in range(n)]
    print(" ".join(map(str, results)))

if __name__ == '__main__':
    solve()
