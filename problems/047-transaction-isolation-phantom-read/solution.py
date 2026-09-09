import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return

    idx = 0
    assert input_data[idx] == "MAX_CAPACITY"
    limit = int(input_data[idx + 1])
    idx += 2

    assert input_data[idx] == "EVENTS"
    events_count = int(input_data[idx + 1])
    idx += 2

    committed_items = []
    active_tx = {}
    conflicts_count = 0
    out_lines = []

    for _ in range(events_count):
        cmd = input_data[idx]
        if cmd == "TX_START":
            tx_id = input_data[idx + 1]
            level = input_data[idx + 2]
            idx += 3

            active_tx[tx_id] = {
                'level': level,
                'snapshot_count': len(committed_items),
                'uncommitted': [],
                'has_read': False,
                'aborted': False
            }
            out_lines.append(f"TX_START {tx_id} LEVEL:{level}")

        elif cmd == "TX_READ":
            tx_id = input_data[idx + 1]
            idx += 2

            tx = active_tx[tx_id]
            if tx['aborted']:
                out_lines.append(f"TX_READ {tx_id} STATUS:ABORTED")
            else:
                tx['has_read'] = True
                if tx['level'] == 'READ_COMMITTED':
                    c = len(committed_items) + len(tx['uncommitted'])
                else: # REPEATABLE_READ or SERIALIZABLE
                    c = tx['snapshot_count'] + len(tx['uncommitted'])
                out_lines.append(f"TX_READ {tx_id} COUNT:{c}")

        elif cmd == "TX_INSERT":
            tx_id = input_data[idx + 1]
            item_id = input_data[idx + 2]
            idx += 3

            tx = active_tx[tx_id]
            if tx['aborted']:
                out_lines.append(f"TX_INSERT {tx_id} ITEM:{item_id} STATUS:ABORTED")
            else:
                conflict = False
                for other_id, other_tx in active_tx.items():
                    if other_id != tx_id and not other_tx['aborted']:
                        if other_tx['level'] == 'SERIALIZABLE' and other_tx['has_read']:
                            conflict = True
                            break
                
                if conflict:
                    conflicts_count += 1
                    tx['aborted'] = True
                    tx['uncommitted'].clear()
                    out_lines.append(f"TX_INSERT {tx_id} ITEM:{item_id} STATUS:SERIALIZATION_CONFLICT")
                else:
                    tx['uncommitted'].append(item_id)
                    out_lines.append(f"TX_INSERT {tx_id} ITEM:{item_id} STATUS:ACCEPTED")

        elif cmd == "TX_COMMIT":
            tx_id = input_data[idx + 1]
            idx += 2

            tx = active_tx[tx_id]
            if tx['aborted']:
                out_lines.append(f"TX_COMMIT {tx_id} STATUS:ABORTED_CANNOT_COMMIT")
            else:
                cnt = len(tx['uncommitted'])
                committed_items.extend(tx['uncommitted'])
                out_lines.append(f"TX_COMMIT {tx_id} STATUS:COMMITTED ITEMS_COMMITTED:{cnt}")
            del active_tx[tx_id]

        elif cmd == "TX_ROLLBACK":
            tx_id = input_data[idx + 1]
            idx += 2

            del active_tx[tx_id]
            out_lines.append(f"TX_ROLLBACK {tx_id} STATUS:ROLLED_BACK")

        else:
            raise ValueError(f"Unknown command: {cmd}")

    final_committed = len(committed_items)
    overbooked = max(0, final_committed - limit)
    out_lines.append(
        f"SUMMARY TOTAL_EVENTS:{events_count} FINAL_COMMITTED:{final_committed} LIMIT:{limit} OVERBOOKED:{overbooked} CONFLICTS_CAUGHT:{conflicts_count}"
    )

    sys.stdout.write("\n".join(out_lines) + "\n")

if __name__ == "__main__":
    solve()
