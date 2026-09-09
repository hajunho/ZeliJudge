#!/usr/bin/env python3
import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return

    it = iter(input_data)

    # 1. ?? ??
    cmd = next(it)  # CONFIG
    M = int(next(it))
    K = int(next(it))

    seeds = [int(next(it)) for _ in range(K)]

    # 2. ???? ???
    # bytearray? ?? M? ??/??? ?? ?? (M <= 1,000,000??? 1MB ??)
    bit_array = bytearray(M)
    on_bits_count = 0
    db_set = set()

    # 3. ?? ?? ??
    def compute_hashes(s):
        ords = [ord(c) for c in s]
        hashes = []
        for seed in seeds:
            val = seed
            for o in ords:
                val = (val * 31 + o) % M
            hashes.append(val)
        return hashes

    # 4. ?? ??
    Q = int(next(it))
    query_count = 0
    blocked_count = 0
    tp_count = 0
    fp_count = 0

    output_lines = []

    for _ in range(Q):
        op = next(it)
        key = next(it)

        if op == "INSERT":
            db_set.add(key)
            hashes = compute_hashes(key)
            for h in hashes:
                if bit_array[h] == 0:
                    bit_array[h] = 1
                    on_bits_count += 1
        elif op == "QUERY":
            query_count += 1
            hashes = compute_hashes(key)
            # ? ???? 0? ??? ??? ??
            is_absent = any(bit_array[h] == 0 for h in hashes)

            if is_absent:
                blocked_count += 1
                output_lines.append(f"QUERY {key} RESULT:DEFINITELY_ABSENT ACTION:BLOCKED")
            else:
                if key in db_set:
                    tp_count += 1
                    output_lines.append(f"QUERY {key} RESULT:POSSIBLY_PRESENT ACTUAL:PRESENT")
                else:
                    fp_count += 1
                    output_lines.append(f"QUERY {key} RESULT:POSSIBLY_PRESENT ACTUAL:ABSENT_FALSE_POSITIVE")

    output_lines.append(
        f"SUMMARY QUERIES:{query_count} BLOCKED:{blocked_count} DB_HITS:{tp_count} FALSE_POSITIVES:{fp_count} ON_BITS:{on_bits_count}/{M}"
    )
    sys.stdout.write("\n".join(output_lines) + "\n")

if __name__ == '__main__':
    solve()
