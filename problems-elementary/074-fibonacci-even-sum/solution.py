import sys

def main():
    line = sys.stdin.read().strip()
    if not line:
        return
    m = int(line)
    
    a, b = 1, 2
    even_sum = 0
    while a <= m:
        if a % 2 == 0:
            even_sum += a
        a, b = b, a + b
        
    print(even_sum)

if __name__ == "__main__":
    main()
