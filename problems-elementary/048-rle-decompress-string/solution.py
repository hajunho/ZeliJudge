"""
ZeliJudge Junior Problem #048: 비밀 압축문 해제하기! 런렝스 복원기
Standard Solution (Python 3)
"""
import sys

def main():
    s = sys.stdin.read().strip()
    if not s:
        return
        
    result = []
    current_char = ''
    num_str = ''
    
    for ch in s:
        if ch.isalpha():
            if current_char:
                result.append(current_char * int(num_str))
            current_char = ch
            num_str = ''
        else:
            num_str += ch
            
    if current_char and num_str:
        result.append(current_char * int(num_str))
        
    print("".join(result))

if __name__ == "__main__":
    main()
