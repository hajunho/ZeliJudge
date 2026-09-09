"""
ZeliJudge Junior Problem #058: 디지털 미술관의 16진수(HEX) 색상 코드 변환기
Standard Solution (Python 3)
"""
import sys

def main():
    tokens = sys.stdin.read().split()
    if not tokens:
        return
    r = int(tokens[0])
    g = int(tokens[1])
    b = int(tokens[2])
    
    # {:02X} 포맷팅: 2자리 대문자 16진수, 빈자리는 0 채움
    hex_code = f"#{r:02X}{g:02X}{b:02X}"
    print(hex_code)

if __name__ == "__main__":
    main()
