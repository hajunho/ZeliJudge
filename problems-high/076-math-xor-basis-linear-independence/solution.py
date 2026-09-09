import sys

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    a = [int(x) for x in input_data[1:1+n]]
    
    basis = [0] * 62
    for x in a:
        for b in range(60, -1, -1):
            if (x >> b) & 1:
                if not basis[b]:
                    basis[b] = x
                    break
                x ^= basis[b]
                
    ans = 0
    for b in range(60, -1, -1):
        if (ans ^ basis[b]) > ans:
            ans ^= basis[b]
            
    print(ans)

if __name__ == '__main__':
    main()
