"""
ZeliJudge Junior Problem #032: 놀이공원 롤러코스터 대기열과 큐(Queue)
Standard Solution (Python 3)
"""
import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    k = int(lines[0].strip())
    n = int(lines[1].strip())
    people = lines[2].split()
    
    boarded = people[:k]
    waiting = people[k:]
    
    print(" ".join(boarded))
    if waiting:
        print(" ".join(waiting))
    else:
        print("EMPTY")

if __name__ == "__main__":
    main()
