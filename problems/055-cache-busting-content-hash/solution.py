import sys

def get_content_hash(content):
    h = 0
    for c in content:
        h = (h * 31 + ord(c)) & 0xFFFFFFFF
    return f"{h:08x}"[:6]

def solve():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return

    naive_html_ttl = 3600
    naive_bundle_ttl = 86400

    idx = 0
    while idx < len(lines):
        line = lines[idx].strip()
        idx += 1
        if not line:
            continue
        parts = line.split()
        if parts[0] == "NAIVE_HTML_TTL_SEC":
            naive_html_ttl = int(parts[1])
        elif parts[0] == "NAIVE_BUNDLE_TTL_SEC":
            naive_bundle_ttl = int(parts[1])
        elif parts[0] == "EVENTS":
            break

    # Event types:
    # 1. DEPLOY <timestamp> <version> <code_content>
    # 2. VISIT <client_id> <timestamp>
    raw_events = []
    while idx < len(lines):
        line = lines[idx].strip()
        idx += 1
        if not line:
            continue
        parts = line.split()
        if parts[0] == "DEPLOY":
            # ('DEPLOY', timestamp, int(version), code_content)
            raw_events.append(('DEPLOY', int(parts[1]), int(parts[2]), parts[3]))
        elif parts[0] == "VISIT":
            # ('VISIT', timestamp, client_id)
            raw_events.append(('VISIT', int(parts[2]), parts[1]))

    # Sort events by timestamp; ties: DEPLOY before VISIT
    raw_events.sort(key=lambda x: (x[1], 0 if x[0] == 'DEPLOY' else 1))

    # Server state
    curr_server_version = 1
    curr_code_content = "initial_code"
    curr_bundle_hash = get_content_hash(curr_code_content)

    # NAIVE Client caches: client_id -> {'html_v': int, 'html_exp': int, 'bundle_v': int, 'bundle_exp': int}
    naive_client_cache = {}

    # HASH Client caches: client_id -> set of cached bundle hashes
    hash_client_cache = {}

    total_visits = 0
    n_succ = 0
    n_err = 0

    h_succ = 0
    h_err = 0
    h_fetches = 0
    h_hits = 0

    for ev in raw_events:
        if ev[0] == 'DEPLOY':
            _, t, version, code_content = ev
            curr_server_version = version
            curr_code_content = code_content
            curr_bundle_hash = get_content_hash(code_content)

        elif ev[0] == 'VISIT':
            _, t, client_id = ev
            total_visits += 1

            # 1. NAIVE Evaluation
            c_info = naive_client_cache.get(client_id)
            if c_info is None:
                c_info = {'html_v': None, 'html_exp': 0, 'bundle_v': None, 'bundle_exp': 0}
                naive_client_cache[client_id] = c_info

            # HTML lookup
            if t < c_info['html_exp']:
                # Disk cache hit for HTML
                resolved_html_v = c_info['html_v']
            else:
                # Fetch fresh HTML from server
                resolved_html_v = curr_server_version
                c_info['html_v'] = curr_server_version
                c_info['html_exp'] = t + naive_html_ttl

            # Bundle lookup (fixed URL: /static/bundle.js)
            if t < c_info['bundle_exp']:
                # Disk cache hit for bundle
                executed_bundle_v = c_info['bundle_v']
            else:
                # Fetch bundle from server
                executed_bundle_v = curr_server_version
                c_info['bundle_v'] = curr_server_version
                c_info['bundle_exp'] = t + naive_bundle_ttl

            if executed_bundle_v < curr_server_version:
                n_status = "API_MISMATCH_ERROR"
                n_err += 1
            else:
                n_status = "SUCCESS"
                n_succ += 1

            # 2. HASH (Content Hashing + no-cache HTML) Evaluation
            # HTML is no-cache, always fresh: references /static/bundle.<curr_bundle_hash>.js
            if client_id not in hash_client_cache:
                hash_client_cache[client_id] = set()

            client_hashes = hash_client_cache[client_id]
            if curr_bundle_hash in client_hashes:
                h_asset = "DISK_HIT"
                h_hits += 1
            else:
                h_asset = "NETWORK_FETCH"
                h_fetches += 1
                client_hashes.add(curr_bundle_hash)

            h_status = "SUCCESS"
            h_succ += 1
            h_exec_v = curr_server_version

            print(f"VISIT {client_id} AT:{t} NAIVE:{n_status},EXEC_V:{executed_bundle_v} HASH:{h_status},EXEC_V:{h_exec_v},ASSET:{h_asset}")

    n_rate = (n_succ / total_visits * 100.0) if total_visits > 0 else 0.0
    h_rate = (h_succ / total_visits * 100.0) if total_visits > 0 else 0.0
    adv = h_rate - n_rate

    print(f"SUMMARY TOTAL_VISITS:{total_visits}")
    print(f"NAIVE SUCCESS:{n_succ} ERRORS:{n_err} SUCCESS_RATE:{n_rate:.2f}%")
    print(f"HASH SUCCESS:{h_succ} ERRORS:{h_err} SUCCESS_RATE:{h_rate:.2f}% NETWORK_FETCHES:{h_fetches} DISK_HITS:{h_hits}")
    print(f"SUMMARY CACHE_BUSTING_ADVANTAGE:{adv:.2f}%")

if __name__ == "__main__":
    solve()
