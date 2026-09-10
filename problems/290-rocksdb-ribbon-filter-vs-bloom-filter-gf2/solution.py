import sys
import json
import hashlib

def murmur_like_hash(key_str, seed):
    h = hashlib.sha256(f"{seed}:{key_str}".encode()).digest()
    return int.from_bytes(h[:8], "little")

class BloomFilter:
    def __init__(self, num_keys, bits_per_key=10, num_hashes=7):
        self.num_keys = num_keys
        self.m = max(64, num_keys * bits_per_key)
        self.k = num_hashes
        self.bit_array = [0] * self.m

    def insert(self, key):
        for i in range(self.k):
            idx = murmur_like_hash(key, i) % self.m
            self.bit_array[idx] = 1

    def query(self, key):
        for i in range(self.k):
            idx = murmur_like_hash(key, i) % self.m
            if self.bit_array[idx] == 0:
                return False
        return True

    def memory_bits(self):
        return self.m

class RibbonFilter:
    def __init__(self, num_keys, width=32, target_bits=7, slot_ratio=1.10):
        self.num_keys = num_keys
        self.w = width
        self.r = target_bits
        self.num_slots = max(width + 10, int(num_keys * slot_ratio) + width)
        self.sol = [[0] * self.r for _ in range(self.num_slots)]

    def _get_row(self, key):
        h1 = murmur_like_hash(key, 100)
        h2 = murmur_like_hash(key, 200)
        h3 = murmur_like_hash(key, 300)

        start = h1 % (self.num_slots - self.w + 1)
        mask = (h2 & ((1 << self.w) - 1))
        if mask == 0: mask = 1
        sig = [ (h3 >> b) & 1 for b in range(self.r) ]
        return start, mask, sig

    def construct(self, keys):
        pivots = {}
        for key in keys:
            start, mask, sig = self._get_row(key)
            shift = (mask & -mask).bit_length() - 1
            col = start + shift
            cur_mask = mask >> shift
            cur_sig = list(sig)

            while cur_mask > 0:
                if col in pivots:
                    p_mask, p_sig = pivots[col]
                    cur_mask ^= p_mask
                    for b in range(self.r):
                        cur_sig[b] ^= p_sig[b]
                    if cur_mask > 0:
                        shift = (cur_mask & -cur_mask).bit_length() - 1
                        col += shift
                        cur_mask >>= shift
                else:
                    pivots[col] = (cur_mask, cur_sig)
                    break

        for col in sorted(pivots.keys(), reverse=True):
            mask, sig = pivots[col]
            for b in range(self.r):
                val = 0
                for bit_idx in range(1, self.w):
                    if (mask >> bit_idx) & 1:
                        target_col = col + bit_idx
                        if target_col < self.num_slots:
                            val ^= self.sol[target_col][b]
                self.sol[col][b] = val ^ sig[b]

    def query(self, key):
        start, mask, sig = self._get_row(key)
        for b in range(self.r):
            val = 0
            for bit_idx in range(self.w):
                if (mask >> bit_idx) & 1:
                    c = start + bit_idx
                    if c < self.num_slots:
                        val ^= self.sol[c][b]
            if val != sig[b]:
                return False
        return True

    def memory_bits(self):
        return self.num_slots * self.r

def main():
    raw = sys.stdin.read()
    if not raw.strip():
        return

    data = json.loads(raw)
    config = data.get("config", {})
    bloom_bpk = config.get("bloom_bits_per_key", 10)
    bloom_hashes = config.get("bloom_num_hashes", 7)
    ribbon_width = config.get("ribbon_width", 32)
    ribbon_target_bits = config.get("ribbon_target_bits", 7)
    ribbon_slot_ratio = config.get("ribbon_slot_ratio", 1.10)

    inserted_keys = data.get("inserted_keys", [])
    query_keys = data.get("query_keys", [])

    num_keys = len(inserted_keys)

    bloom = BloomFilter(num_keys, bits_per_key=bloom_bpk, num_hashes=bloom_hashes)
    for k in inserted_keys:
        bloom.insert(k)

    ribbon = RibbonFilter(num_keys, width=ribbon_width, target_bits=ribbon_target_bits, slot_ratio=ribbon_slot_ratio)
    ribbon.construct(inserted_keys)

    bloom_bits = bloom.memory_bits()
    ribbon_bits = ribbon.memory_bits()
    mem_savings = round(((bloom_bits - ribbon_bits) / bloom_bits * 100.0), 2)

    inserted_set = set(inserted_keys)
    actual_positives = 0
    actual_negatives = 0

    bloom_false_positives = 0
    ribbon_false_positives = 0

    for qk in query_keys:
        b_res = bloom.query(qk)
        r_res = ribbon.query(qk)
        is_actual = qk in inserted_set

        if is_actual:
            actual_positives += 1
        else:
            actual_negatives += 1
            if b_res: bloom_false_positives += 1
            if r_res: ribbon_false_positives += 1

    bloom_fpr = round((bloom_false_positives / actual_negatives * 100.0), 2) if actual_negatives > 0 else 0.0
    ribbon_fpr = round((ribbon_false_positives / actual_negatives * 100.0), 2) if actual_negatives > 0 else 0.0

    output = {
        "keys_count": num_keys,
        "queries_count": len(query_keys),
        "memory_comparison": {
            "bloom_bits": bloom_bits,
            "ribbon_bits": ribbon_bits,
            "bits_per_key_bloom": round(bloom_bits / num_keys, 2) if num_keys > 0 else 0.0,
            "bits_per_key_ribbon": round(ribbon_bits / num_keys, 2) if num_keys > 0 else 0.0,
            "memory_savings_pct": mem_savings
        },
        "query_performance": {
            "actual_positives": actual_positives,
            "actual_negatives": actual_negatives,
            "bloom_false_positives": bloom_false_positives,
            "ribbon_false_positives": ribbon_false_positives,
            "bloom_fpr_pct": bloom_fpr,
            "ribbon_fpr_pct": ribbon_fpr
        }
    }
    print(json.dumps(output, ensure_ascii=False))

if __name__ == "__main__":
    main()
