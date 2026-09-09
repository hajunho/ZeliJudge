"""
ZeliJudge Junior Problem #025: 짝수만 골라 담는 마법 주머니
Standard Solution (Python 3)
"""
import sys

def main():
    tokens = sys.stdin.read().split()
    if not tokens:
        return
    n = int(tokens[0])
    nums = [int(x) for x in tokens[1:1+n]]
    
    evens = [x for x in nums if x % 2 == 0]
    print(len(evens))
    print(sum(evens))

if __name__ == "__main__":
    main()
