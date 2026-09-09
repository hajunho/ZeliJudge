"""
ZeliJudge Junior Problem #045: 해커를 막아라! 비밀번호 안전성 검사기
Standard Solution (Python 3)
"""
import sys

def main():
    p = sys.stdin.read().strip()
    if not p:
        return
        
    cond_len = len(p) >= 8
    cond_upper = any(ch.isupper() for ch in p)
    cond_lower = any(ch.islower() for ch in p)
    cond_digit = any(ch.isdigit() for ch in p)
    
    if cond_len and cond_upper and cond_lower and cond_digit:
        print("STRONG")
    else:
        print("WEAK")

if __name__ == "__main__":
    main()
