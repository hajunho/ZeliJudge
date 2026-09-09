import sys
import urllib.parse

def solve():
    """
    [ZeliJudge #019 표준 해법]
    URL 퍼센트 인코딩(Percent-Encoding)과 쿼리 스트링 왜곡 시뮬레이션
    
    - ENCODED: urllib.parse.quote(val, safe='') (RFC 3986 비예약 문자 외 전부 %XX)
    - NAIVE_CORRUPTED: 인코딩 없이 전송 시 '#' 절단, '&' 절단, '+'의 공백화
    - DECODED: urllib.parse.unquote(encoded_val) 원본 100% 복원
    
    시간 복잡도: O(Q * |S|)
    공간 복잡도: O(Q * |S|)
    """
    raw_lines = sys.stdin.read().splitlines()
    if not raw_lines:
        return

    q = int(raw_lines[0].strip())
    output = []

    for i in range(1, q + 1):
        if i >= len(raw_lines):
            break
        line = raw_lines[i]
        parts = line.split(' ', 1)
        key = parts[0]
        raw_val = parts[1] if len(parts) > 1 else ""

        # 1. 표준 퍼센트 인코딩
        encoded_val = urllib.parse.quote(raw_val, safe='')

        # 2. 인코딩 없는 단순 전송 시 왜곡 (# 절단 -> & 절단 -> + 공백화)
        corrupted_val = raw_val.split('#')[0].split('&')[0].replace('+', ' ')

        # 3. 디코딩 복원
        decoded_val = urllib.parse.unquote(encoded_val)

        output.append(f"ENCODED:{key}={encoded_val}")
        output.append(f"NAIVE_CORRUPTED:{key}={corrupted_val}")
        output.append(f"DECODED:{key}={decoded_val}")

    if output:
        sys.stdout.write("\n".join(output) + "\n")

if __name__ == '__main__':
    solve()
