import sys
from collections import Counter

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    n = int(lines[0].strip())
    words = [line.strip() for line in lines[1:1+n] if line.strip()]
    
    counter = Counter(words)
    # 정렬: 빈도수 내림차순 (-count), 단어 사전순 오름차순 (word)
    sorted_items = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    
    for word, count in sorted_items:
        print(f"{word} {count}")

if __name__ == "__main__":
    main()
