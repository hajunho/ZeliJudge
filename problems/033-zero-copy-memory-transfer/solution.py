#!/usr/bin/env python3
import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return

    it = iter(input_data)

    # 1. ?? ??: CONFIG CS_COST:<ns> CPU_SPEED:<bps> DMA_SPEED:<bps>
    cmd = next(it)  # CONFIG
    cs_token = next(it)
    cpu_token = next(it)
    dma_token = next(it)

    cs_cost = int(cs_token.split(':')[1])
    cpu_speed = int(cpu_token.split(':')[1])
    dma_speed = int(dma_token.split(':')[1])

    N = int(next(it))

    total_cpu_bytes_trad = 0
    total_cpu_saved = 0

    output_lines = []

    for _ in range(N):
        op = next(it)  # TRANSFER
        tid = next(it)
        s = int(next(it))
        b = int(next(it))

        n_chunks = (s + b - 1) // b

        # 1. TRADITIONAL
        cs_trad = n_chunks * 4
        cpu_bytes_trad = 2 * s
        cpu_time_trad = cs_trad * cs_cost + cpu_bytes_trad // cpu_speed

        # 2. MMAP
        cs_mmap = n_chunks * 2
        cpu_bytes_mmap = s
        cpu_time_mmap = cs_mmap * cs_cost + cpu_bytes_mmap // cpu_speed

        # 3. ZERO_COPY
        cs_zero = 2
        cpu_bytes_zero = 0
        cpu_time_zero = cs_zero * cs_cost

        saved_cpu = cpu_time_trad - cpu_time_zero

        total_cpu_bytes_trad += cpu_bytes_trad
        total_cpu_saved += saved_cpu

        output_lines.append(
            f"REQ {tid} SIZE:{s}B TRADITIONAL_CPU:{cpu_time_trad}ns MMAP_CPU:{cpu_time_mmap}ns ZERO_COPY_CPU:{cpu_time_zero}ns SAVED_CPU:{saved_cpu}ns"
        )

    output_lines.append(
        f"SUMMARY TOTAL_TRANSFERS:{N} TOTAL_CPU_BYTES_TRADITIONAL:{total_cpu_bytes_trad}B TOTAL_CPU_BYTES_ZERO:0B TOTAL_CPU_SAVED:{total_cpu_saved}ns"
    )

    sys.stdout.write("\n".join(output_lines) + "\n")

if __name__ == '__main__':
    solve()
