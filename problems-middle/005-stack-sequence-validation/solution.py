import sys

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    targets = [int(x) for x in input_data[1:1+n]]
    
    stack = []
    curr = 1
    possible = True
    
    for x in targets:
        while curr <= n and (not stack or stack[-1] != x):
            stack.append(curr)
            curr += 1
            
        if stack and stack[-1] == x:
            stack.pop()
        else:
            possible = False
            break
            
    if possible:
        print("YES")
    else:
        print("NO")

if __name__ == "__main__":
    main()
