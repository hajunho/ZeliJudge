import sys
from datetime import datetime

def solve():
    """
    [ZeliJudge #017 표준 해법]
    시간대(Timezone)의 함정과 UTC 절대 시각 정규화 시뮬레이션
    
    - NAIVE: 표기된 로컬 날짜/시간 문자열 기준 정렬 -> 시차 무시로 대규모 순위 역전 발생
    - UTC_NORMALIZED: UTC 기준 절대 초(Timestamp)로 변환하여 정렬 -> 전 세계 공정 선착순 판정
    
    시간 복잡도: O(N log N)
    공간 복잡도: O(N)
    """
    tokens = sys.stdin.read().split()
    if not tokens:
        return

    n = int(tokens[0])
    orders = []

    idx = 1
    for _ in range(n):
        order_id = tokens[idx]
        date_str = tokens[idx + 1]
        time_str = tokens[idx + 2]
        tz_str = tokens[idx + 3]
        idx += 4

        # ISO 8601 파싱을 통한 UTC 타임스탬프 계산
        dt = datetime.fromisoformat(f"{date_str}T{time_str}{tz_str}")
        utc_ts = dt.timestamp()

        orders.append((order_id, date_str, time_str, tz_str, utc_ts))

    # 1. NAIVE 정렬: 로컬 문자열 기준 (date, time, order_id)
    naive_sorted = sorted(orders, key=lambda x: (x[1], x[2], x[0]))

    # 2. UTC_NORMALIZED 정렬: UTC 절대 초 기준 (utc_ts, order_id)
    utc_sorted = sorted(orders, key=lambda x: (x[4], x[0]))

    # 순위 불일치 주문 수 계산
    misplaced_count = sum(1 for i in range(n) if naive_sorted[i][0] != utc_sorted[i][0])

    fastest_utc = utc_sorted[0][0]
    fastest_naive = naive_sorted[0][0]

    top3_utc = [x[0] for x in utc_sorted[:3]]
    top3_naive = [x[0] for x in naive_sorted[:3]]

    output = [
        f"FASTEST UTC:{fastest_utc} NAIVE:{fastest_naive}",
        f"MISPLACED_ORDERS:{misplaced_count}",
        f"TOP3_UTC:{' '.join(top3_utc)}",
        f"TOP3_NAIVE:{' '.join(top3_naive)}"
    ]

    sys.stdout.write("\n".join(output) + "\n")

if __name__ == '__main__':
    solve()
