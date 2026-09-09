import sys
import bisect
import fnmatch

def extract_trigrams(word):
    # Padding with special markers for boundary matching
    padded = f"${word}$"
    trigrams = set()
    for i in range(len(padded) - 2):
        trigrams.add(padded[i:i+3])
    return trigrams

class Table:
    def __init__(self, name, rows):
        self.name = name
        self.rows = rows  # list of strings
        self.indexes = {}  # name -> (type, index_data)

class DatabaseSimulator:
    def __init__(self):
        self.tables = {}

    def load_table(self, table_name, items_str):
        if not items_str.strip():
            rows = []
        else:
            rows = [x.strip() for x in items_str.split(',') if x.strip()]
        self.tables[table_name] = Table(table_name, rows)
        return f"LOAD_TABLE_OK table={table_name} rows={len(rows)}"

    def create_index(self, index_name, table_name, index_type):
        if table_name not in self.tables:
            return f"ERROR:UNKNOWN_TABLE table={table_name}"
        table = self.tables[table_name]
        idx_type = index_type.upper()

        if idx_type == "BTREE":
            # Store sorted list of (word, row_idx)
            indexed_data = sorted([(w, i) for i, w in enumerate(table.rows)], key=lambda x: x[0])
            table.indexes[index_name] = ("BTREE", indexed_data)
        elif idx_type == "REVERSE_BTREE":
            # Store sorted list of (reversed_word, row_idx)
            indexed_data = sorted([(w[::-1], i) for i, w in enumerate(table.rows)], key=lambda x: x[0])
            table.indexes[index_name] = ("REVERSE_BTREE", indexed_data)
        elif idx_type == "TRIGRAM":
            # Map trigram -> set of row_idx
            trigram_map = {}
            for i, w in enumerate(table.rows):
                for tg in extract_trigrams(w):
                    if tg not in trigram_map:
                        trigram_map[tg] = set()
                    trigram_map[tg].add(i)
            table.indexes[index_name] = ("TRIGRAM", trigram_map)
        else:
            return f"ERROR:INVALID_INDEX_TYPE type={index_type}"

        return f"CREATE_INDEX_OK name={index_name} type={idx_type}"

    def explain_query(self, table_name, pattern):
        if table_name not in self.tables:
            return f"ERROR:UNKNOWN_TABLE table={table_name}"
        table = self.tables[table_name]
        n_rows = len(table.rows)

        # Classify pattern
        is_exact = not ('%' in pattern)
        is_prefix = pattern.endswith('%') and not pattern.startswith('%') and pattern.count('%') == 1
        is_suffix = pattern.startswith('%') and not pattern.endswith('%') and pattern.count('%') == 1
        is_infix = pattern.startswith('%') and pattern.endswith('%') and pattern.count('%') == 2

        # Check matched rows using python fnmatch
        py_glob = pattern.replace('%', '*')
        matches = [w for w in table.rows if fnmatch.fnmatchcase(w, py_glob)]
        matched_count = len(matches)

        # Decide plan based on available indexes
        # 1. Exact Match
        if is_exact:
            btree_idx = next((name for name, (t, _) in table.indexes.items() if t == "BTREE"), None)
            if btree_idx:
                return f"EXPLAIN_RESULT table={table_name} pattern={pattern} scan_type=INDEX_SEEK index_used={btree_idx} scanned_rows={matched_count} matched_rows={matched_count}"
            else:
                return f"EXPLAIN_RESULT table={table_name} pattern={pattern} scan_type=FULL_TABLE_SCAN index_used=NONE scanned_rows={n_rows} matched_rows={matched_count}"

        # 2. Prefix Match (apple%)
        if is_prefix:
            btree_idx = next((name for name, (t, _) in table.indexes.items() if t == "BTREE"), None)
            if btree_idx:
                # BTree Range Scan scans only the matching range!
                return f"EXPLAIN_RESULT table={table_name} pattern={pattern} scan_type=INDEX_RANGE_SCAN index_used={btree_idx} scanned_rows={matched_count} matched_rows={matched_count}"
            else:
                return f"EXPLAIN_RESULT table={table_name} pattern={pattern} scan_type=FULL_TABLE_SCAN index_used=NONE scanned_rows={n_rows} matched_rows={matched_count}"

        # 3. Suffix Match (%apple)
        if is_suffix:
            rev_idx = next((name for name, (t, _) in table.indexes.items() if t == "REVERSE_BTREE"), None)
            if rev_idx:
                return f"EXPLAIN_RESULT table={table_name} pattern={pattern} scan_type=INDEX_RANGE_SCAN index_used={rev_idx} scanned_rows={matched_count} matched_rows={matched_count}"
            else:
                return f"EXPLAIN_RESULT table={table_name} pattern={pattern} scan_type=FULL_TABLE_SCAN index_used=NONE scanned_rows={n_rows} matched_rows={matched_count}"

        # 4. Infix Match (%apple%)
        if is_infix:
            trgm_idx = next((name for name, (t, _) in table.indexes.items() if t == "TRIGRAM"), None)
            if trgm_idx:
                # Trigram GIN index: scan candidates matching trigrams
                raw_keyword = pattern[1:-1]
                target_tgs = extract_trigrams(raw_keyword)
                trigram_map = table.indexes[trgm_idx][1]
                candidate_ids = None
                for tg in target_tgs:
                    if tg in trigram_map:
                        if candidate_ids is None:
                            candidate_ids = set(trigram_map[tg])
                        else:
                            candidate_ids &= trigram_map[tg]
                    else:
                        candidate_ids = set()
                        break
                scanned_rows = len(candidate_ids) if candidate_ids is not None else 0
                return f"EXPLAIN_RESULT table={table_name} pattern={pattern} scan_type=BITMAP_INDEX_SCAN index_used={trgm_idx} scanned_rows={scanned_rows} matched_rows={matched_count}"
            else:
                # BTree CANNOT be used due to Leftmost Prefix Rule!
                return f"EXPLAIN_RESULT table={table_name} pattern={pattern} scan_type=FULL_TABLE_SCAN index_used=NONE scanned_rows={n_rows} matched_rows={matched_count}"

        # Fallback
        return f"EXPLAIN_RESULT table={table_name} pattern={pattern} scan_type=FULL_TABLE_SCAN index_used=NONE scanned_rows={n_rows} matched_rows={matched_count}"

    def search(self, table_name, pattern):
        if table_name not in self.tables:
            return f"ERROR:UNKNOWN_TABLE table={table_name}"
        table = self.tables[table_name]
        py_glob = pattern.replace('%', '*')
        matches = sorted([w for w in table.rows if fnmatch.fnmatchcase(w, py_glob)])
        matches_repr = ", ".join(matches)
        return f"SEARCH_OK pattern={pattern} count={len(matches)} matches=[{matches_repr}]"

    def stats(self, table_name):
        if table_name not in self.tables:
            return f"ERROR:UNKNOWN_TABLE table={table_name}"
        table = self.tables[table_name]
        idx_strs = [f"{name}:{t}" for name, (t, _) in sorted(table.indexes.items())]
        indexes_repr = ", ".join(idx_strs)
        return f"STATS table={table_name} total_rows={len(table.rows)} indexes=[{indexes_repr}]"

def main():
    db = DatabaseSimulator()
    lines = sys.stdin.read().splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split(maxsplit=2)
        cmd = parts[0].upper()

        if cmd == "LOAD_TABLE":
            tname = parts[1]
            items = parts[2] if len(parts) > 2 else ""
            print(db.load_table(tname, items))
        elif cmd == "CREATE_INDEX":
            p = line.split()
            print(db.create_index(p[1], p[2], p[3]))
        elif cmd == "EXPLAIN_QUERY":
            p = line.split()
            print(db.explain_query(p[1], p[2]))
        elif cmd == "SEARCH":
            p = line.split()
            print(db.search(p[1], p[2]))
        elif cmd == "STATS":
            p = line.split()
            print(db.stats(p[1]))

if __name__ == '__main__':
    main()
