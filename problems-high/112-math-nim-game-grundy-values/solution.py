import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    k = int(input_data[0])
    piles = [int(x) for x in input_data[1:1+k]]
    
    # G(n) = n % 3 for moves {1, 2, 4}
    xor_sum = 0
    for stones in piles:
        xor_sum ^= (stones % 3)
        
    if xor_sum != 0:
        print("First")
    else:
        print("Second")

if __name__ == '__main__':
    solve()
