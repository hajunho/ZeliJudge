import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    n = int(lines[0].strip())
    
    main_diag = 0
    anti_diag = 0
    
    for i in range(n):
        row = [int(x) for x in lines[i + 1].split()]
        main_diag += row[i]
        anti_diag += row[n - 1 - i]
        
    diff = abs(main_diag - anti_diag)
    print(diff)

if __name__ == "__main__":
    main()
