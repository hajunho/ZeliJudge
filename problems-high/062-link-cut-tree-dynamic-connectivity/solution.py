import sys

# Increase recursion depth just in case
sys.setrecursionlimit(200000)

class Node:
    __slots__ = ['val', 'mx', 'rev', 'p', 'ch']
    def __init__(self, val=0):
        self.val = val
        self.mx = val
        self.rev = False
        self.p = None
        self.ch = [None, None]

def is_root(x):
    return x.p is None or (x.p.ch[0] != x and x.p.ch[1] != x)

def push_up(x):
    x.mx = x.val
    if x.ch[0]:
        if x.ch[0].mx > x.mx:
            x.mx = x.ch[0].mx
    if x.ch[1]:
        if x.ch[1].mx > x.mx:
            x.mx = x.ch[1].mx

def push_down(x):
    if x.rev:
        x.ch[0], x.ch[1] = x.ch[1], x.ch[0]
        if x.ch[0]:
            x.ch[0].rev = not x.ch[0].rev
        if x.ch[1]:
            x.ch[1].rev = not x.ch[1].rev
        x.rev = False

def rotate(x):
    y = x.p
    z = y.p
    k = 1 if y.ch[1] == x else 0
    is_r = is_root(y)
    y.ch[k] = x.ch[k ^ 1]
    if x.ch[k ^ 1]:
        x.ch[k ^ 1].p = y
    x.ch[k ^ 1] = y
    y.p = x
    x.p = z
    if not is_r:
        z.ch[1 if z.ch[1] == y else 0] = x
    push_up(y)
    push_up(x)

def splay(x):
    st = []
    curr = x
    while not is_root(curr):
        st.append(curr)
        curr = curr.p
    st.append(curr)
    while st:
        push_down(st.pop())
    while not is_root(x):
        y = x.p
        z = y.p
        if not is_root(y):
            if (y.ch[1] == x) ^ (z.ch[1] == y):
                rotate(x)
            else:
                rotate(y)
        rotate(x)

def access(x):
    last = None
    curr = x
    while curr:
        splay(curr)
        curr.ch[1] = last
        push_up(curr)
        last = curr
        curr = curr.p
    splay(x)

def make_root(x):
    access(x)
    x.rev = not x.rev

def link(x, y):
    make_root(x)
    x.p = y

def cut(x, y):
    make_root(x)
    access(y)
    if y.ch[0] == x and x.ch[1] is None:
        y.ch[0] = None
        x.p = None
        push_up(y)

def query(x, y):
    make_root(x)
    access(y)
    return y.mx

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    q = int(input_data[1])
    nodes = [None] + [Node(int(input_data[2 + i])) for i in range(n)]
    idx = 2 + n
    out = []
    for _ in range(q):
        t = int(input_data[idx])
        u = int(input_data[idx + 1])
        v = int(input_data[idx + 2])
        idx += 3
        if t == 1:
            link(nodes[u], nodes[v])
        elif t == 2:
            cut(nodes[u], nodes[v])
        else:
            out.append(str(query(nodes[u], nodes[v])))
    print('\n'.join(out))

if __name__ == '__main__':
    main()
