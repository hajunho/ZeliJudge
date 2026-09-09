import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    x0 = int(lines[0])
    A = int(lines[1])
    B = int(lines[2])
    M = int(lines[3])
    
    # f(x) = (A * x + B) % M
    def f(x):
        return (A * x + B) % M
        
    # Phase 1: Finding intersection
    tortoise = f(x0)
    hare = f(f(x0))
    
    while tortoise != hare:
        tortoise = f(tortoise)
        hare = f(f(hare))
        
    # Phase 2: Finding start of cycle (mu)
    mu = 0
    tortoise = x0
    while tortoise != hare:
        tortoise = f(tortoise)
        hare = f(hare)
        mu += 1
        
    # Phase 3: Finding cycle length (lambda)
    lam = 1
    hare = f(tortoise)
    while tortoise != hare:
        hare = f(hare)
        lam += 1
        
    print(f"{mu} {lam}")

if __name__ == "__main__":
    solve()
