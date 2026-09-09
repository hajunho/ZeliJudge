import sys

def solve():
    """
    [ZeliJudge #013 표준 해법]
    값(Equality, ==)과 객체 주소(Identity, is)의 차이 시뮬레이션
    
    1. INT a b:
       - EQ: a == b
       - IS: a == b and (-5 <= a <= 256) [CPython Small Integer Cache]
    2. STR s t:
       - EQ: s == t
       - IS: s == t and s.isidentifier() [String Interning Pool]
    3. LIST item1 item2:
       - EQ: item1 == item2
       - IS: NO [[] 리터럴은 항상 독립된 새로운 힙 객체 할당]
    
    시간 복잡도: O(Q)
    공간 복잡도: O(Q)
    """
    input_data = sys.stdin.read().split()
    if not input_data:
        return

    q = int(input_data[0])
    idx = 1
    output = []

    for _ in range(q):
        cmd = input_data[idx]
        idx += 1

        if cmd == "INT":
            a = int(input_data[idx])
            b = int(input_data[idx + 1])
            idx += 2

            eq = "YES" if a == b else "NO"
            is_same = "YES" if (a == b and -5 <= a <= 256) else "NO"
            output.append(f"INT {a} {b} IS:{is_same} EQ:{eq}")

        elif cmd == "STR":
            s = input_data[idx]
            t = input_data[idx + 1]
            idx += 2

            eq = "YES" if s == t else "NO"
            is_same = "YES" if (s == t and s.isidentifier()) else "NO"
            output.append(f"STR {s} {t} IS:{is_same} EQ:{eq}")

        elif cmd == "LIST":
            item1 = input_data[idx]
            item2 = input_data[idx + 1]
            idx += 2

            eq = "YES" if item1 == item2 else "NO"
            output.append(f"LIST {item1} {item2} IS:NO EQ:{eq}")

    if output:
        sys.stdout.write("\n".join(output) + "\n")

if __name__ == '__main__':
    solve()
