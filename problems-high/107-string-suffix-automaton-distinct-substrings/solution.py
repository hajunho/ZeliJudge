import sys

class SAM:
    def __init__(self, maxlen):
        self.len = [0] * (2 * maxlen)
        self.link = [0] * (2 * maxlen)
        self.next = [{} for _ in range(2 * maxlen)]
        self.sz = 1
        self.last = 0
        self.len[0] = 0
        self.link[0] = -1

    def extend(self, c):
        cur = self.sz
        self.sz += 1
        self.len[cur] = self.len[self.last] + 1
        p = self.last
        while p != -1 and c not in self.next[p]:
            self.next[p][c] = cur
            p = self.link[p]
            
        if p == -1:
            self.link[cur] = 0
        else:
            q = self.next[p][c]
            if self.len[p] + 1 == self.len[q]:
                self.link[cur] = q
            else:
                clone = self.sz
                self.sz += 1
                self.len[clone] = self.len[p] + 1
                self.next[clone] = dict(self.next[q])
                self.link[clone] = self.link[q]
                while p != -1 and self.next[p].get(c) == q:
                    self.next[p][c] = clone
                    p = self.link[p]
                self.link[q] = self.link[cur] = clone
        self.last = cur

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    s = input_data[0]
    sam = SAM(len(s))
    for ch in s:
        sam.extend(ch)
        
    ans = 0
    for i in range(1, sam.sz):
        ans += sam.len[i] - sam.len[sam.link[i]]
        
    print(ans)

if __name__ == '__main__':
    solve()
