"""
ZeliJudge Junior Problem #018: 새싹초등학교 반장 선거 개표기
Standard Solution (Python 3)
"""
import sys

def main():
    tokens = sys.stdin.read().split()
    if not tokens:
        return
    n = int(tokens[0])
    votes = tokens[1:1+n]
    
    counts = {}
    for name in votes:
        counts[name] = counts.get(name, 0) + 1
        
    # 최대 득표수 찾기
    max_votes = max(counts.values())
    
    # 최대 득표수를 가진 후보들 골라내기
    winners = [name for name, v in counts.items() if v == max_votes]
    
    # 동점자는 사전순 정렬
    winners.sort()
    
    print(f"{winners[0]} {max_votes}")

if __name__ == "__main__":
    main()
