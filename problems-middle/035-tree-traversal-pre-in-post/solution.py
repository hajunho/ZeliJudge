import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    idx = 1
    tree = {}
    for _ in range(N):
        node = lines[idx]
        left = lines[idx+1]
        right = lines[idx+2]
        tree[node] = (left, right)
        idx += 3
        
    pre_res = []
    in_res = []
    post_res = []
    
    def preorder(curr):
        if curr == '.':
            return
        pre_res.append(curr)
        preorder(tree[curr][0])
        preorder(tree[curr][1])
        
    def inorder(curr):
        if curr == '.':
            return
        inorder(tree[curr][0])
        in_res.append(curr)
        inorder(tree[curr][1])
        
    def postorder(curr):
        if curr == '.':
            return
        postorder(tree[curr][0])
        postorder(tree[curr][1])
        post_res.append(curr)
        
    preorder('A')
    inorder('A')
    postorder('A')
    
    print("".join(pre_res))
    print("".join(in_res))
    print("".join(post_res))

if __name__ == "__main__":
    solve()
