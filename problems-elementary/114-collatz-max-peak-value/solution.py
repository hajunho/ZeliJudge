import sys

def main():
    line = sys.stdin.read().strip()
    if not line:
        return
    n = int(line)
    
    max_val = n
    while n != 1:
        if n % 2 == 0:
            n //= 2
        else:
            n = n * 3 + 1
        if n > max_val:
            max_val = n
            
    print(max_val)

if __name__ == "__main__":
    main()
