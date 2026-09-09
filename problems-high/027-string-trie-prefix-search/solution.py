import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    t = int(input_data[0])
    idx = 1
    
    out = []
    for _ in range(t):
        n = int(input_data[idx])
        idx += 1
        numbers = input_data[idx:idx+n]
        idx += n
        
        # 정렬하면 접두어 관계인 문자열들이 인접하게 됨
        numbers.sort()
        consistent = True
        for i in range(n - 1):
            if numbers[i+1].startswith(numbers[i]):
                consistent = False
                break
                
        out.append("YES" if consistent else "NO")
        
    print("\n".join(out))

if __name__ == "__main__":
    solve()
