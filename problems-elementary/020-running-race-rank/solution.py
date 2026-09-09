"""
ZeliJudge Junior Problem #020: 가을 운동회 100m 달리기 등수 매기기
Standard Solution (Python 3)
"""
import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    n = int(lines[0].strip())
    
    runners = []
    for i in range(1, 1 + n):
        parts = lines[i].split()
        name = parts[0]
        record_str = parts[1]
        record_val = float(record_str)
        runners.append((record_val, name, record_str))
        
    # 기록(초) 기준 오름차순 정렬
    runners.sort(key=lambda x: x[0])
    
    for rank, item in enumerate(runners, 1):
        print(f"{rank} {item[1]} {item[2]}")

if __name__ == "__main__":
    main()
