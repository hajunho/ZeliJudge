import sys

def is_prime(n):
    if n < 2:
        return False
    if n == 2:
        return True
    if n % 2 == 0:
        return False
    d = 3
    while d * d <= n:
        if n % d == 0:
            return False
        d += 2
    return True

def main():
    line = sys.stdin.read().strip()
    if not line:
        return
    parts = line.split()
    l, r = int(parts[0]), int(parts[1])
    
    count = 0
    for num in range(l, r + 1):
        if is_prime(num):
            count += 1
            
    print(count)

if __name__ == "__main__":
    main()
