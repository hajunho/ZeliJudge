"""
ZeliJudge Junior Problem #053: 적군의 암호를 해독하라! 카이사르 암호 복호화
Standard Solution (Python 3)
"""
import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    k = int(lines[0].strip())
    word = lines[1].strip()
    
    result = []
    for ch in word:
        idx = ord(ch) - ord('A')
        # 왼쪽으로 K칸 당기기: 음수가 되어도 파이썬의 % 연산자는 안전하게 순환!
        orig_idx = (idx - k) % 26
        result.append(chr(ord('A') + orig_idx))
        
    print("".join(result))

if __name__ == "__main__":
    main()
