"""
ZeliJudge Junior Problem #009: 과자 공장의 무게 검사기와 불량품 찾기
Standard Solution (Python 3)
"""
import sys

def main():
    tokens = sys.stdin.read().split()
    if not tokens:
        return
    n = int(tokens[0])
    target = int(tokens[1])
    error = int(tokens[2])
    
    weights = [int(x) for x in tokens[3:3+n]]
    
    min_ok = target - error
    max_ok = target + error
    
    normal_count = 0
    defect_count = 0
    
    for w in weights:
        if min_ok <= w <= max_ok:
            normal_count += 1
        else:
            defect_count += 1
            
    print(f"{normal_count} {defect_count}")

if __name__ == "__main__":
    main()
