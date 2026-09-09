"""
ZeliJudge Junior Problem #030: 급식실 식판 쌓기와 올바른 괄호 짝 맞추기
Standard Solution (Python 3)
"""
import sys

def main():
    s = sys.stdin.read().strip()
    if not s:
        return
        
    stack_count = 0
    is_valid = True
    
    for ch in s:
        if ch == '(':
            stack_count += 1
        elif ch == ')':
            if stack_count == 0:
                is_valid = False
                break
            stack_count -= 1
            
    if stack_count != 0:
        is_valid = False
        
    if is_valid:
        print("YES")
    else:
        print("NO")

if __name__ == "__main__":
    main()
