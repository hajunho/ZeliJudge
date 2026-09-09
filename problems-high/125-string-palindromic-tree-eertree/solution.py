import sys

class EERTREE:
    def __init__(self, n):
        # 0: even root (len 0), 1: odd root (len -1)
        self.len = [0] * (n + 5)
        self.link = [0] * (n + 5)
        self.next = [{} for _ in range(n + 5)]
        self.len[0] = 0; self.link[0] = 1
        self.len[1] = -1; self.link[1] = 1
        self.sz = 2
        self.last = 0
        self.s = []

    def get_link(self, v):
        pos = len(self.s) - 1
        while True:
            cur_len = self.len[v]
            if pos - 1 - cur_len >= 0 and self.s[pos - 1 - cur_len] == self.s[pos]:
                return v
            v = self.link[v]

    def add_char(self, ch):
        self.s.append(ch)
        cur = self.get_link(self.last)
        if ch not in self.next[cur]:
            nxt = self.sz
            self.sz += 1
            self.len[nxt] = self.len[cur] + 2
            if self.len[nxt] == 1:
                self.link[nxt] = 0
            else:
                self.link[nxt] = self.next[self.get_link(self.link[cur])][ch]
            self.next[cur][ch] = nxt
        self.last = self.next[cur][ch]

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    s = input_data[0]
    tree = EERTREE(len(s))
    for ch in s:
        tree.add_char(ch)
    # Number of distinct palindromes = tree.sz - 2 (excluding the two roots)
    print(tree.sz - 2)

if __name__ == '__main__':
    solve()
