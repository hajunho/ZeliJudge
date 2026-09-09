"""
ZeliJudge Junior Problem #046: 매일매일 모은 용돈! 특정 기간 저금통 합계
Standard Solution (Python 3)
"""
import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    n = int(lines[0].strip())
    money = [int(x) for x in lines[1].split()]
    lr = lines[2].split()
    l = int(lr[0])
    r = int(lr[1])
    
    # L과 R은 1-based 인덱스이므로 슬라이싱은 money[l-1 : r]
    sub_sum = sum(money[l - 1 : r])
    print(sub_sum)

if __name__ == "__main__":
    main()
