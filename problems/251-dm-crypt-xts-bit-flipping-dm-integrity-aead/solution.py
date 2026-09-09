import json
import hashlib
import sys

def compute_tag(sector_num, ciphertext, seq, integrity_enabled=True, integrity_algo="hmac-sha256", replay_protection=False):
    if not integrity_enabled or integrity_algo == "none":
        return ""
    content = f"{sector_num}:{ciphertext}"
    if replay_protection:
        content += f":{seq}"
    return hashlib.sha256(content.encode()).hexdigest()[:32]

def encrypt_xts(sector_num, plaintext):
    h = hashlib.sha256(f"{sector_num}:{plaintext}".encode()).hexdigest()
    return f"enc_{h[:16]}"

def simulate_dm_crypt(data):
    cfg = data["device_config"]
    cipher = cfg.get("cipher", "aes-xts-plain64")
    sector_size = cfg.get("sector_size_bytes", 4096)
    integrity_enabled = cfg.get("integrity_enabled", False)
    integrity_algo = cfg.get("integrity_algorithm", "hmac-sha256")
    journal_mode = cfg.get("journal_mode", "journal")  # "journal" or "bitmap"
    journal_capacity = cfg.get("journal_capacity_sectors", 2048)
    journal_watermark = cfg.get("journal_watermark_percent", 80.0)
    replay_protection = cfg.get("replay_protection_enabled", False)

    disk_sectors = {}
    current_seq = 1
    journal_used = 0

    def get_tag(sec_num, ct, seq):
        return compute_tag(sec_num, ct, seq, integrity_enabled, integrity_algo, replay_protection)

    # Initialize sectors
    for s in data.get("initial_sectors", []):
        sec_num = s["sector_num"]
        pt = s.get("plaintext", "initial_data")
        seq = s.get("commit_seq", 100)
        ct = encrypt_xts(sec_num, pt)
        tag = get_tag(sec_num, ct, seq)
        disk_sectors[sec_num] = {
            "ciphertext": ct,
            "tag": tag,
            "commit_seq": seq,
            "is_corrupted": False,
            "plaintext": pt
        }

    # Metrics
    successful_reads = 0
    successful_writes = 0
    integrity_checksum_failures = 0
    silent_data_corruptions = 0
    replay_attacks_detected = 0
    replay_attacks_succeeded = 0
    journal_write_stalls = 0

    def write_sector(sec_num, plaintext):
        nonlocal current_seq, journal_used, journal_write_stalls, successful_writes
        current_seq += 1

        if integrity_enabled and journal_mode == "journal":
            journal_used += 1
            threshold = (journal_watermark / 100.0) * journal_capacity
            if journal_used > threshold:
                journal_write_stalls += 1
                journal_used = 0

        ct = encrypt_xts(sec_num, plaintext)
        tag = get_tag(sec_num, ct, current_seq)
        disk_sectors[sec_num] = {
            "ciphertext": ct,
            "tag": tag,
            "commit_seq": current_seq,
            "is_corrupted": False,
            "plaintext": plaintext
        }
        successful_writes += 1

    def read_sector(sec_num):
        nonlocal successful_reads, integrity_checksum_failures, silent_data_corruptions
        if sec_num not in disk_sectors:
            return False

        sec = disk_sectors[sec_num]
        ct = sec["ciphertext"]
        tag = sec["tag"]
        seq = sec["commit_seq"]
        is_corrupted = sec["is_corrupted"]

        if integrity_enabled:
            expected_tag = get_tag(sec_num, ct, seq)
            if tag != expected_tag or is_corrupted:
                integrity_checksum_failures += 1
                return False
            else:
                successful_reads += 1
                return True
        else:
            if is_corrupted:
                silent_data_corruptions += 1
                return True
            else:
                successful_reads += 1
                return True

    events = sorted(data.get("events", []), key=lambda e: e.get("time_sec", 0))
    for ev in events:
        ev_type = ev["type"]

        if ev_type == "WRITE_BIO":
            write_sector(ev["sector_num"], ev["plaintext"])

        elif ev_type == "READ_BIO":
            read_sector(ev["sector_num"])

        elif ev_type == "CORRUPT_SECTOR":
            sec_num = ev["sector_num"]
            if sec_num in disk_sectors:
                disk_sectors[sec_num]["is_corrupted"] = True
                disk_sectors[sec_num]["ciphertext"] += "_tampered"

        elif ev_type == "REPLAY_SECTOR":
            target_sec = ev["target_sector_num"]
            old_ct = ev["old_ciphertext"]
            old_tag = ev["old_tag"]
            old_seq = ev["old_seq"]

            curr = disk_sectors.get(target_sec)
            curr_seq = curr["commit_seq"] if curr else 0

            disk_sectors[target_sec] = {
                "ciphertext": old_ct,
                "tag": old_tag,
                "commit_seq": old_seq,
                "is_corrupted": False,
                "plaintext": "replayed_old_data"
            }

            if integrity_enabled:
                if replay_protection:
                    if old_seq < curr_seq:
                        replay_attacks_detected += 1
                        integrity_checksum_failures += 1
                else:
                    replay_attacks_succeeded += 1

        elif ev_type == "FLUSH_JOURNAL":
            journal_used = 0

    # Diagnosis Hierarchy
    if silent_data_corruptions > 0:
        root_cause = "SILENT_DATA_CORRUPTION_UNAUTHENTICATED_AES_XTS"
    elif replay_attacks_succeeded > 0:
        root_cause = "REPLAY_ATTACK_ACCEPTED_DUE_TO_MISSING_SEQUENCE_CHECK"
    elif integrity_checksum_failures > 0:
        root_cause = "INTEGRITY_TAMPER_DETECTED_AND_BLOCKED"
    elif journal_write_stalls >= 2:
        root_cause = "DM_INTEGRITY_JOURNAL_EXHAUSTION_WRITE_STALL"
    else:
        root_cause = "STABLE_AUTHENTICATED_ENCRYPTED_STORAGE"

    recommendations = []
    if not integrity_enabled:
        recommendations.append("ENABLE_DM_INTEGRITY_WITH_HMAC_OR_AEAD")
    if replay_attacks_succeeded > 0 or not replay_protection:
        recommendations.append("ENABLE_REPLAY_PROTECTION_SEQUENCE_COUNTER")
    if journal_write_stalls > 0 or (integrity_enabled and journal_mode == "journal" and journal_capacity <= 2048):
        recommendations.append("INCREASE_JOURNAL_SIZE_OR_SWITCH_TO_BITMAP")

    if not recommendations:
        recommendations.append("MAINTAIN_CURRENT_AUTHENTICATED_CRYPTO_SETTINGS")

    return {
        "final_state": {
            "sectors_count": len(disk_sectors),
            "journal_used_sectors": journal_used,
            "current_commit_seq": current_seq
        },
        "metrics": {
            "successful_reads": successful_reads,
            "successful_writes": successful_writes,
            "integrity_checksum_failures": integrity_checksum_failures,
            "silent_data_corruptions": silent_data_corruptions,
            "replay_attacks_detected": replay_attacks_detected,
            "replay_attacks_succeeded": replay_attacks_succeeded,
            "journal_write_stalls": journal_write_stalls
        },
        "root_cause": root_cause,
        "recommendations": recommendations
    }

def main():
    try:
        input_data = sys.stdin.read().strip()
        if not input_data:
            return
        data = json.loads(input_data)
        result = simulate_dm_crypt(data)
        print(json.dumps(result, indent=2))
    except Exception as e:
        sys.stderr.write(f"Error: {str(e)}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
