import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    s = lines[0]
    n = len(s)
    if n <= 1:
        print(n)
        return
        
    def expand(left, right):
        while left >= 0 and right < n and s[left] == s[right]:
            left -= 1
            right += 1
        return right - left - 1

    max_len = 1
    for i in range(n):
        len1 = expand(i, i)       # 홀수 길이 회문
        len2 = expand(i, i + 1)   # 짝수 길이 회문
        if len1 > max_len:
            max_len = len1
        if len2 > max_len:
            max_len = len2
            
    print(max_len)

if __name__ == "__main__":
    solve()
