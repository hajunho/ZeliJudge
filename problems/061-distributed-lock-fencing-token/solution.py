import sys

def solve():
    input_data = sys.stdin.read().splitlines()
    if not input_data:
        return

    ttl_ms = 0
    actions = []
    in_actions = False

    for line in input_data:
        line = line.strip()
        if not line:
            continue
        if line.startswith("LOCK_TTL_MS"):
            parts = line.split()
            ttl_ms = int(parts[1])
        elif line == "ACTIONS":
            in_actions = True
        elif in_actions:
            actions.append(line.split())

    # Naive State
    naive_current_holder = None
    naive_expires_at = 0
    naive_client_has_lock = {}
    naive_storage_val = "NONE"
    naive_corrupted_writes = 0
    naive_hijacked_releases = 0

    # Safe State (Martin Kleppmann Fencing Token)
    safe_current_holder = None
    safe_current_token = 0
    safe_expires_at = 0
    safe_global_token = 0
    safe_client_has_lock = {}
    safe_client_token = {}
    safe_storage_val = "NONE"
    safe_highest_token_seen = 0
    safe_stale_writes_rejected = 0
    safe_stale_releases_rejected = 0

    out_lines = []

    for idx, act in enumerate(actions, 1):
        cmd = act[0]

        if cmd == "LOCK":
            client_id = act[1]
            ts = int(act[2])

            # --- NAIVE LOCK ---
            if naive_current_holder is not None and ts >= naive_expires_at:
                naive_current_holder = None

            if naive_current_holder is None:
                naive_current_holder = client_id
                naive_expires_at = ts + ttl_ms
                naive_client_has_lock[client_id] = True
                naive_status = "LOCK_ACQUIRED"
            else:
                naive_status = "LOCK_BUSY"

            # --- SAFE LOCK ---
            if safe_current_holder is not None and ts >= safe_expires_at:
                safe_current_holder = None
                safe_current_token = 0

            if safe_current_holder is None:
                safe_global_token += 1
                safe_current_token = safe_global_token
                safe_current_holder = client_id
                safe_expires_at = ts + ttl_ms
                safe_client_has_lock[client_id] = True
                safe_client_token[client_id] = safe_current_token
                safe_status = f"LOCK_ACQUIRED(token={safe_current_token})"
            else:
                safe_status = "LOCK_BUSY"

            out_lines.append(f"ACT {idx} LOCK {client_id} NAIVE:{naive_status} SAFE:{safe_status}")

        elif cmd == "WRITE":
            client_id = act[1]
            val = act[2]
            ts = int(act[3])

            # --- NAIVE WRITE ---
            if not naive_client_has_lock.get(client_id, False):
                naive_status = "WRITE_FAIL_NO_LOCK"
            else:
                naive_storage_val = val
                if naive_current_holder is not None and ts >= naive_expires_at:
                    naive_current_holder = None

                if naive_current_holder == client_id:
                    naive_status = "WRITE_OK"
                else:
                    naive_status = "WRITE_CORRUPTED"
                    naive_corrupted_writes += 1

            # --- SAFE WRITE ---
            if not safe_client_has_lock.get(client_id, False):
                safe_status = "WRITE_FAIL_NO_LOCK"
            else:
                token = safe_client_token.get(client_id, 0)
                if token > safe_highest_token_seen:
                    safe_highest_token_seen = token
                    safe_storage_val = val
                    safe_status = f"WRITE_OK(token={token})"
                else:
                    safe_stale_writes_rejected += 1
                    safe_status = f"WRITE_REJECTED_STALE(token={token},highest={safe_highest_token_seen})"

            out_lines.append(f"ACT {idx} WRITE {client_id} NAIVE:{naive_status} SAFE:{safe_status}")

        elif cmd == "RELEASE":
            client_id = act[1]
            ts = int(act[2])

            # --- NAIVE RELEASE ---
            if not naive_client_has_lock.get(client_id, False):
                naive_status = "RELEASE_FAIL_NO_LOCK"
            else:
                naive_client_has_lock[client_id] = False
                if naive_current_holder is not None and ts >= naive_expires_at:
                    naive_current_holder = None

                if naive_current_holder is None:
                    naive_status = "RELEASE_FAIL_NO_LOCK"
                elif naive_current_holder == client_id:
                    naive_current_holder = None
                    naive_status = "RELEASE_OK"
                else:
                    naive_current_holder = None
                    naive_hijacked_releases += 1
                    naive_status = "RELEASE_OK_HIJACKED"

            # --- SAFE RELEASE ---
            if not safe_client_has_lock.get(client_id, False):
                safe_status = "RELEASE_FAIL_NO_LOCK"
            else:
                token = safe_client_token.get(client_id, 0)
                safe_client_has_lock[client_id] = False

                if safe_current_holder is not None and ts >= safe_expires_at:
                    safe_current_holder = None
                    safe_current_token = 0

                if safe_current_holder is None:
                    safe_status = f"RELEASE_IGNORED_EXPIRED(token={token})"
                elif safe_current_holder == client_id and safe_current_token == token:
                    safe_current_holder = None
                    safe_current_token = 0
                    safe_status = f"RELEASE_OK(token={token})"
                else:
                    safe_stale_releases_rejected += 1
                    safe_status = f"RELEASE_REJECTED_STALE(token={token},holder={safe_current_holder})"

            out_lines.append(f"ACT {idx} RELEASE {client_id} NAIVE:{naive_status} SAFE:{safe_status}")

    out_lines.append(f"SUMMARY NAIVE FINAL_VAL:{naive_storage_val} CORRUPTED_WRITES:{naive_corrupted_writes} HIJACKED_RELEASES:{naive_hijacked_releases}")
    out_lines.append(f"SUMMARY SAFE FINAL_VAL:{safe_storage_val} STALE_WRITES_REJECTED:{safe_stale_writes_rejected} STALE_RELEASES_REJECTED:{safe_stale_releases_rejected}")
    out_lines.append(f"SUMMARY ANOMALIES_PREVENTED:{safe_stale_writes_rejected + safe_stale_releases_rejected}")

    print("\n".join(out_lines))

if __name__ == "__main__":
    solve()
