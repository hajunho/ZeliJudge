"""
ZeliJudge Junior Problem #017: 비밀 단어 속 모음(a, e, i, o, u) 탐정
Standard Solution (Python 3)
"""
import sys

def main():
    word = sys.stdin.read().strip()
    if not word:
        return
        
    vowels = set("aeiou")
    v_count = 0
    c_count = 0
    
    for ch in word:
        if ch in vowels:
            v_count += 1
        else:
            c_count += 1
            
    print(f"{v_count} {c_count}")

if __name__ == "__main__":
    main()
