import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    n = int(lines[0].strip())
    
    meetings = []
    for i in range(1, 1 + n):
        if not lines[i].strip():
            continue
        s, e = map(int, lines[i].split())
        meetings.append((s, e))
        
    # 끝나는 시간 오름차순, 끝나는 시간 같으면 시작 시간 오름차순
    meetings.sort(key=lambda x: (x[1], x[0]))
    
    count = 0
    last_end = 0
    for s, e in meetings:
        if s >= last_end:
            count += 1
            last_end = e
            
    print(count)

if __name__ == "__main__":
    main()
