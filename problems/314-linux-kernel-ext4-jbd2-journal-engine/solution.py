import sys
import os
import json
import binascii

# JBD2 Block Magic & Types
JBD2_MAGIC_NUMBER = 0xC03B3998
JBD2_DESCRIPTOR_BLOCK = 1
JBD2_COMMIT_BLOCK     = 2
JBD2_SUPERBLOCK_V1    = 3
JBD2_SUPERBLOCK_V2    = 4
JBD2_REVOKE_BLOCK     = 5

# Transaction States
T_RUNNING    = "T_RUNNING"
T_LOCKED     = "T_LOCKED"
T_COMMIT     = "T_COMMIT"
T_COMMITTED  = "T_COMMITTED"
T_CHECKPOINT = "T_CHECKPOINT"

def crc32_be(data: bytes) -> int:
    return binascii.crc32(data) & 0xFFFFFFFF

class JBD2JournalEngine:
    def __init__(self, config, initial_fs=None):
        self.journal_blocks = config.get("journal_blocks", 32)
        self.journal_mode = config.get("journal_mode", "ordered")
        self.max_tx_blocks = config.get("max_tx_blocks", 8)

        self.fs_storage = {}
        if initial_fs:
            for k, v in initial_fs.items():
                self.fs_storage[int(k)] = v

        self.journal_storage = {}
        self.journal_head = 1
        self.journal_tail = 1
        self.sequence = 1

        self.current_tx = None
        self.checkpoint_list = []
        self.history = []
        self.event_log = []
        self.stats = {
            "transactions_committed": 0,
            "blocks_journaled": 0,
            "blocks_checkpointed": 0,
            "blocks_revoked": 0,
            "recoveries_performed": 0
        }

    def log(self, msg: str):
        self.event_log.append(msg)

    def start_transaction(self) -> int:
        if self.current_tx is not None and self.current_tx["state"] == T_RUNNING:
            return self.current_tx["tid"]
        tid = self.sequence
        self.sequence += 1
        self.current_tx = {
            "tid": tid,
            "state": T_RUNNING,
            "dirty_metadata": {},
            "dirty_data": {},
            "revokes": set()
        }
        self.log(f"JBD2 START_TRANSACTION tid={tid}")
        return tid

    def dirty_buffer(self, block_id: int, data_hex: str, is_metadata: bool = True):
        if self.current_tx is None or self.current_tx["state"] != T_RUNNING:
            self.start_transaction()

        if is_metadata:
            self.current_tx["dirty_metadata"][block_id] = data_hex
            self.log(f"JBD2 DIRTY_METADATA tid={self.current_tx['tid']} block={block_id}")
        else:
            self.current_tx["dirty_data"][block_id] = data_hex
            self.log(f"JBD2 DIRTY_DATA tid={self.current_tx['tid']} block={block_id}")

    def revoke_buffer(self, block_id: int):
        if self.current_tx is None or self.current_tx["state"] != T_RUNNING:
            self.start_transaction()
        self.current_tx["revokes"].add(block_id)
        if block_id in self.current_tx["dirty_metadata"]:
            del self.current_tx["dirty_metadata"][block_id]
        self.stats["blocks_revoked"] += 1
        self.log(f"JBD2 REVOKE_BUFFER tid={self.current_tx['tid']} block={block_id}")

    def get_space_left(self) -> int:
        capacity = self.journal_blocks - 1
        if self.journal_head >= self.journal_tail:
            used = self.journal_head - self.journal_tail
        else:
            used = capacity - (self.journal_tail - self.journal_head)
        return capacity - used

    def commit_transaction(self, corrupt_commit_crc: bool = False, omit_commit_block: bool = False) -> dict:
        if self.current_tx is None or self.current_tx["state"] != T_RUNNING:
            res = {"op": "COMMIT_TX", "status": "NO_RUNNING_TRANSACTION"}
            self.history.append(res)
            return res

        tx = self.current_tx
        tid = tx["tid"]
        tx["state"] = T_LOCKED
        self.log(f"JBD2 T_LOCKED tid={tid}")

        if self.journal_mode == "ordered":
            for b_id, d_hex in tx["dirty_data"].items():
                self.fs_storage[b_id] = d_hex
                self.log(f"JBD2 ORDERED_DATA_FLUSH block={b_id}")
        elif self.journal_mode == "journal":
            for b_id, d_hex in tx["dirty_data"].items():
                tx["dirty_metadata"][b_id] = d_hex

        meta_blocks = list(tx["dirty_metadata"].items())
        revokes = sorted(list(tx["revokes"]))
        blocks_needed = 1 + len(meta_blocks) + (1 if len(revokes) > 0 else 0) + (0 if omit_commit_block else 1)

        while self.get_space_left() < blocks_needed:
            self.log(f"JBD2 JOURNAL_SPACE_LOW head={self.journal_head} tail={self.journal_tail} needed={blocks_needed} left={self.get_space_left()}")
            chk_tid = self.checkpoint_oldest()
            if chk_tid is None:
                res = {"op": "COMMIT_TX", "status": "JOURNAL_EXHAUSTION", "tid": tid}
                self.history.append(res)
                return res

        tx["state"] = T_COMMIT
        slots_written = []

        # 1. Descriptor Block
        desc_slot = self.alloc_journal_slot()
        desc_tags = [b_id for b_id, _ in meta_blocks]
        self.journal_storage[desc_slot] = {
            "type": JBD2_DESCRIPTOR_BLOCK,
            "tid": tid,
            "tags": desc_tags
        }
        slots_written.append(desc_slot)

        # 2. Metadata Blocks
        for b_id, d_hex in meta_blocks:
            slot = self.alloc_journal_slot()
            self.journal_storage[slot] = {
                "type": "DATA",
                "tid": tid,
                "fs_block_id": b_id,
                "data_hex": d_hex
            }
            slots_written.append(slot)
            self.stats["blocks_journaled"] += 1

        # 3. Revoke Block
        if len(revokes) > 0:
            rev_slot = self.alloc_journal_slot()
            self.journal_storage[rev_slot] = {
                "type": JBD2_REVOKE_BLOCK,
                "tid": tid,
                "revokes": revokes
            }
            slots_written.append(rev_slot)

        # 4. Commit Block
        if not omit_commit_block:
            commit_slot = self.alloc_journal_slot()
            commit_crc = crc32_be(f"{tid}:{len(meta_blocks)}".encode())
            if corrupt_commit_crc:
                commit_crc ^= 0xDEADBEEF
            self.journal_storage[commit_slot] = {
                "type": JBD2_COMMIT_BLOCK,
                "tid": tid,
                "crc32": commit_crc
            }
            slots_written.append(commit_slot)

        tx["state"] = T_COMMITTED
        tx["journal_slots"] = slots_written
        self.checkpoint_list.append(tx)
        self.stats["transactions_committed"] += 1
        self.current_tx = None

        self.log(f"JBD2 T_COMMITTED tid={tid} slots={slots_written} head={self.journal_head}")
        res = {
            "op": "COMMIT_TX",
            "status": "SUCCESS",
            "tid": tid,
            "slots_written": slots_written,
            "meta_blocks_count": len(meta_blocks),
            "journal_head": self.journal_head,
            "journal_tail": self.journal_tail
        }
        self.history.append(res)
        return res

    def alloc_journal_slot(self) -> int:
        slot = self.journal_head
        self.journal_head += 1
        if self.journal_head >= self.journal_blocks:
            self.journal_head = 1
        return slot

    def checkpoint_oldest(self):
        if not self.checkpoint_list:
            return None
        tx = self.checkpoint_list.pop(0)
        tid = tx["tid"]
        for b_id, d_hex in tx["dirty_metadata"].items():
            if b_id not in tx["revokes"]:
                self.fs_storage[b_id] = d_hex
                self.stats["blocks_checkpointed"] += 1

        last_slot = tx["journal_slots"][-1]
        self.journal_tail = (last_slot + 1)
        if self.journal_tail >= self.journal_blocks:
            self.journal_tail = 1

        self.log(f"JBD2 CHECKPOINT tid={tid} new_tail={self.journal_tail}")
        return tid

    def checkpoint_all(self) -> list:
        tids = []
        while self.checkpoint_list:
            tids.append(self.checkpoint_oldest())
        res = {"op": "CHECKPOINT", "checkpointed_tids": tids, "new_tail": self.journal_tail}
        self.history.append(res)
        return tids

    def crash(self):
        self.log("JBD2 SIMULATE_CRASH (Power loss / Kernel panic)")
        self.current_tx = None
        self.checkpoint_list = []
        res = {"op": "CRASH", "status": "CRASHED"}
        self.history.append(res)

    def recover(self) -> dict:
        self.stats["recoveries_performed"] += 1
        self.log(f"JBD2 RECOVERY_START tail={self.journal_tail} head={self.journal_head}")

        valid_transactions = []
        revoked_blocks = set()

        cur = self.journal_tail
        cur_tx_blocks = []
        cur_revokes = []
        cur_tid = None

        visited = set()
        while cur in self.journal_storage and cur not in visited:
            visited.add(cur)
            blk = self.journal_storage[cur]
            b_type = blk.get("type")

            if b_type == JBD2_DESCRIPTOR_BLOCK:
                cur_tid = blk["tid"]
                cur_tx_blocks = []
                cur_revokes = []
            elif b_type == "DATA":
                cur_tx_blocks.append(blk)
            elif b_type == JBD2_REVOKE_BLOCK:
                cur_revokes.extend(blk.get("revokes", []))
            elif b_type == JBD2_COMMIT_BLOCK:
                tid = blk["tid"]
                expected_crc = crc32_be(f"{tid}:{len(cur_tx_blocks)}".encode())
                if blk.get("crc32") == expected_crc:
                    valid_transactions.append({
                        "tid": tid,
                        "blocks": cur_tx_blocks
                    })
                    for r in cur_revokes:
                        revoked_blocks.add(r)
                    self.log(f"JBD2 RECOVERY_VALID_TX tid={tid} blocks={len(cur_tx_blocks)}")
                else:
                    self.log(f"JBD2 RECOVERY_CORRUPT_COMMIT tid={tid}")
                cur_tid = None
                cur_tx_blocks = []
                cur_revokes = []

            cur += 1
            if cur >= self.journal_blocks:
                cur = 1

        replayed_count = 0
        for tx in valid_transactions:
            for blk in tx["blocks"]:
                fb = blk["fs_block_id"]
                if fb not in revoked_blocks:
                    self.fs_storage[fb] = blk["data_hex"]
                    replayed_count += 1
                    self.log(f"JBD2 REPLAY_BLOCK tid={tx['tid']} block={fb}")
                else:
                    self.log(f"JBD2 SKIP_REVOKED_BLOCK tid={tx['tid']} block={fb}")

        self.journal_head = 1
        self.journal_tail = 1
        self.current_tx = None
        self.checkpoint_list = []

        res = {
            "op": "RECOVER",
            "recovered_transactions": len(valid_transactions),
            "replayed_blocks": replayed_count,
            "revoked_blocks": sorted(list(revoked_blocks)),
            "journal_tail": self.journal_tail,
            "journal_head": self.journal_head
        }
        self.history.append(res)
        return res

