"""
ZeliJudge Junior Problem #003: 스마트 횡단보도 안전 지킴이
Standard Solution (Python 3)
"""
import sys

def main():
    tokens = sys.stdin.read().split()
    if not tokens:
        return
    
    light = tokens[0]
    seconds = int(tokens[1])
    car_state = tokens[2]
    
    # 빨간불이거나 차가 지나가는 중이면 무조건 정지
    if light == "RED" or car_state == "CAR":
        print("STOP")
    elif light == "GREEN" and car_state == "EMPTY":
        if seconds >= 5:
            print("CROSS")
        else:
            print("WAIT")
    else:
        print("STOP")

if __name__ == "__main__":
    main()
