import sys

def solve():
    input_data = sys.stdin.read().splitlines()
    if not input_data:
        return

    mode = None
    init_stocks = {}
    init_balances = {}
    transactions = []

    for line in input_data:
        line = line.strip()
        if not line:
            continue
        if line == "INIT_STOCKS":
            mode = "STOCKS"
            continue
        elif line == "INIT_BALANCES":
            mode = "BALANCES"
            continue
        elif line == "TRANSACTIONS":
            mode = "TXS"
            continue

        parts = line.split()
        if mode == "STOCKS":
            init_stocks[parts[0]] = int(parts[1])
        elif mode == "BALANCES":
            init_balances[parts[0]] = int(parts[1])
        elif mode == "TXS":
            # tx_id, user_id, item_id, qty, amount, fault
            tx_id = parts[0]
            user_id = parts[1]
            item_id = parts[2]
            qty = int(parts[3])
            amount = int(parts[4])
            fault = parts[5] if len(parts) > 5 else "NONE"
            transactions.append((tx_id, user_id, item_id, qty, amount, fault))

    # --- 2PC Simulation State ---
    pc_stock = dict(init_stocks)
    pc_balance = dict(init_balances)
    indoubt_stock = {}  # item_id -> tx_id
    indoubt_user = {}   # user_id -> tx_id

    pc_committed = 0
    pc_aborted = 0
    pc_blocked = 0
    pc_lock_timeouts = 0

    # --- SAGA Simulation State ---
    saga_stock = dict(init_stocks)
    saga_balance = dict(init_balances)

    saga_committed = 0
    saga_compensated = 0

    out_lines = []

    for tx_id, user_id, item_id, qty, amount, fault in transactions:
        # 1. Simulate 2PC
        pc_status = ""
        if item_id in indoubt_stock:
            blocker = indoubt_stock[item_id]
            pc_status = f"LOCK_TIMEOUT_BLOCKED(by={blocker})"
            pc_lock_timeouts += 1
        elif user_id in indoubt_user:
            blocker = indoubt_user[user_id]
            pc_status = f"LOCK_TIMEOUT_BLOCKED(by={blocker})"
            pc_lock_timeouts += 1
        else:
            # Acquire locks & Phase 1 Prepare
            if fault == "OUT_OF_STOCK" or pc_stock.get(item_id, 0) < qty:
                pc_status = "ABORTED(reason=OUT_OF_STOCK)"
                pc_aborted += 1
            elif fault == "INSUFFICIENT_FUNDS" or pc_balance.get(user_id, 0) < amount:
                pc_status = "ABORTED(reason=INSUFFICIENT_FUNDS)"
                pc_aborted += 1
            elif fault == "PAYMENT_FAIL":
                pc_status = "ABORTED(reason=PAYMENT_FAIL)"
                pc_aborted += 1
            elif fault == "CRASH_COORD_P2":
                # Phase 1 succeeded, coordinator crashed before Phase 2!
                indoubt_stock[item_id] = tx_id
                indoubt_user[user_id] = tx_id
                pc_stock[item_id] -= qty
                pc_balance[user_id] -= amount
                pc_status = "BLOCKED_INDOUBT(CRASH_COORD_P2)"
                pc_blocked += 1
            else:
                # Phase 2 Global Commit
                pc_stock[item_id] -= qty
                pc_balance[user_id] -= amount
                pc_status = "COMMITTED"
                pc_committed += 1

        # 2. Simulate SAGA
        saga_status = ""
        # Step 1: T_ORDER (Local commit OK)
        # Step 2: T_STOCK
        if fault == "OUT_OF_STOCK" or saga_stock.get(item_id, 0) < qty:
            # Stock check/deduct failed -> Compensate C_ORDER
            saga_status = "COMPENSATED(failed_at=STOCK,reason=OUT_OF_STOCK)"
            saga_compensated += 1
        else:
            # T_STOCK succeeded (locally committed)
            saga_stock[item_id] -= qty
            # Step 3: T_PAY
            if fault == "INSUFFICIENT_FUNDS" or saga_balance.get(user_id, 0) < amount:
                # Balance check failed -> Compensate C_STOCK, C_ORDER
                saga_stock[item_id] += qty
                saga_status = "COMPENSATED(failed_at=PAY,reason=INSUFFICIENT_FUNDS)"
                saga_compensated += 1
            elif fault == "PAYMENT_FAIL":
                # Gateway failed -> Compensate C_STOCK, C_ORDER
                saga_stock[item_id] += qty
                saga_status = "COMPENSATED(failed_at=PAY,reason=PAYMENT_FAIL)"
                saga_compensated += 1
            else:
                # T_PAY succeeded (locally committed)
                saga_balance[user_id] -= amount
                if fault == "CRASH_COORD_P2":
                    # Saga orchestrator rebooted and recovered from saga log!
                    saga_status = "COMMITTED(RECOVERED)"
                    saga_committed += 1
                else:
                    saga_status = "COMMITTED"
                    saga_committed += 1

        out_lines.append(f"TX {tx_id} 2PC:{pc_status} SAGA:{saga_status}")

    # Summary
    out_lines.append(f"SUMMARY 2PC COMMITTED:{pc_committed} ABORTED:{pc_aborted} BLOCKED:{pc_blocked} LOCK_TIMEOUTS:{pc_lock_timeouts}")
    out_lines.append(f"SUMMARY SAGA COMMITTED:{saga_committed} COMPENSATED:{saga_compensated} BLOCKED:0 LOCK_TIMEOUTS:0")

    sorted_items = sorted(init_stocks.keys())
    sorted_users = sorted(init_balances.keys())

    pc_stock_str = " ".join(f"{item}:{pc_stock.get(item, 0)}" for item in sorted_items)
    pc_bal_str = " ".join(f"{user}:{pc_balance.get(user, 0)}" for user in sorted_users)
    saga_stock_str = " ".join(f"{item}:{saga_stock.get(item, 0)}" for item in sorted_items)
    saga_bal_str = " ".join(f"{user}:{saga_balance.get(user, 0)}" for user in sorted_users)

    out_lines.append(f"RESOURCE 2PC FINAL_STOCKS {pc_stock_str}")
    out_lines.append(f"RESOURCE 2PC FINAL_BALANCES {pc_bal_str}")
    out_lines.append(f"RESOURCE SAGA FINAL_STOCKS {saga_stock_str}")
    out_lines.append(f"RESOURCE SAGA FINAL_BALANCES {saga_bal_str}")

    print("\n".join(out_lines))

if __name__ == "__main__":
    solve()
