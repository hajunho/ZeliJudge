import sys

def main():
    s = sys.stdin.read().strip()
    if not s:
        return
        
    matching = {')': '(', '}': '{', ']': '['}
    stack = []
    is_valid = True
    
    for ch in s:
        if ch in "({[":
            stack.append(ch)
        elif ch in ")}]":
            if not stack or stack[-1] != matching[ch]:
                is_valid = False
                break
            stack.pop()
            
    if is_valid and not stack:
        print("YES")
    else:
        print("NO")

if __name__ == "__main__":
    main()
