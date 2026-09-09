"""
ZeliJudge Junior Problem #028: 매일매일 돌아가는 청소 당번 시계
Standard Solution (Python 3)
"""
import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    n = int(lines[0].strip())
    names = lines[1].split()
    d = int(lines[2].strip())
    
    # D는 1부터 시작하므로 0-indexed로 변환: (d - 1) % n
    target_idx = (d - 1) % n
    print(names[target_idx])

if __name__ == "__main__":
    main()
