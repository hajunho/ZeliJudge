import sys

def recursive_sum(n, depth_counter):
    depth_counter[0] += 1
    if n == 1:
        return 1
    return n + recursive_sum(n - 1, depth_counter)

def main():
    line = sys.stdin.read().strip()
    if not line:
        return
    n = int(line)
    
    counter = [0]
    total = recursive_sum(n, counter)
    print(counter[0])
    print(total)

if __name__ == "__main__":
    main()
