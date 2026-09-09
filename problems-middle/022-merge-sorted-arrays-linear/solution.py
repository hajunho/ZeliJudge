import sys

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    m = int(input_data[1])
    
    ptr = 2
    a = [int(x) for x in input_data[ptr:ptr+n]]
    ptr += n
    b = [int(x) for x in input_data[ptr:ptr+m]]
    
    merged = []
    i, j = 0, 0
    while i < n and j < m:
        if a[i] <= b[j]:
            merged.append(str(a[i]))
            i += 1
        else:
            merged.append(str(b[j]))
            j += 1
            
    while i < n:
        merged.append(str(a[i]))
        i += 1
    while j < m:
        merged.append(str(b[j]))
        j += 1
        
    print(" ".join(merged))

if __name__ == "__main__":
    main()
