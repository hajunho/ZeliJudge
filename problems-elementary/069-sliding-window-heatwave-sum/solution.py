import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    parts = lines[0].split()
    n, k = int(parts[0]), int(parts[1])
    temps = [int(x) for x in lines[1].split()]
    
    current_sum = sum(temps[:k])
    max_sum = current_sum
    
    for i in range(k, n):
        current_sum += temps[i] - temps[i - k]
        if current_sum > max_sum:
            max_sum = current_sum
            
    print(max_sum)

if __name__ == "__main__":
    main()
