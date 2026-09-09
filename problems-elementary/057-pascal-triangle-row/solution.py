"""
ZeliJudge Junior Problem #057: 삼각형으로 쌓이는 조합의 비밀: 파스칼 삼각형
Standard Solution (Python 3)
"""
import sys

def main():
    tokens = sys.stdin.read().split()
    if not tokens:
        return
    n = int(tokens[0])
    
    triangle = [[1]]
    for i in range(1, n):
        prev = triangle[-1]
        row = [1]
        for j in range(len(prev) - 1):
            row.append(prev[j] + prev[j + 1])
        row.append(1)
        triangle.append(row)
        
    print(" ".join(map(str, triangle[n - 1])))

if __name__ == "__main__":
    main()
