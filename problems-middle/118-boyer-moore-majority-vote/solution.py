import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    arr = [int(x) for x in lines[1:1+N]]
    
    # Step 1: Find candidate via Boyer-Moore
    candidate = None
    count = 0
    for x in arr:
        if count == 0:
            candidate = x
            count = 1
        elif x == candidate:
            count += 1
        else:
            count -= 1
            
    # Step 2: Verify candidate
    actual_count = sum(1 for x in arr if x == candidate)
    if actual_count > N // 2:
        print(candidate)
    else:
        print("NO MAJORITY")

if __name__ == "__main__":
    solve()
