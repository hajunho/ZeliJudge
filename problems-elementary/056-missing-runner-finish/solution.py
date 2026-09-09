"""
ZeliJudge Junior Problem #056: 마라톤 완주자 명단과 사라진 단 한 명의 러너
Standard Solution (Python 3)
"""
import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    n = int(lines[0].strip())
    participants = lines[1].split()
    finishers = lines[2].split()
    
    # 집합 차집합(Difference) 활용
    missing = set(participants) - set(finishers)
    print(list(missing)[0])

if __name__ == "__main__":
    main()
