"""
ZeliJudge Junior Problem #010: 도서관 책 정리와 가나다 사전 순서
Standard Solution (Python 3)
"""
import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    n = int(lines[0].strip())
    books = [lines[i].strip() for i in range(1, 1 + n)]
    target = lines[1 + n].strip()
    
    sorted_books = sorted(books)
    target_pos = sorted_books.index(target) + 1
    
    print(target_pos)
    print(" ".join(sorted_books))

if __name__ == "__main__":
    main()
