import sys

def main():
    line = sys.stdin.read().strip()
    if not line:
        return
    tokens = line.split()
    
    stack = []
    pair_map = {
        "</b>": "<b>",
        "</i>": "<i>",
        "</u>": "<u>",
        "</p>": "<p>"
    }
    
    for token in tokens:
        if token in ("<b>", "<i>", "<u>", "<p>"):
            stack.append(token)
        elif token in pair_map:
            if not stack or stack[-1] != pair_map[token]:
                print("NO")
                return
            stack.pop()
        else:
            # 일반 텍스트 토큰은 무시 (만약 들어올 경우 대비)
            pass
            
    if len(stack) == 0:
        print("YES")
    else:
        print("NO")

if __name__ == "__main__":
    main()
