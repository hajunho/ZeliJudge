import sys
import re

def solve():
    """
    [ZeliJudge #016 표준 해법]
    정규표현식 탐욕적(Greedy) 매칭 vs 비탐욕적(Lazy) 매칭 시뮬레이션
    
    - GREEDY: r'<.*>'  -> 가장 첫 '<'부터 가장 마지막 '>'까지 최장 일치(Longest Match) 제거
    - LAZY:   r'<.*?>' -> 각 '<'부터 가장 가까운 '>'까지 최단 일치(Shortest Match) 개별 제거
    - LOST:   len(LAZY) - len(GREEDY) -> 탐욕적 매칭으로 인해 함께 삼켜진 순수 본문 글자 수
    
    시간 복잡도: O(Q * |S|)
    공간 복잡도: O(Q * |S|)
    """
    raw_input = sys.stdin.read().splitlines()
    if not raw_input:
        return

    q = int(raw_input[0].strip())
    output = []

    greedy_pattern = re.compile(r'<.*>')
    lazy_pattern = re.compile(r'<.*?>')

    for i in range(1, q + 1):
        if i >= len(raw_input):
            break
        s = raw_input[i]

        greedy_res = greedy_pattern.sub('', s)
        lazy_res = lazy_pattern.sub('', s)
        lost_count = len(lazy_res) - len(greedy_res)

        output.append(f"GREEDY:{greedy_res}")
        output.append(f"LAZY:{lazy_res}")
        output.append(f"LOST:{lost_count}")

    if output:
        sys.stdout.write("\n".join(output) + "\n")

if __name__ == '__main__':
    solve()
