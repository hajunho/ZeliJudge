import sys
import math

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    n = int(lines[0].strip())
    
    total_num = 0
    total_den = 1
    
    for i in range(1, 1 + n):
        if not lines[i].strip():
            continue
        a, b = map(int, lines[i].split())
        
        # 분수 덧셈: total_num / total_den + a / b
        total_num = total_num * b + a * total_den
        total_den = total_den * b
        
        # 즉시 약분
        g = math.gcd(total_num, total_den)
        total_num //= g
        total_den //= g
        
    if total_den == 1:
        print(total_num)
    else:
        print(f"{total_num}/{total_den}")

if __name__ == "__main__":
    main()
