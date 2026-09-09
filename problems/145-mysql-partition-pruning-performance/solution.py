import sys

class PartitionPruningSim:
    def __init__(self, partitions):
        # partitions: list of (p_name, low, high, row_count)
        self.partitions = partitions
        self.total_rows = sum(p[3] for p in partitions)
        self.total_queries = 0
        self.pruned_queries = 0
        self.failed_queries = 0
        self.total_scanned_rows = 0
        self.total_saved_rows = 0

    def query(self, q_type, args):
        self.total_queries += 1
        P = len(self.partitions)
        accessed_partitions = []
        
        if q_type == "POINT":
            val = int(args[0])
            for p_name, low, high, cnt in self.partitions:
                if low <= val < high:
                    accessed_partitions.append((p_name, cnt))
            self.pruned_queries += 1
        elif q_type == "RANGE":
            q_low = int(args[0])
            q_high = int(args[1])
            for p_name, low, high, cnt in self.partitions:
                if max(low, q_low) < min(high, q_high):
                    accessed_partitions.append((p_name, cnt))
            self.pruned_queries += 1
        elif q_type == "FUNCTION_EXPRESSION":
            accessed_partitions = [(p[0], p[3]) for p in self.partitions]
            self.failed_queries += 1
        elif q_type == "NO_PARTITION_KEY":
            accessed_partitions = [(p[0], p[3]) for p in self.partitions]
            self.failed_queries += 1
            
        scanned_rows = sum(p[1] for p in accessed_partitions)
        saved_rows = self.total_rows - scanned_rows
        self.total_scanned_rows += scanned_rows
        self.total_saved_rows += saved_rows

    def summary(self):
        return f"TOTAL_QUERIES: {self.total_queries} PRUNED: {self.pruned_queries} FAILED: {self.failed_queries} SCANNED_ROWS: {self.total_scanned_rows} SAVED_ROWS: {self.total_saved_rows}"

def solve():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    p_num = int(lines[0].strip())
    partitions = []
    line_idx = 1
    for _ in range(p_num):
        parts = lines[line_idx].strip().split()
        p_name = parts[0]
        low = int(parts[1])
        high = 10**9 if parts[2].upper() == 'INF' else int(parts[2])
        row_cnt = int(parts[3])
        partitions.append((p_name, low, high, row_cnt))
        line_idx += 1
        
    sim = PartitionPruningSim(partitions)
    q_num = int(lines[line_idx].strip())
    line_idx += 1
    
    for _ in range(q_num):
        if line_idx < len(lines):
            q_parts = lines[line_idx].strip().split()
            q_type = q_parts[0]
            args = q_parts[1:]
            sim.query(q_type, args)
            line_idx += 1
            
    print(sim.summary())

if __name__ == '__main__':
    solve()
