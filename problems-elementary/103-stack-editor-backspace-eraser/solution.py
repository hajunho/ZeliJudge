import sys

def main():
    s = sys.stdin.read().strip()
    if not s:
        return
        
    stack = []
    for ch in s:
        if ch == '#':
            if stack:
                stack.pop()
        else:
            stack.append(ch)
            
    if not stack:
        print("EMPTY")
    else:
        print("".join(stack))

if __name__ == "__main__":
    main()
