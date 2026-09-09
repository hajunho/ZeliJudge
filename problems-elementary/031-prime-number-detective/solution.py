"""
ZeliJudge Junior Problem #031: 소수(Prime) 보물찾기 탐정단
Standard Solution (Python 3)
"""
import sys

def main():
    tokens = sys.stdin.read().split()
    if not tokens:
        return
    n = int(tokens[0])
    
    if n < 2:
        print("COMPOSITE")
        return
        
    is_prime = True
    for i in range(2, int(n**0.5) + 1):
        if n % i == 0:
            is_prime = False
            break
            
    if is_prime:
        print("PRIME")
    else:
        print("COMPOSITE")

if __name__ == "__main__":
    main()