def run_simulation(input_data: dict) -> dict:
    config = input_data.get("config", {})
    initial_fs = input_data.get("initial_fs", {})
    operations = input_data.get("operations", [])
    dump_blocks = input_data.get("dump_blocks", None)

    engine = JBD2JournalEngine(config, initial_fs)

    for op_info in operations:
        op = op_info.get("op")
        if op == "START_TX":
            engine.start_transaction()
        elif op == "DIRTY":
            block_id = op_info.get("block_id")
            data_hex = op_info.get("data_hex", "")
            is_meta = op_info.get("is_metadata", True)
            engine.dirty_buffer(block_id, data_hex, is_meta)
        elif op == "REVOKE":
            block_id = op_info.get("block_id")
            engine.revoke_buffer(block_id)
        elif op == "COMMIT_TX":
            corrupt_crc = op_info.get("corrupt_commit_crc", False)
            omit_commit = op_info.get("omit_commit_block", False)
            engine.commit_transaction(corrupt_crc, omit_commit)
        elif op == "CHECKPOINT":
            chk_all = op_info.get("all", True)
            if chk_all:
                engine.checkpoint_all()
            else:
                engine.checkpoint_oldest()
        elif op == "CRASH":
            engine.crash()
        elif op == "RECOVER":
            engine.recover()

    fs_dump = {}
    if dump_blocks is not None:
        for b in sorted(dump_blocks):
            if b in engine.fs_storage:
                fs_dump[str(b)] = engine.fs_storage[b]
    else:
        for b in sorted(engine.fs_storage.keys()):
            fs_dump[str(b)] = engine.fs_storage[b]

    return {
        "journal_head": engine.journal_head,
        "journal_tail": engine.journal_tail,
        "stats": engine.stats,
        "history": engine.history,
        "filesystem_dump": fs_dump,
        "event_log": engine.event_log
    }

if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            sys.stdin.reconfigure(encoding="utf-8")
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    input_text = sys.stdin.read().strip()
    if not input_text:
        sys.exit(0)

    data = json.loads(input_text)
    result = run_simulation(data)
    print(json.dumps(result, ensure_ascii=False))
