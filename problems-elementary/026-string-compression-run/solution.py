"""
ZeliJudge Junior Problem #026: 연속된 글자 줄이기! 런렝스 압축의 마법
Standard Solution (Python 3)
"""
import sys

def main():
    s = sys.stdin.read().strip()
    if not s:
        return
        
    result = []
    current_char = s[0]
    count = 1
    
    for i in range(1, len(s)):
        if s[i] == current_char:
            count += 1
        else:
            result.append(f"{current_char}{count}")
            current_char = s[i]
            count = 1
            
    result.append(f"{current_char}{count}")
    print("".join(result))

if __name__ == "__main__":
    main()
