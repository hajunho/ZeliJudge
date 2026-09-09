import sys

MOD1 = 1000000007
MOD2 = 1000000009
BASE1 = 313
BASE2 = 317

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    s = input_data[0]
    q = int(input_data[1])
    n = len(s)
    
    p1 = [1] * (n + 1)
    p2 = [1] * (n + 1)
    h1 = [0] * (n + 1)
    h2 = [0] * (n + 1)
    
    for i in range(n):
        val = ord(s[i])
        p1[i + 1] = (p1[i] * BASE1) % MOD1
        p2[i + 1] = (p2[i] * BASE2) % MOD2
        h1[i + 1] = (h1[i] * BASE1 + val) % MOD1
        h2[i + 1] = (h2[i] * BASE2 + val) % MOD2
        
    def get_hash(l, r):
        len_sub = r - l + 1
        sub1 = (h1[r] - h1[l - 1] * p1[len_sub]) % MOD1
        if sub1 < 0:
            sub1 += MOD1
        sub2 = (h2[r] - h2[l - 1] * p2[len_sub]) % MOD2
        if sub2 < 0:
            sub2 += MOD2
        return (sub1, sub2)

    idx = 2
    out = []
    for _ in range(q):
        l1 = int(input_data[idx])
        r1 = int(input_data[idx + 1])
        l2 = int(input_data[idx + 2])
        r2 = int(input_data[idx + 3])
        idx += 4
        
        if (r1 - l1) != (r2 - l2):
            out.append("NO")
        else:
            if get_hash(l1, r1) == get_hash(l2, r2):
                out.append("YES")
            else:
                out.append("NO")
                
    print('\n'.join(out))

if __name__ == '__main__':
    main()
