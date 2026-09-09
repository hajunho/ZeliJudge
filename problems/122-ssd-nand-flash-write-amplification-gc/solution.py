import sys

class Page:
    def __init__(self):
        self.status = "FREE" # FREE, VALID, INVALID
        self.lpa = None
        self.data = None

class Block:
    def __init__(self, block_id, pages_per_block):
        self.id = block_id
        self.pages_per_block = pages_per_block
        self.pages = [Page() for _ in range(pages_per_block)]
        self.erase_count = 0

    def is_completely_free(self):
        return all(p.status == "FREE" for p in self.pages)

    def invalid_count(self):
        return sum(1 for p in self.pages if p.status == "INVALID")

    def valid_count(self):
        return sum(1 for p in self.pages if p.status == "VALID")

    def erase(self):
        for p in self.pages:
            p.status = "FREE"
            p.lpa = None
            p.data = None
        self.erase_count += 1

class SSDSimulator:
    def __init__(self):
        self.reset()

    def reset(self):
        self.pages_per_block = 4
        self.total_blocks = 8
        self.op_pct = 25
        self.gc_threshold = 1

        self.blocks = [Block(i, self.pages_per_block) for i in range(self.total_blocks)]
        self.mapping_table = {} # lpa -> (block_id, page_offset)
        self.active_block_id = None
        self.active_page_offset = 0

        self.user_writes = 0
        self.gc_writes = 0
        self.total_erases = 0

    def config(self, pages_per_block=None, total_blocks=None, op_pct=None, gc_threshold=None):
        if pages_per_block is not None:
            self.pages_per_block = int(pages_per_block)
        if total_blocks is not None:
            self.total_blocks = int(total_blocks)
        if op_pct is not None:
            self.op_pct = int(op_pct)
        if gc_threshold is not None:
            self.gc_threshold = int(gc_threshold)

        self.blocks = [Block(i, self.pages_per_block) for i in range(self.total_blocks)]
        self.mapping_table.clear()
        self.active_block_id = None
        self.active_page_offset = 0
        self.user_writes = 0
        self.gc_writes = 0
        self.total_erases = 0

        return f"OK pages_per_block={self.pages_per_block} total_blocks={self.total_blocks} op_pct={self.op_pct} gc_threshold={self.gc_threshold}"

    def count_free_blocks(self):
        return sum(1 for b in self.blocks if b.is_completely_free())

    def allocate_free_block(self):
        for b in self.blocks:
            if b.is_completely_free():
                return b.id
        return None

    def trigger_gc(self):
        outputs = []
        # Choose victim block with most INVALID pages, not the current active block
        best_victim = None
        max_invalid = -1

        for b in self.blocks:
            if b.id == self.active_block_id:
                continue
            inv = b.invalid_count()
            if inv > max_invalid:
                max_invalid = inv
                best_victim = b

        if best_victim is None or max_invalid <= 0:
            return outputs

        victim_id = best_victim.id
        inv_cnt = best_victim.invalid_count()
        val_cnt = best_victim.valid_count()

        outputs.append(f"GC_TRIGGERED victim_block={victim_id} invalid_pages={inv_cnt} valid_pages_copied={val_cnt}")

        # Relocate valid pages
        for idx, p in enumerate(best_victim.pages):
            if p.status == "VALID":
                # Write to active block
                if self.active_block_id is None or self.active_page_offset >= self.pages_per_block:
                    new_b = self.allocate_free_block()
                    if new_b is not None:
                        self.active_block_id = new_b
                        self.active_page_offset = 0

                target_b = self.blocks[self.active_block_id]
                target_p = target_b.pages[self.active_page_offset]
                target_p.status = "VALID"
                target_p.lpa = p.lpa
                target_p.data = p.data

                self.mapping_table[p.lpa] = (self.active_block_id, self.active_page_offset)
                self.active_page_offset += 1
                self.gc_writes += 1

        # Erase victim block
        best_victim.erase()
        self.total_erases += 1
        outputs.append(f"BLOCK_ERASED block={victim_id} erase_count={best_victim.erase_count}")

        return outputs

    def write(self, lpa, data):
        outputs = []
        lpa = int(lpa)
        self.user_writes += 1

        # 1. Invalidate old page if mapped
        if lpa in self.mapping_table:
            old_b_id, old_p_idx = self.mapping_table[lpa]
            self.blocks[old_b_id].pages[old_p_idx].status = "INVALID"

        # 2. Check active block capacity
        if self.active_block_id is None or self.active_page_offset >= self.pages_per_block:
            # Need a new active block
            if self.count_free_blocks() <= self.gc_threshold:
                gc_outs = self.trigger_gc()
                outputs.extend(gc_outs)

            new_b = self.allocate_free_block()
            if new_b is None:
                # Need GC again if still none
                gc_outs = self.trigger_gc()
                outputs.extend(gc_outs)
                new_b = self.allocate_free_block()

            self.active_block_id = new_b
            self.active_page_offset = 0

        # 3. Write to active page
        block = self.blocks[self.active_block_id]
        page = block.pages[self.active_page_offset]
        page.status = "VALID"
        page.lpa = lpa
        page.data = data

        self.mapping_table[lpa] = (self.active_block_id, self.active_page_offset)
        outputs.append(f"WRITE_OK lpa={lpa} ppa=(block={self.active_block_id},page={self.active_page_offset}) data={data}")
        self.active_page_offset += 1

        return outputs

    def trim(self, lpa):
        lpa = int(lpa)
        if lpa in self.mapping_table:
            b_id, p_idx = self.mapping_table[lpa]
            self.blocks[b_id].pages[p_idx].status = "INVALID"
            del self.mapping_table[lpa]
            return f"TRIM_OK lpa={lpa} ppa=(block={b_id},page={p_idx}) status=INVALIDATED"
        else:
            return f"TRIM_SKIPPED lpa={lpa} status=NOT_MAPPED"

    def dump(self):
        lines = []
        for b in self.blocks:
            chars = []
            for p in b.pages:
                if p.status == "VALID":
                    chars.append("V")
                elif p.status == "INVALID":
                    chars.append("I")
                else:
                    chars.append("F")
            lines.append(f"BLOCK {b.id}: erase={b.erase_count} [{','.join(chars)}]")
        return lines

    def stats(self):
        total_w = self.user_writes + self.gc_writes
        waf = total_w / max(1, self.user_writes)
        return f"STATS user_writes={self.user_writes} gc_writes={self.gc_writes} total_writes={total_w} waf={waf:.2f} total_erases={self.total_erases}"

def main():
    sim = SSDSimulator()

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
                pages_per_block=params.get('pages_per_block'),
                total_blocks=params.get('total_blocks'),
                op_pct=params.get('op_pct'),
                gc_threshold=params.get('gc_threshold')
            ))

        elif cmd == "WRITE":
            lines = sim.write(
                lpa=params.get('lpa'),
                data=params.get('data', '')
            )
            for out in lines:
                print(out)

        elif cmd == "TRIM":
            print(sim.trim(lpa=params.get('lpa')))

        elif cmd == "DUMP":
            for out in sim.dump():
                print(out)

        elif cmd == "STATS":
            print(sim.stats())

        elif cmd == "RESET":
            sim.reset()
            print("OK pages_per_block=4 total_blocks=8 op_pct=25")

if __name__ == '__main__':
    main()
