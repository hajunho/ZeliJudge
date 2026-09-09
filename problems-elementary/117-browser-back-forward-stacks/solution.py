import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    q = int(lines[0].strip())
    
    current = "home"
    back_stack = []
    forward_stack = []
    
    for i in range(1, 1 + q):
        cmd_parts = lines[i].split()
        op = cmd_parts[0]
        
        if op == "VISIT":
            url = cmd_parts[1]
            back_stack.append(current)
            current = url
            forward_stack.clear()
        elif op == "BACK":
            if back_stack:
                forward_stack.append(current)
                current = back_stack.pop()
        elif op == "FORWARD":
            if forward_stack:
                back_stack.append(current)
                current = forward_stack.pop()
                
    print(current)

if __name__ == "__main__":
    main()
