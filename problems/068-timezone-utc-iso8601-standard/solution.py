import sys
from datetime import datetime, timezone, timedelta

def parse_offset(offset_str):
    offset_str = offset_str.strip()
    if offset_str == "Z":
        return 0
    sign = 1 if offset_str[0] == '+' else -1
    parts = offset_str[1:].split(':')
    hours = int(parts[0])
    minutes = int(parts[1]) if len(parts) > 1 else 0
    return sign * (hours * 3600 + minutes * 60)

def format_offset(offset_sec):
    if offset_sec == 0:
        return "Z"
    sign = "+" if offset_sec >= 0 else "-"
    abs_sec = abs(offset_sec)
    h = abs_sec // 3600
    m = (abs_sec % 3600) // 60
    return f"{sign}{h:02d}:{m:02d}"

def iso_to_epoch(iso_str, offset_sec):
    # iso_str: YYYY-MM-DDTHH:MM:SS
    dt = datetime.strptime(iso_str, "%Y-%m-%dT%H:%M:%S")
    dt = dt.replace(tzinfo=timezone.utc)
    naive_epoch = int(dt.timestamp())
    return naive_epoch - offset_sec

def epoch_to_iso(epoch_sec, offset_sec):
    utc_dt = datetime.fromtimestamp(epoch_sec, tz=timezone.utc)
    tz_obj = timezone(timedelta(seconds=offset_sec))
    target_dt = utc_dt.astimezone(tz_obj)
    base_str = target_dt.strftime("%Y-%m-%dT%H:%M:%S")
    return base_str + format_offset(offset_sec)

