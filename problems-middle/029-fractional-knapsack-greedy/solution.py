import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    n, w = map(int, lines[0].split())
    
    items = []
    for i in range(1, 1 + n):
        if not lines[i].strip():
            continue
        weight, value = map(int, lines[i].split())
        items.append((weight, value, value / weight))
        
    # 단위 무게당 가치 내림차순 정렬
    items.sort(key=lambda x: x[2], reverse=True)
    
    total_val = 0.0
    rem_cap = w
    
    for weight, value, ratio in items:
        if rem_cap <= 0:
            break
        if weight <= rem_cap:
            total_val += value
            rem_cap -= weight
        else:
            total_val += ratio * rem_cap
            rem_cap = 0
            break
            
    print(f"{total_val:.2f}")

if __name__ == "__main__":
    main()
