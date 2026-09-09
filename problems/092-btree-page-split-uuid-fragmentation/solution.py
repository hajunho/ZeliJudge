import sys
from collections import OrderedDict

def parse_key(k_str):
    if k_str.isdigit() or (k_str.startswith('-') and len(k_str) > 1 and k_str[1:].isdigit()):
        return (0, int(k_str), k_str)
    return (1, 0, k_str)

def key_less(k1, k2):
    return parse_key(k1) < parse_key(k2)

class LeafPage:
    def __init__(self, page_id, records=None, high_key=None, is_dirty=False):
        self.id = page_id
        self.records = records if records is not None else []
        self.high_key = high_key  # Exclusive upper bound (None means +infinity)
        self.is_dirty = is_dirty

class BTreeEngine:
    def __init__(self):
        self.page_capacity = 4
        self.buffer_pool_capacity = 3
        self.pages = {}
        self.page_order = []
        self.next_page_id = 0
        self.buffer_pool = OrderedDict()
        self.page_splits = 0
        self.disk_read_count = 0
        self.disk_write_count = 0
        self.cache_hits = 0
        self.cache_misses = 0

    def init(self, page_cap, pool_cap):
        self.page_capacity = page_cap
        self.buffer_pool_capacity = pool_cap
        self.pages = {}
        self.page_order = [0]
        self.pages[0] = LeafPage(0, records=[], high_key=None, is_dirty=False)
        self.next_page_id = 1
        self.buffer_pool = OrderedDict()
        self.buffer_pool[0] = False
        self.page_splits = 0
        self.disk_read_count = 0
        self.disk_write_count = 0
        self.cache_hits = 0
        self.cache_misses = 0
        return f"INIT_OK page_cap={page_cap} pool_cap={pool_cap}"

    def _ensure_buffer_space(self):
        if len(self.buffer_pool) >= self.buffer_pool_capacity:
            evicted_id, is_dirty = self.buffer_pool.popitem(last=False)
            if is_dirty:
                self.disk_write_count += 1
                if evicted_id in self.pages:
                    self.pages[evicted_id].is_dirty = False

    def access_page(self, page_id):
        if page_id in self.buffer_pool:
            self.cache_hits += 1
            self.buffer_pool.move_to_end(page_id)
            return "HIT"
        else:
            self.cache_misses += 1
            self.disk_read_count += 1
            self._ensure_buffer_space()
            self.buffer_pool[page_id] = False
            return "MISS"

    def find_leaf_page(self, key):
        for p_id in self.page_order:
            page = self.pages[p_id]
            if page.high_key is None:
                return page
            if key_less(key, page.high_key):
                return page
        return self.pages[self.page_order[-1]]

    def insert(self, key, value):
        page = self.find_leaf_page(key)
        cache_status = self.access_page(page.id)

        # Check for duplicate key
        for existing_k, _ in page.records:
            if existing_k == key:
                return f"PAGE:{page.id} ERROR:DUPLICATE_KEY CACHE:{cache_status}"

        if len(page.records) < self.page_capacity:
            # Insert in sorted order
            inserted = False
            for i, (k, v) in enumerate(page.records):
                if key_less(key, k):
                    page.records.insert(i, (key, value))
                    inserted = True
                    break
            if not inserted:
                page.records.append((key, value))

            page.is_dirty = True
            self.buffer_pool[page.id] = True
            return f"PAGE:{page.id} STATUS:INSERTED CACHE:{cache_status}"

        # Page is full: Page Split
        self.page_splits += 1

        # Combine all records
        combined = list(page.records)
        inserted = False
        for i, (k, v) in enumerate(combined):
            if key_less(key, k):
                combined.insert(i, (key, value))
                inserted = True
                break
        if not inserted:
            combined.append((key, value))

        # Check Right-Append Optimization
        is_rightmost = (page.id == self.page_order[-1])
        is_strictly_greater = key_less(page.records[-1][0], key)

        if is_rightmost and is_strictly_greater:
            # Right split: keep original records in page, put only the new record in new_page
            split_type = "SPLIT_RIGHT"
            page.records = combined[:-1]
            new_records = [combined[-1]]
            sep = new_records[0][0]
            target_page_id = self.next_page_id
        else:
            # 50/50 Balanced split
            split_type = "SPLIT_BALANCED"
            mid = (len(combined) + 1) // 2
            page.records = combined[:mid]
            new_records = combined[mid:]
            sep = new_records[0][0]
            if key_less(key, sep):
                target_page_id = page.id
            else:
                target_page_id = self.next_page_id

        # Allocate new page
        new_id = self.next_page_id
        self.next_page_id += 1

        old_high_key = page.high_key
        page.high_key = sep
        new_page = LeafPage(new_id, records=new_records, high_key=old_high_key, is_dirty=True)
        self.pages[new_id] = new_page

        # Insert new_page in leaf order immediately after page
        idx = self.page_order.index(page.id)
        self.page_order.insert(idx + 1, new_id)

        # Mark both dirty and place new page in buffer pool
        page.is_dirty = True
        self.buffer_pool[page.id] = True

        self._ensure_buffer_space()
        self.buffer_pool[new_id] = True

        return f"PAGE:{target_page_id} STATUS:{split_type} CACHE:{cache_status}"

    def range_query(self, start_key, end_key):
        start_page = self.find_leaf_page(start_key)
        start_idx = self.page_order.index(start_page.id)

        matched_count = 0
        pages_visited = 0

        for i in range(start_idx, len(self.page_order)):
            p_id = self.page_order[i]
            self.access_page(p_id)
            pages_visited += 1
            page = self.pages[p_id]

            for k, v in page.records:
                if not key_less(k, start_key) and not key_less(end_key, k):
                    matched_count += 1

            if page.high_key is not None and key_less(end_key, page.high_key):
                break

        return f"RANGE count={matched_count} pages_visited={pages_visited}"

    def optimize(self):
        all_records = []
        for p_id in self.page_order:
            all_records.extend(self.pages[p_id].records)

        old_pages_count = len(self.page_order)
        total_records = len(all_records)
        num_pages = max(1, (total_records + self.page_capacity - 1) // self.page_capacity)

        # Writing out new pages to disk
        self.disk_write_count += num_pages

        new_pages = {}
        new_page_order = list(range(num_pages))
        for i in range(num_pages):
            chunk = all_records[i * self.page_capacity : (i + 1) * self.page_capacity]
            high_k = None
            if (i + 1) * self.page_capacity < total_records:
                high_k = all_records[(i + 1) * self.page_capacity][0]
            new_pages[i] = LeafPage(i, records=chunk, high_key=high_k, is_dirty=False)

        self.pages = new_pages
        self.page_order = new_page_order
        self.next_page_id = num_pages

        # Reset buffer pool and load first pages
        self.buffer_pool.clear()
        for i in range(min(num_pages, self.buffer_pool_capacity)):
            self.buffer_pool[i] = False

        saved_pages = old_pages_count - num_pages
        new_total_cap = num_pages * self.page_capacity
        new_fill = (total_records / new_total_cap * 100.0) if new_total_cap > 0 else 100.0

        return f"OPTIMIZE_OK old_pages={old_pages_count} new_pages={num_pages} saved_pages={saved_pages} new_fill={new_fill:.1f}%"

    def stats(self):
        total_pages = len(self.page_order)
        total_records = sum(len(self.pages[pid].records) for pid in self.page_order)
        page_splits = self.page_splits
        total_cap = total_pages * self.page_capacity
        fill_factor = (total_records / total_cap * 100.0) if total_cap > 0 else 100.0
        fragmentation = 100.0 - fill_factor

        total_cache = self.cache_hits + self.cache_misses
        hit_rate = (self.cache_hits / total_cache * 100.0) if total_cache > 0 else 0.0
        disk_io = self.disk_read_count + self.disk_write_count

        if total_pages <= 1:
            health = "OPTIMAL"
        elif fill_factor >= 80.0 and (total_cache == 0 or hit_rate >= 70.0):
            health = "OPTIMAL"
        elif fill_factor < 70.0 or fragmentation > 30.0:
            health = "FRAGMENTED"
        else:
            health = "NORMAL"

        return f"STATS pages={total_pages} records={total_records} splits={page_splits} fill={fill_factor:.1f}% frag={fragmentation:.1f}% hit_rate={hit_rate:.1f}% disk_io={disk_io} health={health}"

def main():
    engine = BTreeEngine()
    lines = sys.stdin.read().splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        cmd = parts[0].upper()

        if cmd == "INIT":
            page_cap = int(parts[1])
            pool_cap = int(parts[2])
            print(engine.init(page_cap, pool_cap))
        elif cmd == "INSERT":
            key = parts[1]
            val = parts[2] if len(parts) > 2 else ""
            print(engine.insert(key, val))
        elif cmd == "RANGE":
            start_k = parts[1]
            end_k = parts[2]
            print(engine.range_query(start_k, end_k))
        elif cmd == "OPTIMIZE":
            print(engine.optimize())
        elif cmd == "STATS":
            print(engine.stats())

if __name__ == '__main__':
    main()
