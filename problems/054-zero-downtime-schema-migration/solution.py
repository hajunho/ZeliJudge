import sys

def parse_phone(phone_str):
    # phone_str format: "+82:01012345678"
    parts = phone_str.split(':')
    country_code = parts[0]
    national_number = parts[1]
    legacy_phone = f"{country_code}-{national_number}"
    return country_code, national_number, legacy_phone

def solve():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return

    idx = 0
    init_users_count = 0
    while idx < len(lines):
        line = lines[idx].strip()
        idx += 1
        if not line:
            continue
        parts = line.split()
        if parts[0] == "INIT_USERS":
            init_users_count = int(parts[1])
            break

    init_data = []
    while len(init_data) < init_users_count and idx < len(lines):
        line = lines[idx].strip()
        idx += 1
        if not line:
            continue
        parts = line.split()
        init_data.append((parts[0], parts[1]))

    while idx < len(lines):
        line = lines[idx].strip()
        idx += 1
        if not line:
            continue
        parts = line.split()
        if parts[0] == "EVENTS":
            break

    requests = []
    while idx < len(lines):
        line = lines[idx].strip()
        idx += 1
        if not line:
            continue
        parts = line.split()
        if parts[0] == "REQ":
            client_id = parts[1]
            pod_ver = parts[2]
            op = parts[3]
            user_id = parts[4]
            phone_arg = parts[5] if len(parts) > 5 else None
            requests.append((client_id, pod_ver, op, user_id, phone_arg))

    # 1. NAIVE DB State
    # NAIVE dropped 'phone', only has 'country_code', 'national_number'.
    # Initial data has NULL for new columns!
    naive_db = {}
    for uid, raw_phone in init_data:
        naive_db[uid] = {'country_code': None, 'national_number': None}

    # 2. EXPAND DB State
    # Has both legacy 'phone' and new 'country_code', 'national_number'.
    # Initial data has legacy 'phone' populated.
    expand_db = {}
    for uid, raw_phone in init_data:
        cc, nn, leg = parse_phone(raw_phone)
        expand_db[uid] = {
            'phone': leg,
            'country_code': None,
            'national_number': None
        }

    n_succ = 0
    n_err = 0
    n_not_found = 0

    e_succ = 0
    e_err = 0
    e_not_found = 0

    for client_id, pod_ver, op, user_id, phone_arg in requests:
        # Evaluate NAIVE
        if pod_ver == 'V1':
            # V1 tries to access 'phone' column which is DROPPED in NAIVE DB
            n_status = "ERROR_SCHEMA_MISMATCH"
            n_err += 1
        else: # V2
            if op == 'WRITE':
                cc, nn, _ = parse_phone(phone_arg)
                naive_db[user_id] = {'country_code': cc, 'national_number': nn}
                n_status = "SUCCESS"
                n_succ += 1
            else: # READ
                rec = naive_db.get(user_id)
                if rec is None:
                    n_status = "NOT_FOUND"
                    n_not_found += 1
                elif rec['country_code'] is None or rec['national_number'] is None:
                    n_status = "ERROR_DATA_MISSING"
                    n_err += 1
                else:
                    n_status = "SUCCESS"
                    n_succ += 1

        # Evaluate EXPAND (Expand-and-Contract)
        if pod_ver == 'V1':
            if op == 'WRITE':
                cc, nn, leg = parse_phone(phone_arg)
                if user_id not in expand_db:
                    expand_db[user_id] = {'phone': leg, 'country_code': None, 'national_number': None}
                else:
                    expand_db[user_id]['phone'] = leg
                e_status = "SUCCESS"
                e_succ += 1
            else: # READ
                rec = expand_db.get(user_id)
                if rec is None or rec['phone'] is None:
                    e_status = "NOT_FOUND"
                    e_not_found += 1
                else:
                    e_status = "SUCCESS"
                    e_succ += 1
        else: # V2
            if op == 'WRITE':
                # Dual Write: writes both legacy and new columns
                cc, nn, leg = parse_phone(phone_arg)
                expand_db[user_id] = {
                    'phone': leg,
                    'country_code': cc,
                    'national_number': nn
                }
                e_status = "SUCCESS"
                e_succ += 1
            else: # READ
                # Fallback Read: tries new columns first, falls back to legacy
                rec = expand_db.get(user_id)
                if rec is None:
                    e_status = "NOT_FOUND"
                    e_not_found += 1
                elif rec['country_code'] is not None and rec['national_number'] is not None:
                    e_status = "SUCCESS"
                    e_succ += 1
                elif rec['phone'] is not None:
                    # Fallback to phone
                    e_status = "SUCCESS"
                    e_succ += 1
                else:
                    e_status = "NOT_FOUND"
                    e_not_found += 1

        print(f"REQ {client_id} POD:{pod_ver} OP:{op} USER:{user_id} NAIVE:{n_status} EXPAND:{e_status}")

    total_reqs = len(requests)
    n_rate = (n_succ / total_reqs * 100.0) if total_reqs > 0 else 0.0
    e_rate = (e_succ / total_reqs * 100.0) if total_reqs > 0 else 0.0
    adv = e_rate - n_rate

    print(f"SUMMARY TOTAL_REQS:{total_reqs}")
    print(f"NAIVE SUCCESS:{n_succ} ERRORS:{n_err} SUCCESS_RATE:{n_rate:.2f}%")
    print(f"EXPAND SUCCESS:{e_succ} ERRORS:{e_err} SUCCESS_RATE:{e_rate:.2f}%")
    print(f"SUMMARY ZERO_DOWNTIME_ADVANTAGE:{adv:.2f}%")

if __name__ == "__main__":
    solve()
