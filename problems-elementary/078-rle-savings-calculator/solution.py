import sys

def main():
    s = sys.stdin.read().strip()
    if not s:
        return
        
    compressed_parts = []
    curr_char = s[0]
    count = 1
    
    for i in range(1, len(s)):
        if s[i] == curr_char:
            count += 1
        else:
            compressed_parts.append(f"{curr_char}{count}")
            curr_char = s[i]
            count = 1
    compressed_parts.append(f"{curr_char}{count}")
    
    compressed_str = "".join(compressed_parts)
    savings = len(s) - len(compressed_str)
    print(savings)

if __name__ == "__main__":
    main()
