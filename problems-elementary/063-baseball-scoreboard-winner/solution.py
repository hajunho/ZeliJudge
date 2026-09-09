import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    away_scores = [int(x) for x in lines[0].split()]
    home_scores = [int(x) for x in lines[1].split()]
    
    total_away = sum(away_scores)
    total_home = sum(home_scores)
    
    print(f"{total_away}:{total_home}")
    if total_away > total_home:
        print("AWAY")
    elif total_home > total_away:
        print("HOME")
    else:
        print("DRAW")

if __name__ == "__main__":
    main()
