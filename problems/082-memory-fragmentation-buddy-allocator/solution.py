import sys

class BuddyAllocator:
    def __init__(self, total_size: int):
        self.total_size = total_size
        self.free_lists = {}
        size = 1
        while size <= total_size:
            self.free_lists[size] = set()
            size *= 2
        self.free_lists[total_size].add(0)
        self.allocated = {}  # req_id -> (addr, block_size, requested_size)

    def _next_power_of_two(self, n: int) -> int:
        if n <= 1:
            return 1
        return 1 << (n - 1).bit_length()

    def alloc(self, req_id: str, size: int):
        if req_id in self.allocated:
            return None
        target_size = self._next_power_of_two(size)
        if target_size > self.total_size:
            return None

        # Find the smallest available block of size >= target_size
        current_size = target_size
        while current_size <= self.total_size:
            if self.free_lists[current_size]:
                break
            current_size *= 2

        if current_size > self.total_size:
            return None  # OOM

        # Pick the lowest address block for determinism
        addr = min(self.free_lists[current_size])
        self.free_lists[current_size].remove(addr)

        # Split down to target_size
        while current_size > target_size:
            current_size //= 2
            buddy_addr = addr + current_size
            self.free_lists[current_size].add(buddy_addr)

        self.allocated[req_id] = (addr, target_size, size)
        return (addr, target_size)

    def free(self, req_id: str):
        if req_id not in self.allocated:
            return None

        addr, block_size, _ = self.allocated.pop(req_id)
        current_addr = addr
        current_size = block_size
        merges = 0

        while current_size < self.total_size:
            buddy_addr = current_addr ^ current_size
            if buddy_addr in self.free_lists[current_size]:
                self.free_lists[current_size].remove(buddy_addr)
                current_addr = min(current_addr, buddy_addr)
                current_size *= 2
                merges += 1
            else:
                break

        self.free_lists[current_size].add(current_addr)
        return merges

    def get_status(self) -> str:
        total = self.total_size
        used = sum(b_size for _, b_size, _ in self.allocated.values())
        free_mem = total - used

        avail_sizes = [s for s, addrs in self.free_lists.items() if len(addrs) > 0]
        max_contig = max(avail_sizes, default=0)

        if free_mem == 0:
            frag_ratio = 0.0
        else:
            frag_ratio = (1.0 - (max_contig / free_mem)) * 100.0

        free_blocks_summary = {s: len(self.free_lists[s]) for s in sorted(self.free_lists.keys()) if self.free_lists[s]}

        lines = [
            f"TOTAL_MEMORY: {total}",
            f"USED_MEMORY: {used}",
            f"FREE_MEMORY: {free_mem}",
            f"MAX_CONTIGUOUS_FREE: {max_contig}",
            f"FRAGMENTATION_RATIO: {frag_ratio:.2f}%",
            f"FREE_BLOCKS: {free_blocks_summary}"
        ]
        return "\n".join(lines)

def run():
    input_data = sys.stdin.read().splitlines()
    allocator = None
    output = []

    for line in input_data:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split()
        cmd = parts[0]

        if cmd == "INIT":
            total_size = int(parts[1])
            allocator = BuddyAllocator(total_size)
            output.append(f"INITIALIZED MEMORY_SIZE={total_size}")

        elif cmd == "ALLOC":
            req_id = parts[1]
            size = int(parts[2])
            res = allocator.alloc(req_id, size)
            if res is None:
                output.append(f"ALLOC_FAILED {req_id} (OOM)")
            else:
                addr, b_size = res
                output.append(f"ALLOCATED {req_id} ADDR={addr} BLOCK_SIZE={b_size}")

        elif cmd == "FREE":
            req_id = parts[1]
            res = allocator.free(req_id)
            if res is None:
                output.append(f"FREE_FAILED {req_id}")
            else:
                output.append(f"FREED {req_id} (MERGES: {res})")

        elif cmd == "STATUS":
            output.append(allocator.get_status())

    print("\n".join(output))

if __name__ == "__main__":
    run()
