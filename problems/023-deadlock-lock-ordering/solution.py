#!/usr/bin/env python3
"""
[ZeliJudge #023] A는 B를 기다리고 B는 A를 기다린다: 데드락과 락 획득 순서의 저주
해답 코드: 반복문 DFS 사이클 검출 및 위상 정렬 DAG 최장 경로 O(V + E)
"""
import sys
from collections import defaultdict

def solve():
    input_data = sys.stdin.read().splitlines()
    if not input_data:
        return

    first_line = input_data[0].strip()
    if not first_line:
        return
    n = int(first_line)

    naive_edges = set()
    ordered_edges = set()
    all_nodes = set()

    for line in input_data[1:n + 1]:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        # TX <tx_id> <res_from> <res_to>
        u = parts[2]
        v = parts[3]

        all_nodes.add(u)
        all_nodes.add(v)
        naive_edges.add((u, v))

        su = min(u, v)
        sv = max(u, v)
        ordered_edges.add((su, sv))

    sorted_nodes = sorted(all_nodes)

    # ==========================================
    # 1. NAIVE 정책 (사이클 검출)
    # ==========================================
    adj_naive = defaultdict(list)
    for u, v in naive_edges:
        adj_naive[u].append(v)
    for u in adj_naive:
        adj_naive[u].sort()

    state = {u: 0 for u in sorted_nodes}  # 0: unvisited, 1: visiting, 2: visited
    cycle_len = None

    for root in sorted_nodes:
        if state[root] != 0:
            continue

        stack = [(root, 0)]
        state[root] = 1
        path = [root]
        path_pos = {root: 0}

        while stack:
            u, nxt_idx = stack[-1]
            neighbors = adj_naive.get(u, [])

            if nxt_idx < len(neighbors):
                v = neighbors[nxt_idx]
                stack[-1] = (u, nxt_idx + 1)

                if state[v] == 1:
                    cycle_len = len(path) - path_pos[v]
                    break
                elif state[v] == 0:
                    state[v] = 1
                    path_pos[v] = len(path)
                    path.append(v)
                    stack.append((v, 0))
            else:
                state[u] = 2
                stack.pop()
                path.pop()
                del path_pos[u]

        if cycle_len is not None:
            break

    if cycle_len is not None:
        naive_output = f"NAIVE: DEADLOCK CYCLE:{cycle_len}"
    else:
        naive_output = "NAIVE: SAFE"

    # ==========================================
    # 2. ORDERED 정책 (DAG 최장 체인 계산)
    # ==========================================
    adj_ordered = defaultdict(list)
    for u, v in ordered_edges:
        adj_ordered[u].append(v)

    # 사전순이 이미 위상 정렬 순서이므로 순서대로 DP 진행
    dp = {u: 0 for u in sorted_nodes}
    for u in sorted_nodes:
        for v in adj_ordered.get(u, []):
            if dp[u] + 1 > dp[v]:
                dp[v] = dp[u] + 1

    max_chain = max(dp.values()) if dp else 0
    ordered_output = f"ORDERED: SAFE MAX_CHAIN:{max_chain}"

    print(naive_output)
    print(ordered_output)

if __name__ == "__main__":
    solve()
