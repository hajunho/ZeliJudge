#!/usr/bin/env python3
"""
[ZeliJudge #020] 도서관 신청서에 불을 지르다: SQL Injection과 파라미터 바인딩
해답 코드: NAIVE 문자열 치환 시뮬레이션 vs SECURE 파라미터 바인딩 O(Q)
"""
import sys

def solve():
    input_data = sys.stdin.read().splitlines()
    if not input_data:
        return

    first_line = input_data[0].strip()
    if not first_line:
        return
    q_count = int(first_line)

    users = {}  # id -> (pw, role)
    first_user = None  # (id, role)
    output = []

    for line in input_data[1:q_count + 1]:
        line = line.strip()
        if not line:
            continue

        parts = line.split()
        cmd = parts[0]

        if cmd == "REGISTER":
            # REGISTER <id> <pw> <role>
            u_id = parts[1]
            u_pw = parts[2]
            u_role = parts[3]
            users[u_id] = (u_pw, u_role)
            if first_user is None:
                first_user = (u_id, u_role)

        elif cmd == "ATTACK_LOGIN":
            # ATTACK_LOGIN <input_id...> <input_pw>
            input_pw = parts[-1]
            input_id = " ".join(parts[1:-1])

            # 1. NAIVE 엔진 평가
            # (A) 주석 공격 (Comment Injection)
            if "'--" in input_id or "' --" in input_id:
                target_id = input_id.split("'")[0].strip()
                if target_id in users:
                    naive_res = f"SUCCESS:{target_id}:{users[target_id][1]}"
                else:
                    naive_res = "FAIL"
            else:
                clean_id = input_id.replace(" ", "").lower()
                # (B) 항상 참 우회 (Always-True Injection)
                if "'or'1'='1" in clean_id or "'or1=1" in clean_id:
                    if first_user is not None:
                        naive_res = f"SUCCESS:{first_user[0]}:{first_user[1]}"
                    else:
                        naive_res = "FAIL"
                else:
                    # (C) 일반 로그인
                    if input_id in users and users[input_id][0] == input_pw:
                        naive_res = f"SUCCESS:{input_id}:{users[input_id][1]}"
                    else:
                        naive_res = "FAIL"

            # 2. SECURE 엔진 평가 (파라미터 바인딩: input_id를 순수 데이터 리터럴로 취급)
            if input_id in users and users[input_id][0] == input_pw:
                secure_res = f"SUCCESS:{input_id}:{users[input_id][1]}"
            else:
                secure_res = "FAIL"

            output.append(f"AUTH NAIVE:{naive_res} SECURE:{secure_res}")

    if output:
        sys.stdout.write("\n".join(output) + "\n")

if __name__ == "__main__":
    solve()
