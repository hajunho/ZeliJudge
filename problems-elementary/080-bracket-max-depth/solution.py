import sys

def main():
    s = sys.stdin.read().strip()
    if not s:
        return
        
    current_depth = 0
    max_depth = 0
    
    for ch in s:
        if ch == '(':
            current_depth += 1
            if current_depth > max_depth:
                max_depth = current_depth
        elif ch == ')':
            current_depth -= 1
            
    print(max_depth)

if __name__ == "__main__":
    main()
