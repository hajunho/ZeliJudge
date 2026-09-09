"""
ZeliJudge Junior Problem #037: 1부터 100까지! 업다운 숫자 맞추기
Standard Solution (Python 3)
"""
import sys

def main():
    tokens = sys.stdin.read().split()
    if not tokens:
        return
    n = int(tokens[0])
    target = int(tokens[1])
    
    left = 1
    right = n
    attempts = 0
    
    while left <= right:
        attempts += 1
        mid = (left + right) // 2
        if mid == target:
            break
        elif mid < target:
            left = mid + 1
        else:
            right = mid - 1
            
    print(attempts)

if __name__ == "__main__":
    main()
