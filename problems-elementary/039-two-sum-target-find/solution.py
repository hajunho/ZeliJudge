"""
ZeliJudge Junior Problem #039: 장바구니 두 상품 합쳐서 만원 맞추기
Standard Solution (Python 3)
"""
import sys

def main():
    tokens = sys.stdin.read().split()
    if not tokens:
        return
    n = int(tokens[0])
    target = int(tokens[1])
    prices = [int(x) for x in tokens[2:2+n]]
    
    seen = set()
    found = False
    
    for p in prices:
        needed = target - p
        if needed in seen:
            found = True
            break
        seen.add(p)
        
    if found:
        print("YES")
    else:
        print("NO")

if __name__ == "__main__":
    main()
