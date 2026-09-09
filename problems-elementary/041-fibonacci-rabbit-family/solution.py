"""
ZeliJudge Junior Problem #041: 번식하는 마법 토끼 가족과 피보나치 수열
Standard Solution (Python 3)
"""
import sys

def main():
    tokens = sys.stdin.read().split()
    if not tokens:
        return
    n = int(tokens[0])
    
    if n <= 2:
        print(1)
        return
        
    a, b = 1, 1
    for _ in range(3, n + 1):
        a, b = b, a + b
        
    print(b)

if __name__ == "__main__":
    main()
