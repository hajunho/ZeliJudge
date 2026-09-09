"""
ZeliJudge Problem #002: 사라진 1원의 저주: IEEE 754 부동소수점
Standard Solution (Python 3)

시간 복잡도: O(N)
공간 복잡도: O(1)
"""
import sys
from decimal import Decimal, ROUND_HALF_UP

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    
    n = int(input_data[0])
    idx = 1
    
    total_sum = 0
    one = Decimal("1")
    hundred = Decimal("100")
    
    for _ in range(n):
        p_str = input_data[idx]
        d_str = input_data[idx + 1]
        v_str = input_data[idx + 2]
        idx += 3
        
        p = Decimal(p_str)
        d = Decimal(d_str)
        v = Decimal(v_str)
        
        # 공급가액 = P * (1 - D / 100)
        supply = p * (one - (d / hundred))
        # 최종 결제 금액 = 공급가액 * (1 + V / 100)
        final_price = supply * (one + (v / hundred))
        
        # 1원 미만 사사오입(ROUND_HALF_UP)
        rounded_val = int(final_price.quantize(one, rounding=ROUND_HALF_UP))
        total_sum += rounded_val
        
    print(total_sum)

if __name__ == "__main__":
    main()
