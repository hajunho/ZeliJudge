import sys

def main():
    line = sys.stdin.read().strip()
    if not line:
        return
    n = int(line)
    
    # 2진수 문자열 추출 (접두사 '0b' 제거)
    b_str = bin(n)[2:]
    
    # 각 비트 반전
    flipped = "".join('0' if bit == '1' else '1' for bit in b_str)
    
    # 10진수로 변환
    result = int(flipped, 2)
    print(result)

if __name__ == "__main__":
    main()