def solve():
    input_data = sys.stdin.read().splitlines()
    if not input_data:
        return

    mode = "TIMEZONES"
    tz_map = {}
    naive_server_tz = "UTC"
    actions = []

    for line in input_data:
        line = line.strip()
        if not line:
            continue
        if line == "TIMEZONES":
            mode = "TIMEZONES"
            continue
        elif line == "SERVER_CONFIG":
            mode = "SERVER_CONFIG"
            continue
        elif line == "ACTIONS":
            mode = "ACTIONS"
            continue

        parts = line.split()
        if mode == "TIMEZONES":
            tz_name = parts[0]
            offset_str = parts[1]
            tz_map[tz_name] = parse_offset(offset_str)
        elif mode == "SERVER_CONFIG":
            if parts[0] == "NAIVE_SERVER_TZ":
                naive_server_tz = parts[1]
        elif mode == "ACTIONS":
            actions.append(parts)

    naive_payments = {}  # pay_id -> (naive_raw_str, amount)
    utc_payments = {}    # pay_id -> (utc_epoch, amount, original_client_tz)

    out_lines = []
    total_payments = 0
    expiration_checks = 0
    naive_errors = 0
    settlement_count = 0
    total_discrepancy = 0

    for act_idx, act in enumerate(actions, 1):
        cmd = act[0]

        if cmd == "CREATE_PAYMENT":
            pay_id = act[1]
            amount = int(act[2])
            local_iso = act[3]
            client_tz = act[4]

            total_payments += 1
            client_offset = tz_map[client_tz]
            utc_epoch = iso_to_epoch(local_iso, client_offset)
            utc_iso_str = epoch_to_iso(utc_epoch, 0)

            naive_payments[pay_id] = (local_iso, amount)
            utc_payments[pay_id] = (utc_epoch, amount, client_tz)

            out_lines.append(f"ACT {act_idx} CREATE_PAYMENT {pay_id}")
            out_lines.append(f"  NAIVE_STORED: {local_iso} (ASSUMED_TZ:{naive_server_tz})")
            out_lines.append(f"  UTC_STORED: {utc_iso_str} (EPOCH:{utc_epoch})")

        elif cmd == "DISPLAY_PAYMENT":
            pay_id = act[1]
            target_tz = act[2]
            target_offset = tz_map[target_tz]

            naive_raw = naive_payments[pay_id][0]
            utc_epoch = utc_payments[pay_id][0]
            utc_display = epoch_to_iso(utc_epoch, target_offset)

            out_lines.append(f"ACT {act_idx} DISPLAY_PAYMENT {pay_id} TARGET_TZ:{target_tz}")
            out_lines.append(f"  NAIVE_DISPLAY: {naive_raw}")
            out_lines.append(f"  UTC_DISPLAY: {utc_display}")

        elif cmd == "CHECK_EXPIRATION":
            pay_id = act[1]
            curr_iso = act[2]
            check_tz = act[3]
            valid_hours = float(act[4])

            expiration_checks += 1
            check_offset = tz_map[check_tz]

            # 1. Naive calculation (string subtraction without timezone consideration)
            naive_stored_str = naive_payments[pay_id][0]
            dt_stored = datetime.strptime(naive_stored_str, "%Y-%m-%dT%H:%M:%S")
            dt_curr = datetime.strptime(curr_iso, "%Y-%m-%dT%H:%M:%S")
            naive_elapsed_sec = (dt_curr - dt_stored).total_seconds()
            naive_elapsed_hours = naive_elapsed_sec / 3600.0
            naive_status = "VALID" if naive_elapsed_hours <= valid_hours else "EXPIRED"

            # 2. UTC exact calculation
            curr_utc_epoch = iso_to_epoch(curr_iso, check_offset)
            utc_stored_epoch = utc_payments[pay_id][0]
            exact_elapsed_sec = curr_utc_epoch - utc_stored_epoch
            exact_elapsed_hours = exact_elapsed_sec / 3600.0
            exact_status = "VALID" if exact_elapsed_hours <= valid_hours else "EXPIRED"

            if naive_status != exact_status:
                naive_errors += 1

            out_lines.append(f"ACT {act_idx} CHECK_EXPIRATION {pay_id} LIMIT:{int(valid_hours) if valid_hours.is_integer() else valid_hours}h CHECK_TZ:{check_tz}")
            out_lines.append(f"  NAIVE: ELAPSED:{naive_elapsed_hours:.2f}h STATUS:{naive_status}")
            out_lines.append(f"  UTC: ELAPSED:{exact_elapsed_hours:.2f}h STATUS:{exact_status}")

        elif cmd == "SETTLE_DAILY_SALES":
            target_date = act[1]
            biz_tz = act[2]
            settlement_count += 1

            # 1. Naive Settlement: simple string prefix match
            naive_cnt = 0
            naive_sum = 0
            for pid, (raw_str, amt) in naive_payments.items():
                if raw_str.startswith(target_date):
                    naive_cnt += 1
                    naive_sum += amt

            # 2. UTC Settlement: convert biz_tz day boundaries to UTC epoch range
            biz_offset = tz_map[biz_tz]
            start_iso = f"{target_date}T00:00:00"
            end_iso = f"{target_date}T23:59:59"
            start_utc_epoch = iso_to_epoch(start_iso, biz_offset)
            end_utc_epoch = iso_to_epoch(end_iso, biz_offset)

            utc_cnt = 0
            utc_sum = 0
            for pid, (u_epoch, amt, _) in utc_payments.items():
                if start_utc_epoch <= u_epoch <= end_utc_epoch:
                    utc_cnt += 1
                    utc_sum += amt

            discrepancy = abs(naive_sum - utc_sum)
            total_discrepancy += discrepancy

            out_lines.append(f"ACT {act_idx} SETTLE_DAILY_SALES DATE:{target_date} BIZ_TZ:{biz_tz}")
            out_lines.append(f"  NAIVE: COUNT:{naive_cnt} TOTAL:{naive_sum}")
            out_lines.append(f"  UTC: COUNT:{utc_cnt} TOTAL:{utc_sum} DISCREPANCY:{discrepancy}")

    # Summary
    out_lines.append(f"SUMMARY TOTAL_PAYMENTS_PROCESSED:{total_payments}")
    err_rate = (naive_errors / expiration_checks * 100.0) if expiration_checks > 0 else 0.0
    out_lines.append(f"SUMMARY EXPIRATION_CHECKS:{expiration_checks} NAIVE_ERRORS:{naive_errors} (MISJUDGMENT_RATE:{err_rate:.2f}%)")
    out_lines.append(f"SUMMARY SETTLEMENTS:{settlement_count} TOTAL_DISCREPANCY_AMOUNT:{total_discrepancy}")
    out_lines.append("SUMMARY UTC_CONSISTENCY: 100% AUDIT_READY")

    print("\n".join(out_lines))

if __name__ == "__main__":
    solve()
