"""
ZeliJudge Junior Problem #060: 로봇이 계산하는 후위 표기법(Postfix) 한 자리 셈
Standard Solution (Python 3)
"""
import sys

def main():
    tokens = sys.stdin.read().split()
    if not tokens:
        return
        
    stack = []
    for t in tokens:
        if t in ['+', '-', '*']:
            b = stack.pop()
            a = stack.pop()
            if t == '+':
                stack.append(a + b)
            elif t == '-':
                stack.append(a - b)
            elif t == '*':
                stack.append(a * b)
        else:
            stack.append(int(t))
            
    print(stack[0])

if __name__ == "__main__":
    main()
