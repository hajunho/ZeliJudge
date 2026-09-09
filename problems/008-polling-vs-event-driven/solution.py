"""
ZeliJudge Problem #008: 끝없는 폴링과 소켓 고갈: Polling vs Event-Driven
Standard Solution (Python 3)

시간 복잡도: O(M)
공간 복잡도: O(M)
"""
import sys

def solve_polling(v0, target, t_start, t_max, p, intervals):
    """
    방식 A: 주기적 폴링 (Short Polling)
    - t = t_start + k * p (k >= 0) 마다 서버 상태를 확인
    - 가장 먼저 TARGET 상태를 만나는 k를 수학적으로 O(M)에 도출
    """
    # k의 최댓값 (t_max 이내)
    if t_start > t_max:
        return 0, -1
        
    max_k = (t_max - t_start) // p
    
    first_hit_k = None
    first_hit_time = None
    
    for left, right, val in intervals:
        if val == target:
            # 이 인터벌 [left, right)에서 t_start + k * p 가 들어오는 최소 k 계산
            if left <= t_start:
                k = 0
            else:
                k = (left - t_start + p - 1) // p
                
            t_k = t_start + k * p
            # k가 인터벌 내부이고 t_max 이내인지 확인
            if t_k < right and t_k <= t_max:
                if first_hit_k is None or k < first_hit_k:
                    first_hit_k = k
                    first_hit_time = t_k
                    break # 인터벌이 시간순이므로 첫 번째 히트가 최소 k
                    
    if first_hit_k is not None:
        return first_hit_k + 1, first_hit_time
    else:
        # t_max까지 도달했으나 감지 실패
        total_polls = max_k + 1
        return total_polls, -1

def solve_event_driven(v0, target, t_start, t_max, events):
    """
    방식 B: 이벤트 기반 푸시 (Event-Driven / Pub-Sub)
    - t_start <= event_time <= t_max 인 이벤트만 수신
    - TARGET 변경 이벤트 발생 시 즉시 감지
    """
    pushed_count = 0
    for t, val in events:
        if t < t_start:
            continue
        if t > t_max:
            break
            
        pushed_count += 1
        if val == target:
            return pushed_count, t
            
    return pushed_count, -1

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    
    v0 = int(input_data[0])
    target = int(input_data[1])
    t_start = int(input_data[2])
    t_max = int(input_data[3])
    p = int(input_data[4])
    m = int(input_data[5])
    
    raw_events = []
    idx = 6
    for _ in range(m):
        t = int(input_data[idx])
        val = int(input_data[idx + 1])
        raw_events.append((t, val))
        idx += 2
        
    # 동일 시각 이벤트 압축 (동일 시각이면 마지막 이벤트만 유효)
    events = []
    for t, val in raw_events:
        if events and events[-1][0] == t:
            events[-1] = (t, val)
        else:
            events.append((t, val))
            
    # 시간 구간(Intervals) 생성: [left, right, val)
    intervals = []
    prev_time = 0
    prev_val = v0
    
    for t, val in events:
        if t > prev_time:
            intervals.append((prev_time, t, prev_val))
        prev_time = t
        prev_val = val
    intervals.append((prev_time, float('inf'), prev_val))
    
    # 1. 폴링 방식 시뮬레이션
    polls, poll_detect_time = solve_polling(v0, target, t_start, t_max, p, intervals)
    
    # 2. 이벤트 기반 방식 시뮬레이션
    pushes, push_detect_time = solve_event_driven(v0, target, t_start, t_max, events)
    
    print(f"{polls} {poll_detect_time}")
    print(f"{pushes} {push_detect_time}")

if __name__ == "__main__":
    main()
