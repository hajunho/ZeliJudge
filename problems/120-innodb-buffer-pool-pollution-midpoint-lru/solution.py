import sys

class BufferPoolSimulator:
    def __init__(self):
        self.reset()

    def reset(self):
        self.mode = "STANDARD_LRU"
        self.capacity = 10
        self.old_pct = 37
        self.old_blocks_time_ms = 1000

        # STANDARD_LRU state
        self.standard_pages = [] # [0] is Head (MRU), [-1] is Tail (LRU)

        # MIDPOINT_LRU state
        self.young_pages = []
        self.old_pages = []
        self.first_access = {} # page -> int (timestamp_ms)

        # Statistics
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.promotions = 0

    def config(self, mode=None, capacity=None, old_pct=None, old_blocks_time_ms=None):
        if mode:
            self.mode = mode
        if capacity is not None:
            self.capacity = int(capacity)
        if old_pct is not None:
            self.old_pct = int(old_pct)
        if old_blocks_time_ms is not None:
            self.old_blocks_time_ms = int(old_blocks_time_ms)
        return f"OK mode={self.mode} capacity={self.capacity} old_pct={self.old_pct} old_blocks_time_ms={self.old_blocks_time_ms}"

    def read(self, page, now=0):
        now_ms = int(now)
        evicted = "none"

        if self.mode == "STANDARD_LRU":
            if page in self.standard_pages:
                self.hits += 1
                self.standard_pages.remove(page)
                self.standard_pages.insert(0, page)
                return f"READ_RESULT page={page} action=CACHE_HIT evicted=none"
            else:
                self.misses += 1
                if len(self.standard_pages) >= self.capacity:
                    evicted = self.standard_pages.pop()
                    self.evictions += 1
                self.standard_pages.insert(0, page)
                return f"READ_RESULT page={page} action=CACHE_MISS evicted={evicted}"

        elif self.mode == "MIDPOINT_LRU":
            old_capacity = max(1, int(self.capacity * self.old_pct / 100))
            young_capacity = self.capacity - old_capacity

            # Case 1: Page is in Young Sublist
            if page in self.young_pages:
                self.hits += 1
                self.young_pages.remove(page)
                self.young_pages.insert(0, page)
                return f"READ_RESULT page={page} action=CACHE_HIT sublist=YOUNG promoted=false evicted=none"

            # Case 2: Page is in Old Sublist
            elif page in self.old_pages:
                self.hits += 1
                delta_ms = now_ms - self.first_access.get(page, now_ms)
                if delta_ms >= self.old_blocks_time_ms:
                    # Time window satisfied -> Promote to Young!
                    self.promotions += 1
                    self.old_pages.remove(page)
                    if page in self.first_access:
                        del self.first_access[page]
                    self.young_pages.insert(0, page)

                    # If Young overflows, demote Young tail to Old head
                    if len(self.young_pages) > young_capacity:
                        demoted = self.young_pages.pop()
                        self.old_pages.insert(0, demoted)
                        self.first_access[demoted] = now_ms
                        if len(self.old_pages) > old_capacity:
                            evicted = self.old_pages.pop()
                            if evicted in self.first_access:
                                del self.first_access[evicted]
                            self.evictions += 1

                    return f"READ_RESULT page={page} action=CACHE_HIT sublist=YOUNG promoted=true evicted={evicted}"
                else:
                    # Sequential table scan defense -> Touch within Old, no promotion!
                    self.old_pages.remove(page)
                    self.old_pages.insert(0, page)
                    return f"READ_RESULT page={page} action=CACHE_HIT sublist=OLD promoted=false evicted=none"

            # Case 3: Page is not in cache (Cache Miss)
            else:
                self.misses += 1
                self.first_access[page] = now_ms
                self.old_pages.insert(0, page)

                # Evict from Old tail if total exceeds capacity
                if len(self.young_pages) + len(self.old_pages) > self.capacity:
                    evicted = self.old_pages.pop()
                    if evicted in self.first_access:
                        del self.first_access[evicted]
                    self.evictions += 1

                return f"READ_RESULT page={page} action=CACHE_MISS sublist=OLD promoted=false evicted={evicted}"

        return "ERROR unknown_mode"

    def dump(self):
        if self.mode == "STANDARD_LRU":
            pages_str = f"[{','.join(self.standard_pages)}]"
            return f"BUFFER_POOL pages={pages_str}"
        else:
            young_str = f"[{','.join(self.young_pages)}]"
            old_str = f"[{','.join(self.old_pages)}]"
            return f"BUFFER_POOL young={young_str} old={old_str}"

    def stats(self):
        return f"STATS hits={self.hits} misses={self.misses} evictions={self.evictions} promotions={self.promotions}"

def main():
    sim = BufferPoolSimulator()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        parts = line.split()
        cmd = parts[0]
        params = {}
        for p in parts[1:]:
            if '=' in p:
                k, v = p.split('=', 1)
                params[k] = v

        if cmd == "CONFIG":
            print(sim.config(
                mode=params.get('mode'),
                capacity=params.get('capacity'),
                old_pct=params.get('old_pct'),
                old_blocks_time_ms=params.get('old_blocks_time_ms')
            ))

        elif cmd == "READ":
            print(sim.read(
                page=params.get('page'),
                now=params.get('now', 0)
            ))

        elif cmd == "DUMP":
            print(sim.dump())

        elif cmd == "STATS":
            print(sim.stats())

        elif cmd == "RESET":
            sim.reset()
            print("OK mode=STANDARD_LRU capacity=10 old_pct=37 old_blocks_time_ms=1000")

if __name__ == '__main__':
    main()
