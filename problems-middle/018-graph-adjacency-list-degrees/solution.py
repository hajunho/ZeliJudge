import sys

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    v = int(input_data[0])
    e = int(input_data[1])
    
    degree = [0] * (v + 1)
    ptr = 2
    for _ in range(e):
        u = int(input_data[ptr])
        w = int(input_data[ptr+1])
        ptr += 2
        degree[u] += 1
        degree[w] += 1
        
    result = [str(degree[i]) for i in range(1, v + 1)]
    print(" ".join(result))

if __name__ == "__main__":
    main()
