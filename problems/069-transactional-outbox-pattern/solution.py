import sys

def solve():
    input_data = sys.stdin.read().splitlines()
    if not input_data:
        return

    mode = "CONFIG"
    batch_size = 10
    max_retries = 3
    actions = []

    for line in input_data:
        line = line.strip()
        if not line:
            continue
        if line == "SYSTEM_CONFIG":
            mode = "CONFIG"
            continue
        elif line == "ACTIONS":
            mode = "ACTIONS"
            continue

        parts = line.split()
        if mode == "CONFIG":
            if parts[0] == "RELAY_BATCH_SIZE":
                batch_size = int(parts[1])
            elif parts[0] == "MAX_RETRIES":
                max_retries = int(parts[1])
        elif mode == "ACTIONS":
            actions.append(parts)

    broker_up = True

    # 1. Naive Dual-Write Engine State
    naive_db_orders = []       # list of order_id
    naive_broker_queue = []    # list of order_id
    naive_lost_count = 0

    # 2. Transactional Outbox Engine State
    outbox_db_orders = []      # list of order_id
    outbox_records = []        # list of dict: {id, order_id, user_id, amount, status, retries}
    outbox_broker_queue = []   # list of order_id
    outbox_seq = 0

    out_lines = []

    for act_idx, act in enumerate(actions, 1):
        cmd = act[0]

        if cmd == "BROKER_STATUS":
            state_str = act[1].upper()
            broker_up = (state_str == "UP")
            out_lines.append(f"ACT {act_idx} BROKER_STATUS STATE:{state_str}")

        elif cmd == "PLACE_ORDER":
            order_id = act[1]
            user_id = act[2]
            amount = int(act[3])

            # 1. Naive Engine: Save DB then immediately try broker publish
            naive_db_orders.append(order_id)
            if broker_up:
                naive_broker_queue.append(order_id)
                naive_pub_res = "SUCCESS"
            else:
                naive_lost_count += 1
                naive_pub_res = "FAILED_LOST"

            # 2. Outbox Engine: Single local DB transaction (Atomic orders + outbox insert)
            outbox_db_orders.append(order_id)
            outbox_seq += 1
            outbox_records.append({
                "id": outbox_seq,
                "order_id": order_id,
                "user_id": user_id,
                "amount": amount,
                "status": "PENDING",
                "retries": 0
            })

            out_lines.append(f"ACT {act_idx} PLACE_ORDER {order_id} USER:{user_id} AMT:{amount}")
            out_lines.append(f"  NAIVE: DB_SAVED=YES BROKER_PUBLISH:{naive_pub_res}")
            out_lines.append("  OUTBOX: DB_TX_COMMITTED=YES OUTBOX_STATUS:PENDING")

        elif cmd == "RUN_RELAY":
            # Naive has no relay
            # Outbox polls up to batch_size PENDING records
            pending_candidates = [r for r in outbox_records if r["status"] == "PENDING"]
            polled = pending_candidates[:batch_size]
            polled_cnt = len(polled)

            pub_cnt = 0
            retry_cnt = 0
            dlq_cnt = 0

            if broker_up:
                for r in polled:
                    r["status"] = "PUBLISHED"
                    outbox_broker_queue.append(r["order_id"])
                    pub_cnt += 1
            else:
                for r in polled:
                    r["retries"] += 1
                    if r["retries"] >= max_retries:
                        r["status"] = "FAILED_DLQ"
                        dlq_cnt += 1
                    else:
                        retry_cnt += 1

            rem_pending = sum(1 for r in outbox_records if r["status"] == "PENDING")

            out_lines.append(f"ACT {act_idx} RUN_RELAY")
            out_lines.append("  NAIVE: NO_RELAY_SUPPORT")
            out_lines.append(f"  OUTBOX: POLLED:{polled_cnt} PUBLISHED:{pub_cnt} RETRIED:{retry_cnt} FAILED_DLQ:{dlq_cnt} REMAINING_PENDING:{rem_pending}")

        elif cmd == "CHECK_CONSISTENCY":
            naive_orders_cnt = len(naive_db_orders)
            naive_broker_cnt = len(naive_broker_queue)
            naive_status = "CONSISTENT" if naive_lost_count == 0 else "INCONSISTENT"

            outbox_orders_cnt = len(outbox_db_orders)
            outbox_broker_cnt = len(outbox_broker_queue)
            pending_cnt = sum(1 for r in outbox_records if r["status"] == "PENDING")

            out_lines.append(f"ACT {act_idx} CHECK_CONSISTENCY")
            out_lines.append(f"  NAIVE: DB_ORDERS:{naive_orders_cnt} BROKER_RECEIVED:{naive_broker_cnt} LOST_EVENTS:{naive_lost_count} STATUS:{naive_status}")
            out_lines.append(f"  OUTBOX: DB_ORDERS:{outbox_orders_cnt} BROKER_RECEIVED:{outbox_broker_cnt} OUTBOX_PENDING:{pending_cnt} STATUS:CONSISTENT")

    # Summary
    total_orders = len(naive_db_orders)
    naive_loss_pct = (naive_lost_count / total_orders * 100.0) if total_orders > 0 else 0.0
    pending_total = sum(1 for r in outbox_records if r["status"] == "PENDING")
    dlq_total = sum(1 for r in outbox_records if r["status"] == "FAILED_DLQ")

    out_lines.append(f"SUMMARY TOTAL_ORDERS:{total_orders}")
    out_lines.append(f"SUMMARY NAIVE BROKER_RECEIVED:{len(naive_broker_queue)} LOST_EVENTS:{naive_lost_count} (LOSS_RATE:{naive_loss_pct:.2f}%)")
    out_lines.append(f"SUMMARY OUTBOX BROKER_RECEIVED:{len(outbox_broker_queue)} OUTBOX_PENDING:{pending_total} OUTBOX_DLQ:{dlq_total} LOST_EVENTS:0 (LOSS_RATE:0.00%)")
    out_lines.append("SUMMARY PATTERN_VERDICT: OUTBOX_100%_LOSSLESS")

    print("\n".join(out_lines))

if __name__ == "__main__":
    solve()
