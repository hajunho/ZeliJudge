"""
ZeliJudge Junior Problem #014: 한 글자씩 밀어내는 카이사르 비밀 암호
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
        # A는 0, B는 1, ..., Z는 25로 변환
        idx = ord(ch) - ord('A')
        # K칸 밀고 26으로 나눈 나머지로 A~Z 순환
        new_idx = (idx + k) % 26
        result.append(chr(ord('A') + new_idx))
        
    print("".join(result))

if __name__ == "__main__":
    main()
