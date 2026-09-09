import sys
from collections import OrderedDict

PRIMES = [31, 37, 41, 43, 47, 53, 59, 61, 67, 71]
SEEDS = [7, 11, 13, 17, 19, 23, 29, 31, 37, 41]

class BloomFilter:
    def __init__(self, m, k):
        self.m = m
        self.k = k
        self.bits = [0] * m

    def add(self, x):
        for i in range(self.k):
            h = (x * PRIMES[i] + SEEDS[i]) % self.m
            self.bits[h] = 1

    def contains(self, x):
        for i in range(self.k):
            h = (x * PRIMES[i] + SEEDS[i]) % self.m
            if self.bits[h] == 0:
                return False
        return True

class LRUCache:
    def __init__(self, capacity):
        self.capacity = capacity
        self.cache = OrderedDict()

    def get(self, key):
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        return None

    def put(self, key, value):
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = value
        if len(self.cache) > self.capacity:
            self.cache.popitem(last=False)

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    m = int(input_data[1])
    k = int(input_data[2])
    c = int(input_data[3])
    
    idx = 4
    valid_ids = [int(input_data[idx + i]) for i in range(n)]
    idx += n
    valid_set = set(valid_ids)
    
    # 1. Initialize Bloom Filter with valid IDs
    bloom = BloomFilter(m, k)
    for vid in valid_ids:
        bloom.add(vid)
        
    # 2. Initialize LRU Cache
    cache = LRUCache(c)
    
    q_num = int(input_data[idx])
    idx += 1
    
    out = []
    total_db_queries = 0
    blocked_requests = 0
    
    for _ in range(q_num):
        x = int(input_data[idx])
        idx += 1
        
        # Step 1: Bloom filter check
        if not bloom.contains(x):
            out.append("BLOOM_FILTER_BLOCKED")
            blocked_requests += 1
            continue
            
        # Step 2: Cache check
        if cache.get(x) is not None:
            out.append("CACHE_HIT")
            continue
            
        # Step 3: DB check (Cache Miss)
        total_db_queries += 1
        if x in valid_set:
            out.append("DB_HIT")
            cache.put(x, True)
        else:
            # False Positive from Bloom filter!
            out.append("DB_MISS_WASTED")
            
    out.append(f"TOTAL_DB_QUERIES: {total_db_queries} BLOCKED_REQUESTS: {blocked_requests}")
    print("\n".join(out))

if __name__ == '__main__':
    solve()
