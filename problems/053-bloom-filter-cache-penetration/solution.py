import sys

def hash1(s):
    h = 0
    for c in s:
        h = (h * 31 + ord(c)) & 0xFFFFFFFF
    return h

def hash2(s):
    h = 0
    for c in s:
        h = (h * 37 + ord(c)) & 0xFFFFFFFF
    return h

def get_bloom_indices(key, m, k):
    h1 = hash1(key)
    h2 = hash2(key)
    indices = []
    for i in range(k):
        idx = (h1 + i * h2) % m
        indices.append(idx)
    return indices

def solve():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return

    m = 1000
    k = 3
    init_keys_count = 0

    idx = 0
    while idx < len(lines):
        line = lines[idx].strip()
        idx += 1
        if not line:
            continue
        parts = line.split()
        if parts[0] == "BLOOM_FILTER_SIZE":
            m = int(parts[1])
        elif parts[0] == "BLOOM_HASH_COUNT":
            k = int(parts[1])
        elif parts[0] == "INIT_KEYS":
            init_keys_count = int(parts[1])
            break

    db_table = set()
    while len(db_table) < init_keys_count and idx < len(lines):
        line = lines[idx].strip()
        idx += 1
        if not line:
            continue
        db_table.add(line)

    # Find EVENTS line
    events_count = 0
    while idx < len(lines):
        line = lines[idx].strip()
        idx += 1
        if not line:
            continue
        parts = line.split()
        if parts[0] == "EVENTS":
            events_count = int(parts[1])
            break

    requests = []
    while idx < len(lines):
        line = lines[idx].strip()
        idx += 1
        if not line:
            continue
        parts = line.split()
        if parts[0] == "REQ":
            requests.append((parts[1], parts[2]))

    # Build bloom filter bit array
    bloom_bits = bytearray(m)
    for key in db_table:
        for bit_idx in get_bloom_indices(key, m, k):
            bloom_bits[bit_idx] = 1

    naive_cache = set()
    bloom_cache = set()

    naive_db_queries = 0
    bloom_db_queries = 0
    bloom_rejects = 0
    false_positives = 0
    total_reqs = len(requests)

    for client_id, key in requests:
        # 1. NAIVE
        if key in naive_cache:
            n_status = "CACHE_HIT"
        else:
            naive_db_queries += 1
            if key in db_table:
                naive_cache.add(key)
                n_status = "DB_FOUND"
            else:
                n_status = "DB_NOT_FOUND"

        # 2. BLOOM
        if key in bloom_cache:
            b_status = "CACHE_HIT"
        else:
            in_bloom = True
            for bit_idx in get_bloom_indices(key, m, k):
                if bloom_bits[bit_idx] == 0:
                    in_bloom = False
                    break

            if not in_bloom:
                b_status = "BLOOM_REJECT"
                bloom_rejects += 1
            else:
                bloom_db_queries += 1
                if key in db_table:
                    bloom_cache.add(key)
                    b_status = "DB_FOUND"
                else:
                    b_status = "FALSE_POSITIVE_MISS"
                    false_positives += 1

        print(f"REQ {client_id} KEY:{key} NAIVE:{n_status} BLOOM:{b_status}")

    if naive_db_queries > 0:
        saved_pct = ((naive_db_queries - bloom_db_queries) / naive_db_queries) * 100.0
    else:
        saved_pct = 0.0

    print(f"SUMMARY TOTAL_REQS:{total_reqs}")
    print(f"NAIVE DB_QUERIES:{naive_db_queries}")
    print(f"BLOOM DB_QUERIES:{bloom_db_queries} BLOOM_REJECTS:{bloom_rejects} FALSE_POSITIVES:{false_positives}")
    print(f"SUMMARY DB_QUERY_SAVED:{saved_pct:.2f}%")

if __name__ == "__main__":
    solve()
