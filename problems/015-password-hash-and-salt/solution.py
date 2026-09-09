import sys
import hashlib

def solve():
    """
    [ZeliJudge #015 표준 해법]
    비밀번호 단방향 해시와 솔트(Salt)의 레인보우 테이블 방어 시뮬레이션
    
    - NAIVE: salt 없이 sha256(password) 저장 -> 레인보우 테이블에 즉시 크랙됨
    - SALTED: sha256(salt + password) 저장 -> 레인보우 테이블 무력화 및 해시 분리
    
    시간 복잡도: O(M + Q)
    공간 복잡도: O(M + U)
    """
    tokens = sys.stdin.read().split()
    if not tokens:
        return

    m = int(tokens[0])
    idx = 1

    # 해커의 레인보우 테이블 구축
    rainbow_table = {}
    for _ in range(m):
        w = tokens[idx]
        idx += 1
        h = hashlib.sha256(w.encode('utf-8')).hexdigest()
        rainbow_table[h] = w

    q = int(tokens[idx])
    idx += 1

    naive_db = {}
    salted_db = {}
    output = []

    for _ in range(q):
        cmd = tokens[idx]
        idx += 1

        if cmd == "REGISTER":
            user = tokens[idx]
            pw = tokens[idx + 1]
            salt = tokens[idx + 2]
            idx += 3

            naive_db[user] = hashlib.sha256(pw.encode('utf-8')).hexdigest()
            salted_db[user] = hashlib.sha256((salt + pw).encode('utf-8')).hexdigest()

        elif cmd == "ATTACK":
            user = tokens[idx]
            idx += 1

            n_h = naive_db[user]
            n_res = f"CRACKED:{rainbow_table[n_h]}" if n_h in rainbow_table else "SECURE"

            s_h = salted_db[user]
            s_res = f"CRACKED:{rainbow_table[s_h]}" if s_h in rainbow_table else "SECURE"

            output.append(f"ATTACK {user} NAIVE:{n_res} SALTED:{s_res}")

        elif cmd == "HASH_COMPARE":
            u1 = tokens[idx]
            u2 = tokens[idx + 1]
            idx += 2

            n_same = "SAME" if naive_db[u1] == naive_db[u2] else "DIFF"
            s_same = "SAME" if salted_db[u1] == salted_db[u2] else "DIFF"

            output.append(f"COMPARE {u1} {u2} NAIVE:{n_same} SALTED:{s_same}")

    if output:
        sys.stdout.write("\n".join(output) + "\n")

if __name__ == '__main__':
    solve()
