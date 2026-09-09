import sys

INF = float('-inf')
MAX_X = 1000000

class LiChaoTree:
    def __init__(self, size=MAX_X):
        self.size = size
        self.tree = [None] * (4 * (size + 1))
        
    def add_line(self, node, s, e, new_line):
        a_new, b_new = new_line
        curr = self.tree[node]
        if curr is None:
            self.tree[node] = new_line
            return
            
        a_curr, b_curr = curr
        mid = (s + e) // 2
        
        val_curr_mid = a_curr * mid + b_curr
        val_new_mid = a_new * mid + b_new
        
        if val_new_mid > val_curr_mid:
            self.tree[node] = new_line
            a_low, b_low = a_curr, b_curr
        else:
            a_low, b_low = a_new, b_new
            
        if s == e:
            return
            
        val_low_s = a_low * s + b_low
        val_hi_s = self.tree[node][0] * s + self.tree[node][1]
        
        if val_low_s > val_hi_s:
            self.add_line(node * 2, s, mid, (a_low, b_low))
        else:
            self.add_line(node * 2 + 1, mid + 1, e, (a_low, b_low))
            
    def query(self, node, s, e, x):
        if self.tree[node] is None:
            res = INF
        else:
            res = self.tree[node][0] * x + self.tree[node][1]
            
        if s == e:
            return res
            
        mid = (s + e) // 2
        if x <= mid:
            sub = self.query(node * 2, s, mid, x)
        else:
            sub = self.query(node * 2 + 1, mid + 1, e, x)
            
        return max(res, sub)

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    q = int(input_data[0])
    idx = 1
    
    lct = LiChaoTree()
    out = []
    for _ in range(q):
        t = int(input_data[idx])
        if t == 1:
            a = int(input_data[idx + 1])
            b = int(input_data[idx + 2])
            idx += 3
            lct.add_line(1, 0, MAX_X, (a, b))
        else:
            x = int(input_data[idx + 1])
            idx += 2
            out.append(str(lct.query(1, 0, MAX_X, x)))
            
    print('\n'.join(out))

if __name__ == '__main__':
    main()
